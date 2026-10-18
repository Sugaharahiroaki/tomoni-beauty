import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue
from apps.drafts.models import SnsPost
from apps.karte.models import Karte
from apps.profiles.models import Episode

from . import media, services
from .forms import ReelProfileForm, StartForm
from .models import BgmTrack, MediaAsset, ReelPost, ShotExample
from .publishing import AI_NOTICE, caption_for
from .recipes import FRAME_LABELS, TEMPLATES, frame_for


def _is_fetch(request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


def _post(request, pk):
    return get_object_or_404(ReelPost.objects.select_related("stylist", "customer", "karte", "bgm").prefetch_related("assets", "metrics", "takes"), pk=pk, stylist=request.stylist)


# ---------------------------------------------------------------------------
# ホーム（SNSタブ）
# ---------------------------------------------------------------------------
@stylist_required
def home(request):
    stylist = request.stylist
    posts = ReelPost.objects.filter(stylist=stylist)
    profile = services.profile_of(stylist)
    text_posts = SnsPost.objects.filter(stylist=stylist).exclude(status=SnsPost.Status.DISCARDED)[:5]
    context = {
        "in_progress": posts.exclude(status="PUBLISHED")[:8],
        "published": posts.filter(status="PUBLISHED")[:5],
        "month_count": services.month_count(stylist),
        "profile": profile,
        "options": services.options(stylist),
        "text_posts": text_posts,
        "recent_kartes": Karte.objects.filter(stylist=stylist).select_related("customer")[:5],
    }
    return render(request, "reels/home.html", context)


@stylist_required
def start(request):
    karte = None
    if request.GET.get("karte"):
        karte = get_object_or_404(Karte.objects.select_related("customer"), pk=request.GET["karte"], stylist=request.stylist)
    initial = {"menu_items": ", ".join(karte.menu_items or []) if karte else "", "uses_story": bool(karte and karte.customer.story_ok)}
    form = StartForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        post = services.start_post(request.stylist, cd.get("template_key") or None, karte=karte, menu_items=cd.get("menu_items"), purpose=request.GET.get("purpose"), uses_story=cd.get("uses_story", False), import_photos=cd.get("import_photos", True))
        return redirect("reels:workspace", pk=post.pk)
    usable_photos = [p for p in karte.photos.all() if p.usable_for_sns()] if karte else []
    return render(request, "reels/start.html", {"form": form, "karte": karte, "templates": TEMPLATES, "usable_photos": usable_photos, "month_count": services.month_count(request.stylist), "profile": services.profile_of(request.stylist)})


# ---------------------------------------------------------------------------
# 作業画面（撮る → 台本 → 動画 → 投稿）
# ---------------------------------------------------------------------------
@stylist_required
def workspace(request, pk: uuid.UUID):
    post = _post(request, pk)
    profile = services.profile_of(request.stylist)
    assets = list(post.assets.all())
    by_slot = {}
    for a in assets:
        by_slot.setdefault(a.slot, []).append(a)
    known = {s["key"] for s in post.shot_list}
    examples = {e.slot_key: e.image.url for e in ShotExample.objects.filter(template_key=post.template_key, active=True)}
    slots = [{**s, "frame": s.get("frame") or frame_for(post.template_key, s["key"]), "frame_label": FRAME_LABELS.get(s.get("frame", ""), ""), "assets": by_slot.get(s["key"], []), "example_url": examples.get(s["key"])} for s in post.shot_list]
    usable_ids = {str(a.id) for a in post.usable_assets()}
    editing = request.GET.get("edit") == "1" and post.status in ("READY", "FAILED")
    step = 1 if editing else post.step
    context = {
        "post": post,
        "profile": profile,
        "options": services.options(request.stylist),
        "slots": slots,
        "assets": assets,
        "extras": [a for a in assets if a.slot not in known],
        "usable_ids": usable_ids,
        "blocked_count": len([a for a in assets if str(a.id) not in usable_ids]),
        "step": step,
        "editing": editing,
        "bgm_tracks": BgmTrack.usable(),
        "takes": {t.scene_index: t.file.url for t in post.takes.all()},
        "asset_map": {str(a.id): a for a in assets},
        "caption_preview": caption_for(post, "instagram") if post.script else "",
        "ai_notice": AI_NOTICE,
        "metrics": services.latest_metrics(post),
        "episodes": {str(e.id): e for e in Episode.objects.filter(stylist=request.stylist)},
        "min_assets": services.MIN_ASSETS,
        "remaining": max(services.MIN_ASSETS - len(usable_ids), 0),
        "targets": [("instagram", "Instagram", profile.post_to_instagram, profile.instagram_connected), ("youtube", "YouTube", profile.post_to_youtube, profile.youtube_connected), ("threads", "Threads", profile.post_to_threads, profile.threads_connected)],
    }
    return render(request, "reels/workspace.html", context)


@stylist_required
def status_json(request, pk: uuid.UUID):
    post = get_object_or_404(ReelPost, pk=pk, stylist=request.stylist)
    return JsonResponse({"status": post.status, "done": not post.is_busy, "error": post.error})


@stylist_required
@require_POST
def asset_upload(request, pk: uuid.UUID):
    post = _post(request, pk)
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "写真か動画を選んでください。"}, status=400)
    if upload.size > media.MAX_UPLOAD_BYTES:
        return JsonResponse({"error": "ファイルが大きすぎます（200MBまで）。"}, status=400)
    try:
        kind = media.kind_of(upload.name, upload.content_type)
        asset = services.save_asset(post, upload, upload.name, upload.content_type, upload.size, kind, request.POST.get("slot", ""), face_visible=request.POST.get("face_visible") in ("1", "true", "on"))
    except media.MediaError as e:
        return JsonResponse({"error": str(e)}, status=400)
    if post.status in ("REVIEW", "READY", "FAILED"):
        pass  # 台本があるときは、素材を足しても台本はそのまま（確認画面で差し替え可）
    return JsonResponse({"ok": True, "asset": {"id": str(asset.id), "kind": asset.kind, "url": asset.file.url, "poster_url": asset.poster_url, "slot": asset.slot, "face_visible": asset.face_visible, "usable": str(asset.id) in {str(a.id) for a in post.usable_assets()}}})


@stylist_required
@require_POST
def asset_delete(request, pk: uuid.UUID, asset_id: uuid.UUID):
    post = _post(request, pk)
    asset = get_object_or_404(MediaAsset, pk=asset_id, post=post)
    asset.delete()
    if _is_fetch(request):
        return JsonResponse({"ok": True})
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def asset_face(request, pk: uuid.UUID, asset_id: uuid.UUID):
    post = _post(request, pk)
    asset = get_object_or_404(MediaAsset, pk=asset_id, post=post)
    asset.face_visible = not asset.face_visible
    asset.save(update_fields=["face_visible", "updated_at"])
    if _is_fetch(request):
        return JsonResponse({"ok": True, "face_visible": asset.face_visible, "usable": str(asset.id) in {str(a.id) for a in post.usable_assets()}})
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def script_generate(request, pk: uuid.UUID):
    post = _post(request, pk)
    if post.usable_assets().count() < services.MIN_ASSETS:
        messages.error(request, f"写真か動画を{services.MIN_ASSETS}つ以上追加してください（顔が写っている素材は顔出しOKのときだけ使えます）")
        return redirect("reels:workspace", pk=pk)
    post.status = "SCRIPTING"
    post.save(update_fields=["status", "updated_at"])
    enqueue("apps.reels.tasks.generate_script", str(post.id))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def script_edit(request, pk: uuid.UUID):
    """確認画面の保存。フォームの各欄を台本と投稿文に反映し、action=render なら動画作成へ。"""
    post = _post(request, pk)
    if not post.script:
        return redirect("reels:workspace", pk=pk)
    script = post.script
    changes = []
    for i, scene in enumerate(script.get("scenes", [])):
        change = {"scene": i}
        if f"caption_{i}" in request.POST:
            change["caption"] = request.POST.get(f"caption_{i}", "")
        if f"narration_{i}" in request.POST:
            change["narration"] = request.POST.get(f"narration_{i}", "")
        changes.append(change)
        for j, _shot in enumerate(scene.get("shots", [])):
            aid = request.POST.get(f"asset_{i}_{j}")
            if aid and aid != _shot.get("asset_id"):
                changes.append({"scene": i, "shot": j, "asset_id": aid})
    if "cta_text" in request.POST:
        changes.append({"scene": -1, "cta_text": request.POST.get("cta_text", "")})
    try:
        services.edit_script(post, changes)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("reels:workspace", pk=pk)

    post.ig_caption = request.POST.get("ig_caption", post.ig_caption)
    post.hashtags = [h.lstrip("#＃") for h in request.POST.get("hashtags", " ".join(post.hashtags)).replace("　", " ").split() if h.strip("#＃")]
    post.yt_title = request.POST.get("yt_title", post.yt_title)[:95]
    post.yt_description = request.POST.get("yt_description", post.yt_description)
    mode = request.POST.get("narration_mode")
    if mode in ("ai", "own", "none"):
        post.narration_mode = mode
    bgm_id = request.POST.get("bgm")
    if bgm_id:
        post.bgm = BgmTrack.usable().filter(pk=bgm_id).first() or post.bgm
    elif "bgm" in request.POST:
        post.bgm = None
    from .ai import forbidden_terms, pii_summary

    post.pii_check = pii_summary(post.script, forbidden_terms(post))
    post.save()

    if request.POST.get("action") == "render":
        if post.pii_errors:
            messages.error(request, "お客様の個人情報の可能性がある箇所があります。直してから動画を作ってください。")
            return redirect("reels:workspace", pk=pk)
        if not services.options(request.stylist)["ffmpeg_available"]:
            messages.error(request, "このサーバーに FFmpeg が入っていないため動画を作れません。")
            return redirect("reels:workspace", pk=pk)
        services.request_render(post)
        messages.success(request, "動画を作っています。2〜3分でできあがります。")
    else:
        messages.success(request, "保存しました")
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def take_upload(request, pk: uuid.UUID):
    post = _post(request, pk)
    upload = request.FILES.get("file")
    try:
        index = int(request.POST.get("scene_index"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "何番目のセリフか指定してください。"}, status=400)
    if upload is None:
        return JsonResponse({"error": "録音が見つかりません。"}, status=400)
    take = services.save_take(post, index, upload)
    return JsonResponse({"ok": True, "scene_index": index, "url": take.file.url})


@stylist_required
@require_POST
def render_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    try:
        services.request_render(post)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def schedule_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    when = request.POST.get("when") or "auto"
    if when == "custom":
        when = request.POST.get("at", "")
    try:
        services.schedule(post, when)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("reels:workspace", pk=pk)
    if post.status == "SCHEDULED":
        messages.success(request, "投稿を予約しました" if when != "now" else "投稿しています")
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def cancel_schedule_view(request, pk: uuid.UUID):
    services.cancel_schedule(_post(request, pk))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def delete_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    if post.status in ("PUBLISHED", "SCHEDULED", "RENDERING", "SCRIPTING"):
        messages.error(request, "この状態の投稿は削除できません")
        return redirect("reels:workspace", pk=pk)
    post.delete()
    messages.info(request, "投稿を削除しました（撮った写真・動画も消えます）")
    return redirect("reels:home")


# ---------------------------------------------------------------------------
# 履歴・設定
# ---------------------------------------------------------------------------
@stylist_required
def history(request):
    posts = list(ReelPost.objects.filter(stylist=request.stylist, status="PUBLISHED").prefetch_related("metrics"))
    rows = []
    best = None
    best_views = -1
    by_template = {}
    for p in posts:
        metrics = services.latest_metrics(p)
        views = sum(m.views or 0 for m in metrics) if metrics else None
        rows.append({"post": p, "metrics": metrics, "views": views})
        if views is not None:
            if views > best_views:
                best, best_views = p, views
            t = by_template.setdefault(p.template_key, {"label": p.template_label, "count": 0, "views": 0})
            t["count"] += 1
            t["views"] += views
    by_template_rows = sorted(({**t, "avg": int(t["views"] / t["count"])} for t in by_template.values()), key=lambda t: -t["avg"])
    return render(request, "reels/history.html", {"rows": rows, "best": best, "best_views": best_views if best else None, "by_template": by_template_rows})


@stylist_required
def settings_view(request):
    profile = services.profile_of(request.stylist)
    form = ReelProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("reels:settings")
    from .connect import available

    return render(request, "reels/settings.html", {"form": form, "profile": profile, "connect_available": available(), "options": services.options(request.stylist), "callback_base": f"{settings.SITE_URL}/reels/connect/"})


@stylist_required
@require_POST
def voice_preview(request):
    """入力した文字を選んだ声で試聴する（GEMINI_API_KEY が必要）"""
    from pathlib import Path

    from .engine.render import load_settings
    from .engine.tts import GeminiTTS, TTSError

    if not settings.GEMINI_API_KEY:
        return JsonResponse({"error": "声の試聴には GEMINI_API_KEY の設定が必要です。"}, status=400)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return HttpResponseBadRequest("invalid json")
    text = (body.get("text") or "今日はご来店ありがとうございました。").strip()[:80]
    profile = services.profile_of(request.stylist)
    engine_settings = load_settings()
    prompts = Path(__file__).with_name("prompts")
    cache = Path(settings.MEDIA_ROOT) / f"stylist_{request.stylist.id}" / "reels" / "cache" / "tts"
    tts = GeminiTTS(settings.GEMINI_API_KEY, engine_settings["tts"]["model"], body.get("voice") or profile.voice_name, (prompts / "tts_style.md").read_text(encoding="utf-8"), "", engine_settings["narration"]["loudness_lufs"], cache)
    try:
        wav, _ = tts.synthesize(text)
    except TTSError as e:
        return JsonResponse({"error": f"声を作れませんでした（{e}）"}, status=502)
    return JsonResponse({"url": settings.MEDIA_URL + Path(wav).relative_to(settings.MEDIA_ROOT).as_posix()})
