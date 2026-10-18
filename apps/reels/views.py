"""SNS投稿の画面：ホーム（今週のおすすめ）→ 素材 → 型 → フック → 出来上がり → 投稿／成果。"""
import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue
from apps.karte.models import Karte
from apps.profiles.models import Episode

from . import media, services, stock
from .content import STICKER_LABELS, STICKERS, finalize_checks
from .forms import ReelProfileForm
from .models import BgmTrack, MediaAsset, ReelPost, ShotExample, TypeRecommendation
from .post_types import FORMAT_LABELS, POST_TYPES, ROLE_GUIDES, ROLE_LABELS, ROLES, TYPE_LABELS, decide_format, missing_for, missing_roles_for
from .publishing import AI_NOTICE, caption_for
from .recipes import FRAME_LABELS, frame_for
from .recommend import asset_counts, recommend_for, record as record_recommendation, week_count, weekly_plan


def _is_fetch(request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


def _post(request, pk):
    return get_object_or_404(ReelPost.objects.select_related("stylist", "customer", "karte", "bgm", "tracked_link").prefetch_related("assets", "metrics", "takes"), pk=pk, stylist=request.stylist)


def _asset_json(post, asset):
    usable = str(asset.id) in {str(a.id) for a in post.usable_assets()}
    return {"id": str(asset.id), "kind": asset.kind, "url": asset.file.url, "poster_url": asset.poster_url, "slot": asset.slot, "role": asset.role, "role_label": asset.role_label, "face_visible": asset.face_visible, "usable": usable}


# ---------------------------------------------------------------------------
# ホーム（SNSタブ）・開始
# ---------------------------------------------------------------------------
@stylist_required
def home(request):
    stylist = request.stylist
    services.recover_stuck_posts(stylist)
    posts = ReelPost.objects.filter(stylist=stylist)
    profile = services.profile_of(stylist)
    context = {
        "in_progress": posts.exclude(status__in=["PUBLISHED", "SKIPPED"])[:8],
        "published": posts.filter(status="PUBLISHED")[:5],
        "week_count": week_count(stylist),
        "profile": profile,
        "options": services.options(stylist),
        "plan": weekly_plan(stylist),
        "overview": services.type_overview(stylist),
        "recent_kartes": Karte.objects.filter(stylist=stylist).select_related("customer")[:5],
        "needs_focus": not profile.focus_concerns,
    }
    return render(request, "reels/home.html", context)


@stylist_required
def start(request):
    """「投稿をつくる」。素材から始めるので、型は決めずに作成画面へ（今週のおすすめから来たときは型の希望を持っていく）"""
    if request.method != "POST":
        return redirect("reels:home")
    karte = None
    if request.POST.get("karte"):
        karte = get_object_or_404(Karte.objects.select_related("customer"), pk=request.POST["karte"], stylist=request.stylist)
    post = services.start_post(request.stylist, karte=karte, import_photos=True)
    want = request.POST.get("post_type", "")
    if want in POST_TYPES:
        TypeRecommendation.objects.create(stylist=request.stylist, post=post, post_type=want, alternatives=[a for a in request.POST.get("alternatives", "").split(",") if a in POST_TYPES][:2], reason=request.POST.get("reason", "")[:300], context={"source": "weekly_plan"})
        return redirect(f"{post.get_workspace_url()}?want={want}")
    return redirect("reels:workspace", pk=post.pk)


# ---------------------------------------------------------------------------
# 作成画面（素材 → 型 → フック → 出来上がり）
# ---------------------------------------------------------------------------
def _stage_for(post, request) -> int:
    if post.status in ("HOOKING",):
        return 2
    if post.status in ("SCRIPTING", "RENDERING", "REVIEW", "READY", "FAILED", "SCHEDULED", "PUBLISHED", "SKIPPED"):
        return 3
    step = request.GET.get("step")
    if step == "assets":
        return 0
    if step == "type":
        return 1
    if post.post_type and post.hooks:
        return 2
    if post.post_type and not post.hooks and request.GET.get("step") != "assets" and post.notes:
        return 2  # フックの生成に失敗 → やり直しボタン
    return 0


def _pending_recommendation(post):
    return post.recommendations.filter(reaction="pending").order_by("-created_at").first()


@stylist_required
@require_POST
def bulk_delete_view(request):
    deleted, kept = services.bulk_delete(request.stylist, request.POST.getlist("ids"))
    if deleted:
        messages.success(request, f"{deleted}件を削除しました" + (f"（投稿済み・予約済みの{kept}件は残しました）" if kept else ""))
    elif kept:
        messages.info(request, "投稿済み・予約済みの投稿は削除できません")
    else:
        messages.info(request, "削除する投稿を選んでください")
    return redirect("reels:home")


@stylist_required
def workspace(request, pk: uuid.UUID):
    services.recover_stuck_posts(request.stylist)
    post = _post(request, pk)
    profile = services.profile_of(request.stylist)
    assets = list(post.assets.all())
    usable_ids = {str(a.id) for a in post.usable_assets()}
    counts = asset_counts(post.usable_assets())
    stage = _stage_for(post, request)
    editing = request.GET.get("edit") == "1" and post.status in ("READY", "FAILED", "REVIEW") and post.output_format == "reel" and post.script
    want = request.GET.get("want") if request.GET.get("want") in POST_TYPES else ""
    context = {
        "post": post,
        "profile": profile,
        "options": services.options(request.stylist),
        "assets": assets,
        "usable_ids": usable_ids,
        "blocked_count": len([a for a in assets if str(a.id) not in usable_ids]),
        "counts": counts,
        "stage": stage,
        "editing": bool(editing),
        "roles": ROLES,
        "role_guides": ROLE_GUIDES,
        "want": want,
        "want_label": TYPE_LABELS.get(want, ""),
        "want_missing": missing_for(want, counts) if want else [],
        "library": services.library_assets(request.stylist, exclude_post=post) if stage <= 1 else [],
        "ai_notice": AI_NOTICE,
    }
    if stage == 1:
        rec = _pending_recommendation(post)
        if rec is None or rec.context.get("source") == "weekly_plan":
            computed = recommend_for(request.stylist, post, counts=counts)
            rec = record_recommendation(request.stylist, computed, post) if computed.post_type else None
        cards = []
        for key, t in POST_TYPES.items():
            miss = missing_for(key, counts)
            cards.append({"key": key, **t, "missing": miss, "missing_roles": missing_roles_for(key, counts), "available": not miss, "format": decide_format(key, counts), "format_label": FORMAT_LABELS[decide_format(key, counts)], "avoided": key in (profile.avoid_types or []), "recommended": bool(rec and rec.post_type == key), "alternative": bool(rec and key in (rec.alternatives or []))})
        context.update({"rec": rec, "cards": cards, "rec_card": next((c for c in cards if rec and c["key"] == rec.post_type), None)})
    elif stage == 2:
        context.update({"hooks": post.hooks, "regenerations_left": max(services.MAX_HOOK_REGENERATIONS - post.hook_regenerations, 0)})
    elif stage == 3:
        by_slot = {}
        for a in assets:
            by_slot.setdefault(a.slot, []).append(a)
        examples = {e.slot_key: e.image.url for e in ShotExample.objects.filter(template_key=post.template_key, active=True)} if post.template_key else {}
        context.update(
            {
                "slots": [{**s, "frame": s.get("frame") or frame_for(post.template_key, s["key"]), "frame_label": FRAME_LABELS.get(s.get("frame", ""), ""), "assets": by_slot.get(s["key"], []), "example_url": examples.get(s["key"])} for s in post.shot_list],
                "bgm_tracks": BgmTrack.usable(),
                "takes": {t.scene_index: t.file.url for t in post.takes.all()},
                "asset_map": {str(a.id): a for a in assets},
                "caption_preview": caption_for(post, "instagram") if (post.script or post.ig_caption) else "",
                "metrics": services.latest_metrics(post),
                "episodes": {str(e.id): e for e in Episode.objects.filter(stylist=request.stylist)},
                "targets": [("instagram", "Instagram", profile.post_to_instagram, profile.instagram_connected), ("youtube", "YouTube", profile.post_to_youtube, profile.youtube_connected), ("threads", "Threads", profile.post_to_threads, profile.threads_connected)],
                "link_url": services.tracked_link_url(post),
                "link_clicks": services.link_clicks(post),
                "stickers": [(k, STICKER_LABELS[k]) for k in STICKERS],
                "metric_fields": [(k, services.METRIC_LABELS[k], getattr(post, k)) for k in services.METRIC_FIELDS],
                "can_post": services.can_mark_posted(post),
                "hashtags_text": " ".join(f"#{h}" for h in post.hashtags),
                "caption_positions": [("auto", "自動（顔や髪を避ける）"), ("top", "上"), ("middle", "中央"), ("bottom", "下")],
            }
        )
    return render(request, "reels/workspace.html", context)


@stylist_required
def status_json(request, pk: uuid.UUID):
    post = get_object_or_404(ReelPost, pk=pk, stylist=request.stylist)
    return JsonResponse({"status": post.status, "done": not post.is_busy, "error": post.error})


# ------------------------------------------------------------------ 素材


@stylist_required
@require_POST
def asset_upload(request, pk: uuid.UUID):
    post = _post(request, pk)
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "写真か動画を選んでください。"}, status=400)
    if upload.size > media.MAX_UPLOAD_BYTES:
        return JsonResponse({"error": "ファイルが大きすぎます（200MBまで）。"}, status=400)
    role = request.POST.get("role", "")
    try:
        kind = media.kind_of(upload.name, upload.content_type)
        asset = services.save_asset(post, upload, upload.name, upload.content_type, upload.size, kind, request.POST.get("slot", ""), face_visible=request.POST.get("face_visible") in ("1", "true", "on"), role=role if role in ROLE_LABELS else "")
    except media.MediaError as e:
        return JsonResponse({"error": str(e)}, status=400)
    if post.template_key:
        services.assign_slots(post)
        asset.refresh_from_db()
    return JsonResponse({"ok": True, "asset": _asset_json(post, asset)})


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
        return JsonResponse({"ok": True, "asset": _asset_json(post, asset)})
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def asset_role(request, pk: uuid.UUID, asset_id: uuid.UUID):
    post = _post(request, pk)
    asset = get_object_or_404(MediaAsset, pk=asset_id, post=post)
    try:
        services.set_role(asset, request.POST.get("role", ""))
    except ValueError as exc:
        if _is_fetch(request):
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("reels:workspace", pk=pk)
    if post.template_key:
        services.assign_slots(post)
    if _is_fetch(request):
        return JsonResponse({"ok": True, "asset": _asset_json(post, asset), "counts": asset_counts(post.usable_assets())})
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def library_add(request, pk: uuid.UUID):
    """前に撮った素材をこの投稿に足す"""
    post = _post(request, pk)
    asset = get_object_or_404(MediaAsset, pk=request.POST.get("asset_id"), post__stylist=request.stylist)
    try:
        new = services.add_from_library(post, asset)
    except (ValueError, media.MediaError) as exc:
        if _is_fetch(request):
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("reels:workspace", pk=pk)
    if _is_fetch(request):
        return JsonResponse({"ok": True, "asset": _asset_json(post, new)})
    messages.success(request, f"「{new.role_label}」の素材を足しました")
    return redirect(f"{post.get_workspace_url()}?step={request.POST.get('step', 'assets')}")


@stylist_required
def stock_search(request, pk: uuid.UUID):
    _post(request, pk)
    try:
        items = stock.search(request.GET.get("q", ""), request.GET.get("kind", "video"))
    except stock.StockError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"items": items})


@stylist_required
@require_POST
def stock_add(request, pk: uuid.UUID):
    post = _post(request, pk)
    item = {k: request.POST.get(k, "") for k in ("id", "kind", "url", "thumb", "credit", "page")}
    try:
        asset = stock.add_to_post(post, item, role=request.POST.get("role", "other"))
    except (stock.StockError, media.MediaError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if post.template_key:
        services.assign_slots(post)
    return JsonResponse({"ok": True, "asset": _asset_json(post, asset)})


# ------------------------------------------------------------------ 型・フック・本文


@stylist_required
@require_POST
def choose_type_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    if post.is_busy or post.status not in ("DRAFT",):
        messages.error(request, "この投稿はすでに型を決めて先へ進んでいます。")
        return redirect("reels:workspace", pk=pk)
    key = request.POST.get("post_type", "")
    if key not in POST_TYPES:
        messages.error(request, "型を選んでください。")
        return redirect(f"{post.get_workspace_url()}?step=type")
    counts = asset_counts(post.usable_assets())
    miss = missing_for(key, counts)
    if miss and request.POST.get("force") != "1":
        messages.error(request, f"{TYPE_LABELS[key]}には足りない素材があります：" + "／".join(miss))
        return redirect(f"{post.get_workspace_url()}?step=type")
    rec = _pending_recommendation(post)
    mode = "ai" if (rec and rec.post_type == key and request.POST.get("mode") != "manual") else "manual"
    services.choose_type(post, key, mode, recommendation=rec)
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def hooks_regenerate(request, pk: uuid.UUID):
    post = _post(request, pk)
    try:
        services.request_hooks(post, regenerate=bool(post.hooks))
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def choose_hook_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    if post.is_busy:
        return redirect("reels:workspace", pk=pk)
    custom = (request.POST.get("custom_text") or "").strip()
    index = request.POST.get("hook")
    try:
        services.choose_hook(post, index=None if custom else index, text=custom or None)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def content_regenerate(request, pk: uuid.UUID):
    post = _post(request, pk)
    try:
        services.regenerate_content(post)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def content_to_reel(request, pk: uuid.UUID):
    """フィード・ストーリーズの投稿を、同じフックで動画にする"""
    post = _post(request, pk)
    try:
        services.convert_to_reel(post)
        messages.success(request, "同じフックで動画を作っています。2〜3分でできあがります。")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def content_update(request, pk: uuid.UUID):
    """フィード・ストーリーズ・キャプションの手直し（動画の台本は script_edit）"""
    post = _post(request, pk)
    data = {"ig_caption": request.POST.get("ig_caption", post.ig_caption), "hashtags": request.POST.get("hashtags", " ".join(f"#{h}" for h in post.hashtags)), "cover_text": request.POST.get("cover_text", post.cover_text)}
    if post.output_format == "feed":
        slides = []
        i = 0
        while f"slide_title_{i}" in request.POST or f"slide_text_{i}" in request.POST:
            slides.append({"title": request.POST.get(f"slide_title_{i}", ""), "text": request.POST.get(f"slide_text_{i}", "")})
            i += 1
        if slides:
            data["slides"] = slides
    elif post.output_format == "stories":
        stories = []
        i = 0
        while f"story_text_{i}" in request.POST:
            stype = request.POST.get(f"story_sticker_type_{i}", "none")
            stype = stype if stype in STICKERS else "none"
            stories.append({"text": request.POST.get(f"story_text_{i}", ""), "sticker": {"type": stype, "label": STICKER_LABELS[stype], "text": request.POST.get(f"story_sticker_text_{i}", "")[:60]}})
            i += 1
        if stories:
            data["stories"] = stories
    services.update_text_content(post, data)
    messages.success(request, "保存して、チェックをやり直しました")
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def mark_posted_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    try:
        services.mark_posted(post)
        messages.success(request, "投稿済みにしました。あとで成果（保存・DMなど）を記録できます")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def skip_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    services.skip_post(post)
    messages.info(request, "この投稿をスキップしました（記録は残ります）")
    return redirect("reels:home")


@stylist_required
@require_POST
def metrics_update_view(request, pk: uuid.UUID):
    post = _post(request, pk)
    try:
        services.update_metrics(post, request.POST)
        messages.success(request, "成果を記録しました")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or post.get_workspace_url())


# ------------------------------------------------------------------ 動画の台本（既存）


@stylist_required
@require_POST
def script_generate(request, pk: uuid.UUID):
    """台本をAIで作り直す（動画のとき）。フックを決めていれば本文の作り直しと同じ"""
    post = _post(request, pk)
    if post.usable_assets().count() < services.MIN_ASSETS:
        messages.error(request, "写真か動画を1つ以上追加してください（顔が写っている素材は顔出しOKのときだけ使えます）")
        return redirect("reels:workspace", pk=pk)
    if post.selected_hook:
        services.regenerate_content(post)
        return redirect("reels:workspace", pk=pk)
    post.status = "SCRIPTING"
    post.save(update_fields=["status", "updated_at"])
    enqueue("apps.reels.tasks.generate_script", str(post.id))
    return redirect("reels:workspace", pk=pk)


@stylist_required
@require_POST
def script_edit(request, pk: uuid.UUID):
    """台本の確認画面の保存。各欄を台本と投稿文に反映し、action=render なら動画作成へ。"""
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
        if f"caption_pos_{i}" in request.POST:
            change["caption_pos"] = request.POST.get(f"caption_pos_{i}", "auto")
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
    finalize_checks(post)
    post.save()

    if request.POST.get("action") == "render":
        ok, reason = services.can_mark_posted(post)
        if not ok:
            messages.error(request, reason.replace("投稿済みにして", "動画を作って"))
            return redirect(f"{post.get_workspace_url()}?edit=1")
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
    if post.status in ("PUBLISHED", "SCHEDULED", "RENDERING", "SCRIPTING", "HOOKING"):
        messages.error(request, "この状態の投稿は削除できません")
        return redirect("reels:workspace", pk=pk)
    post.delete()
    messages.info(request, "投稿を削除しました（撮った写真・動画も消えます）")
    return redirect("reels:home")


# ---------------------------------------------------------------------------
# 履歴（型の内訳・成果の手入力）・設定
# ---------------------------------------------------------------------------
@stylist_required
def history(request):
    stylist = request.stylist
    posts = list(ReelPost.objects.filter(stylist=stylist, status__in=["PUBLISHED", "READY", "SCHEDULED"]).prefetch_related("metrics").order_by("-published_at", "-created_at")[:60])
    rows = []
    by_type: dict[str, dict] = {}
    for p in posts:
        metrics = services.latest_metrics(p)
        views = sum(m.views or 0 for m in metrics) if metrics else None
        score = p.manual_result_score
        rows.append({"post": p, "metrics": metrics, "views": views, "score": score, "link_clicks": services.link_clicks(p), "metric_fields": [(k, services.METRIC_LABELS[k], getattr(p, k)) for k in services.METRIC_FIELDS]})
        if p.post_type and score is not None:
            t = by_type.setdefault(p.post_type, {"label": p.type_label, "icon": POST_TYPES[p.post_type]["icon"], "count": 0, "score": 0.0})
            t["count"] += 1
            t["score"] += score
    by_type_rows = sorted(({**t, "avg": round(t["score"] / t["count"], 1)} for t in by_type.values()), key=lambda t: -t["avg"])
    return render(request, "reels/history.html", {"rows": rows, "by_type": by_type_rows, "overview": services.type_overview(stylist), "metric_labels": services.METRIC_LABELS})


def _concern_suggestions(stylist) -> list[str]:
    """得意な悩みの候補：インタビューQ4の回答と、カルテに多い悩み"""
    from apps.profiles.models import InterviewAnswer

    out: list[str] = []
    answer = InterviewAnswer.objects.filter(stylist=stylist, question__order=4, status="done").first()
    if answer and answer.transcript:
        for part in answer.transcript.replace("。", "、").split("、"):
            part = part.strip()
            if 2 <= len(part) <= 20 and part not in out:
                out.append(part)
    counts: dict[str, int] = {}
    for concerns in Karte.objects.filter(stylist=stylist).values_list("concerns", flat=True)[:100]:
        for c in concerns or []:
            counts[c] = counts.get(c, 0) + 1
    for c, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        if c not in out:
            out.append(c)
    return out[:8]


@stylist_required
def settings_view(request):
    profile = services.profile_of(request.stylist)
    form = ReelProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("reels:settings")
    from .connect import available

    return render(request, "reels/settings.html", {"form": form, "profile": profile, "connect_available": available(), "options": services.options(request.stylist), "callback_base": f"{settings.SITE_URL}/reels/connect/", "suggestions": _concern_suggestions(request.stylist), "types": POST_TYPES})


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
