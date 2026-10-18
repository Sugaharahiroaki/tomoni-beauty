"""SNS投稿の業務ロジック（開始・素材と役割・型の決定・フック・出来上がり・投稿・成果・日次処理）。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.core.jobs import enqueue

from . import media
from .checks import hype_findings
from .connect import available as connect_available
from .connect import refresh_instagram_tokens, refresh_threads_tokens
from .stock import available as stock_available
from .models import MediaAsset, NarrationTake, ReelPost, ReelProfile, RenderJob
from .post_types import POST_TYPES, ROLE_LABELS, ROLE_SLOTS, TYPE_LABELS, composition_for, decide_format, type_for_composition
from .publishing import best_time, fetch_metrics, publish_post
from .recipes import TEMPLATES, features_stylist, shot_list, theme_for
from .recommend import asset_counts, choose_theme, week_count

log = logging.getLogger(__name__)
MIN_ASSETS = 1  # 動画は素材1つからでも作れる。型ごとに必要な素材は post_types.needs で判定する
MAX_HOOK_REGENERATIONS = 3


def profile_of(stylist) -> ReelProfile:
    profile, created = ReelProfile.objects.get_or_create(stylist=stylist)
    if created and not profile.brand_name:
        profile.brand_name = stylist.salon_name or stylist.display_name
        profile.save(update_fields=["brand_name", "updated_at"])
    return profile


def options(stylist) -> dict:
    from .engine.audio import ffmpeg_available
    from .engine.tts import VOICES

    return {
        "ai_available": not settings.AI_FAKE,
        "tts_available": bool(settings.GEMINI_API_KEY),
        "ffmpeg_available": ffmpeg_available(),
        "connect_available": connect_available(),
        "stock_available": stock_available(),
        "voices": VOICES,
        "types": [{"key": k, **t} for k, t in POST_TYPES.items()],
    }


# ---------------------------------------------------------------------------
# 開始
# ---------------------------------------------------------------------------
@transaction.atomic
def start_post(stylist, post_type: str | None = None, karte=None, menu_items: list[str] | None = None, uses_story: bool | None = None, import_photos: bool = True, template_key: str | None = None, selection_mode: str = "") -> ReelPost:
    """投稿を始める。型はあとで決めてもよい（素材から始める）。template_key は構成を直接指定したいとき（見本・テスト）"""
    profile = profile_of(stylist)
    menu_items = menu_items or (list(karte.menu_items or []) if karte else [])
    customer = karte.customer if karte else None
    if uses_story is None:
        uses_story = bool(customer and customer.story_ok)
    post = ReelPost.objects.create(
        stylist=stylist,
        karte=karte,
        customer=customer,
        menu_items=menu_items,
        narration_mode=profile.narration_mode,
        ai_label=profile.ai_label,
        uses_story=bool(uses_story and customer and customer.story_ok),
        face_allowed=(customer.face_ok if customer else False),
    )
    if karte and import_photos:
        import_karte_photos(post, karte)
    if template_key in TEMPLATES and not post_type:
        post_type = type_for_composition(template_key)
    if post_type in POST_TYPES:
        choose_type(post, post_type, selection_mode or "manual", composition=template_key if template_key in TEMPLATES else None, start_hooks=False)
    return post


def import_karte_photos(post: ReelPost, karte) -> int:
    """カルテの写真のうち、掲載できるもの（写真OK・顔出しの条件を満たす）だけを素材として取り込む。役割はカルテの印（ビフォー／アフター）"""
    count = 0
    for photo in karte.photos.all():
        if not photo.usable_for_sns():
            continue
        try:
            with photo.image.open("rb") as f:
                content = ContentFile(f.read(), name=Path(photo.image.name).name)
        except (OSError, ValueError):
            continue
        try:
            save_asset(post, content, content.name, "image/jpeg", content.size, "photo", "", face_visible=photo.face_visible, source="karte", karte_photo=photo, role=photo.role or "after")
            count += 1
        except media.MediaError:
            continue
    return count


# ---------------------------------------------------------------------------
# 素材と役割
# ---------------------------------------------------------------------------
def save_asset(post: ReelPost, fileobj, filename: str, content_type: str, size: int, kind: str, slot: str, face_visible: bool = False, **extra) -> MediaAsset:
    asset = MediaAsset(post=post, kind=kind, slot=slot, order_index=post.assets.count(), bytes=size, face_visible=face_visible, **extra)
    try:
        if kind == "photo":
            content, asset.width, asset.height, asset.taken_at = media.prepare_photo(fileobj)
            asset.mime = "image/jpeg"
            asset.file.save(content.name, content, save=False)
        else:
            asset.mime = content_type or "video/mp4"
            asset.file.save(filename, fileobj, save=False)
            ext = asset.file.name.rsplit(".", 1)[-1].lower()
            if ext not in ("mp4", "mov", "m4v"):
                converted = media.to_mp4(asset.file.path)
                old_name = asset.file.name
                with open(converted, "rb") as f:
                    asset.file.save(Path(old_name).stem + ".mp4", File(f), save=False)
                asset.file.storage.delete(old_name)
                converted.unlink(missing_ok=True)
                asset.mime = "video/mp4"
            asset.width, asset.height, asset.duration_sec, taken = media.probe_video(asset.file.path)
            asset.taken_at = taken
            asset.best_start = media.best_start(asset.file.path, asset.duration_sec)
            poster = media.poster_frame(asset.file.path, (asset.best_start or 0) + 0.3)
            if poster:
                name = asset.file.name.rsplit(".", 1)[0] + "_poster.jpg"
                stored = asset.file.storage.save(name, ContentFile(poster))
                asset.analysis = {"poster_name": stored, "poster_url": asset.file.storage.url(stored)}
    except media.MediaError:
        if asset.file and asset.file.name:
            asset.file.storage.delete(asset.file.name)
        raise
    if asset.taken_at is None:
        asset.taken_at = timezone.now()
    if not asset.role:
        asset.role = guess_role(post, asset)
    asset.save()
    return asset


def guess_role(post: ReelPost, asset: MediaAsset) -> str:
    """役割の推定：動画＝施術中（人柄の型なら本人）、カルテの写真＝カルテの印、写真が2枚以上なら撮影が一番早いもの＝ビフォー、ほかはアフター"""
    if asset.kind == "video":
        return "self" if post.post_type == "personality" else "process"
    if asset.source == "karte" and asset.karte_photo_id:
        return asset.karte_photo.role or "after"
    others = list(post.assets.filter(kind="photo").exclude(pk=asset.pk))
    if others and not any(a.role == "before" for a in others):
        earliest = min(others + [asset], key=lambda a: (a.taken_at or timezone.now(), a.order_index))
        if earliest.pk == asset.pk:
            return "before"
    return "after"


def set_role(asset: MediaAsset, role: str) -> MediaAsset:
    if role not in ROLE_LABELS:
        raise ValueError("役割の値が正しくありません。")
    if asset.source == "stock" and role not in ("other", "process"):
        raise ValueError("ネットの素材は「その他」か「施術中」にだけ使えます（自分の施術・お客様・本人として見せない）。")
    asset.role = role
    asset.save(update_fields=["role", "updated_at"])
    return asset


def assign_slots(post: ReelPost) -> None:
    """役割 → 構成の撮影リスト項目。先に挙げた項目から順に埋め、足りなければ最後の項目に重ねる"""
    prefs = ROLE_SLOTS.get(post.template_key)
    if not prefs:
        return
    used: set[str] = set()
    for a in post.assets.order_by("order_index", "created_at"):
        choices = prefs.get(a.role or "other") or prefs.get("other") or []
        slot = next((s for s in choices if s not in used), choices[-1] if choices else "")
        used.add(slot)
        if a.slot != slot:
            a.slot = slot
            a.save(update_fields=["slot", "updated_at"])


LIBRARY_ROLES = ("self", "process", "other")


def library_assets(stylist, exclude_post: ReelPost | None = None, limit: int = 24) -> list[MediaAsset]:
    """前に撮った使い回せる素材（本人・施術中・店内など）。お客様の写真（ビフォー／アフター）は入れない"""
    qs = MediaAsset.objects.filter(post__stylist=stylist, role__in=LIBRARY_ROLES).exclude(source="karte").select_related("post").order_by("-created_at")
    if exclude_post is not None:
        qs = qs.exclude(post=exclude_post)
    seen: set = set()
    out: list[MediaAsset] = []
    for a in qs:
        key = (a.bytes, a.kind, a.role)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= limit:
            break
    return out


def add_from_library(post: ReelPost, asset: MediaAsset) -> MediaAsset:
    """前の投稿の素材をこの投稿にコピーして足す"""
    if asset.post.stylist_id != post.stylist_id:
        raise ValueError("この素材は使えません。")
    if asset.role not in LIBRARY_ROLES:
        raise ValueError("お客様の写真は、その投稿の中でだけ使えます。")
    with asset.file.open("rb") as f:
        new = save_asset(post, File(f, name=Path(asset.file.name).name), Path(asset.file.name).name, asset.mime, asset.bytes, asset.kind, "", face_visible=asset.face_visible, role=asset.role, source="stock" if asset.source == "stock" else "library")
    if asset.source == "stock":
        new.analysis = {**(new.analysis or {}), **{k: v for k, v in (asset.analysis or {}).items() if k in ("stock", "credit", "page")}}
        new.save(update_fields=["analysis", "updated_at"])
    if post.template_key:
        assign_slots(post)
    return new


def counts_for(post: ReelPost) -> dict:
    return asset_counts(post.usable_assets())


# ---------------------------------------------------------------------------
# 型の決定 → フック → 出来上がり
# ---------------------------------------------------------------------------
def choose_type(post: ReelPost, post_type: str, mode: str = "manual", recommendation=None, composition: str | None = None, start_hooks: bool = True) -> ReelPost:
    if post_type not in POST_TYPES:
        raise ValueError("型の値が正しくありません。")
    counts = counts_for(post)
    has_intro = ReelPost.objects.filter(stylist=post.stylist, template_key="self_intro").exclude(pk=post.pk).exclude(status="SKIPPED").exists()
    comp = composition if composition in TEMPLATES else composition_for(post_type, counts, has_intro)
    post.post_type = post_type
    post.selection_mode = mode if mode in ("manual", "ai") else "manual"
    post.template_key = comp
    post.shot_list = shot_list(comp)
    post.output_format = decide_format(post_type, counts)
    post.theme = choose_theme(post.stylist, post)
    post.theme_title = theme_for(comp, post.menu_items)
    if not post.customer_id:
        post.face_allowed = features_stylist(comp)
    post.hooks, post.selected_hook, post.hook_regenerations = [], {}, 0
    post.status = "DRAFT"
    post.save()
    # 人柄の型で動画が本人の映像なら、役割も「本人」に寄せる
    if post_type == "personality":
        for a in post.assets.filter(kind="video", role="process"):
            a.role = "self"
            a.save(update_fields=["role", "updated_at"])
    assign_slots(post)
    if recommendation is not None:
        same = recommendation.post_type == post_type
        recommendation.react("accepted" if same else "changed", "" if same else post_type)
        if recommendation.post_id is None:
            recommendation.post = post
            recommendation.save(update_fields=["post", "updated_at"])
    if start_hooks:
        request_hooks(post)
    return post


def request_hooks(post: ReelPost, regenerate: bool = False) -> ReelPost:
    if regenerate:
        if post.hook_regenerations >= MAX_HOOK_REGENERATIONS:
            raise ValueError(f"フックの作り直しは{MAX_HOOK_REGENERATIONS}回までです。案を少し書き換えて使ってください。")
        post.hook_regenerations += 1
    post.status = "HOOKING"
    post.save(update_fields=["status", "hook_regenerations", "updated_at"])
    enqueue("apps.reels.tasks.generate_hooks", str(post.id))
    return post


def choose_hook(post: ReelPost, index: int | None = None, text: str | None = None) -> ReelPost:
    if text and text.strip():
        hook = {"type": "custom", "label": "自分で書いた", "text": text.strip()[:60], "visual": "", "hype": [f["text"] for f in hype_findings([("フック", text)])]}
    else:
        try:
            hook = post.hooks[int(index)]
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError("フックを選んでください。") from exc
    if hook.get("hype"):
        raise ValueError("誇大表現（" + "・".join(hook["hype"]) + "）が入っています。別の案を選ぶか、言い換えてください。")
    post.selected_hook = hook
    post.status = "SCRIPTING"
    post.notes = []
    post.save(update_fields=["selected_hook", "status", "notes", "updated_at"])
    enqueue("apps.reels.tasks.generate_content", str(post.id))
    return post


def convert_to_reel(post: ReelPost) -> ReelPost:
    """写真だけの投稿（フィード・ストーリーズ）を、同じフックで動画にする"""
    if not post.selected_hook:
        raise ValueError("先にフックを選んでください。")
    if not post.usable_assets().exists():
        raise ValueError("動画にするには写真か動画が1つ以上必要です。")
    post.output_format = "reel"
    post.status = "SCRIPTING"
    post.notes = []
    post.save(update_fields=["output_format", "status", "notes", "updated_at"])
    enqueue("apps.reels.tasks.generate_content", str(post.id))
    return post


def regenerate_content(post: ReelPost) -> ReelPost:
    """同じフックで本文（台本）を作り直す"""
    if not post.selected_hook:
        raise ValueError("先にフックを選んでください。")
    post.status = "SCRIPTING"
    post.save(update_fields=["status", "updated_at"])
    enqueue("apps.reels.tasks.generate_content", str(post.id))
    return post


# ---------------------------------------------------------------------------
# 台本の修正・動画・予約
# ---------------------------------------------------------------------------
def edit_script(post: ReelPost, changes: list[dict]) -> None:
    script = post.script or {}
    asset_ids = {str(a.id) for a in post.usable_assets()}
    for change in changes:
        i = int(change.get("scene", -1))
        if i == -1 and "cta_text" in change:
            script.setdefault("cta", {})["text"] = str(change["cta_text"])[:30]
            continue
        if not 0 <= i < len(script.get("scenes", [])):
            raise ValueError("修正する場面の番号が正しくありません。")
        scene = script["scenes"][i]
        for field in ("caption", "narration"):
            if field in change:
                scene[field] = str(change[field])[:80]
        if "caption_pos" in change:
            from .engine.layout import POSITIONS

            scene["caption_pos"] = change["caption_pos"] if change["caption_pos"] in POSITIONS else "auto"
        if "asset_id" in change:
            if change["asset_id"] not in asset_ids:
                raise ValueError("差し替える写真が見つかりません。")
            j = int(change.get("shot", 0))
            if 0 <= j < len(scene["shots"]):
                scene["shots"][j]["asset_id"] = change["asset_id"]
    post.script = script
    if post.status in ("READY", "FAILED", "REVIEW"):
        post.status = "REVIEW"
    post.save(update_fields=["script", "status", "updated_at"])


def update_text_content(post: ReelPost, data: dict) -> ReelPost:
    """フィード・ストーリーズ・キャプションの手直し"""
    from .content import finalize_checks

    if "ig_caption" in data:
        post.ig_caption = (data.get("ig_caption") or "").strip()
    if "hashtags" in data:
        post.hashtags = [h.lstrip("#＃") for h in (data.get("hashtags") or "").replace("　", " ").split() if h.strip("#＃")][:20]
    if "cover_text" in data:
        post.cover_text = (data.get("cover_text") or "").strip()[:60]
    if "slides" in data:
        post.carousel = [{"title": (s.get("title") or "").strip()[:40], "text": (s.get("text") or "").strip()[:200]} for s in data["slides"] if (s.get("title") or s.get("text"))][:10]
    if "stories" in data:
        post.stories = [{"text": (s.get("text") or "").strip()[:120], "sticker": s.get("sticker") or {"type": "none", "label": "なし", "text": ""}} for s in data["stories"] if s.get("text")][:4]
    finalize_checks(post)
    post.save()
    return post


def request_render(post: ReelPost) -> RenderJob:
    if not post.script:
        raise ValueError("先に台本を作ってください。")
    job = RenderJob.objects.filter(post=post, status__in=["queued", "running"]).first()
    post.status = "RENDERING"
    post.save(update_fields=["status", "updated_at"])  # enqueue より先に保存（同期実行では enqueue 中に READY になる）
    if job is None:
        job = RenderJob.objects.create(post=post)
        enqueue("apps.reels.tasks.run_render_job", job.id)
    post.refresh_from_db(fields=["status"])
    return job


def schedule(post: ReelPost, when: str) -> ReelPost:
    if not post.video:
        raise ValueError("先に動画を作ってください。")
    if when == "now":
        at = timezone.now()
    elif when == "auto":
        at = best_time()
    else:
        try:
            at = datetime.fromisoformat(when)
        except ValueError as exc:
            raise ValueError("日時の形式が正しくありません。") from exc
        at = timezone.make_aware(at) if timezone.is_naive(at) else at
    post.scheduled_at, post.status = at, "SCHEDULED"
    post.save(update_fields=["scheduled_at", "status", "updated_at"])
    if when == "now":
        enqueue("apps.reels.tasks.publish_now", str(post.id))
    return post


def cancel_schedule(post: ReelPost) -> ReelPost:
    if post.status == "SCHEDULED":
        post.status, post.scheduled_at = "READY", None
        post.save(update_fields=["status", "scheduled_at", "updated_at"])
    return post


def save_take(post: ReelPost, scene_index: int, upload) -> NarrationTake:
    NarrationTake.objects.filter(post=post, scene_index=scene_index).delete()
    take = NarrationTake(post=post, scene_index=scene_index)
    take.file.save(getattr(upload, "name", "") or "take.webm", upload, save=True)
    return take


# ---------------------------------------------------------------------------
# 止まった投稿の復帰・まとめて削除
# ---------------------------------------------------------------------------
STUCK_AFTER = timedelta(minutes=15)


def recover_stuck_posts(stylist) -> int:
    """「作成中」のまま止まった投稿を直す。動画ができていれば出来上がり、途中で止まっていれば失敗（作り直せる）に"""
    now = timezone.now()
    n = 0
    for post in ReelPost.objects.filter(stylist=stylist, status__in=["RENDERING", "SCRIPTING", "HOOKING"]):
        if post.status == "RENDERING":
            job = post.render_jobs.order_by("-created_at").first()
            if job is not None and job.status == "done" and post.video:
                post.status = "READY"
            elif job is not None and job.status == "failed":
                post.status, post.error = "FAILED", post.error or job.error[:2000]
            elif job is None or job.updated_at < now - STUCK_AFTER:
                if job is not None:
                    job.status, job.error = "failed", "途中で止まりました"
                    job.save(update_fields=["status", "error", "updated_at"])
                post.status = "READY" if post.video else "FAILED"
                if not post.video:
                    post.error = "動画の作成が途中で止まりました。もう一度「動画をつくる」を押してください。"
            else:
                continue
        elif post.updated_at < now - STUCK_AFTER:
            post.status = "REVIEW" if post.script else "DRAFT"
            post.notes = ["作業が途中で止まりました。もう一度お試しください。"]
        else:
            continue
        post.save()
        n += 1
    return n


PROTECTED_STATUSES = ("PUBLISHED", "SCHEDULED")


def bulk_delete(stylist, ids: list[str]) -> tuple[int, int]:
    """選んだ投稿を削除する。投稿済み・予約済みは残す。戻り値は（削除した数, 残した数）"""
    qs = ReelPost.objects.filter(stylist=stylist, pk__in=[i for i in ids if i])
    kept = qs.filter(status__in=PROTECTED_STATUSES).count()
    targets = list(qs.exclude(status__in=PROTECTED_STATUSES))
    for post in targets:
        post.delete()
    return len(targets), kept


# ---------------------------------------------------------------------------
# 投稿済み・スキップ・成果
# ---------------------------------------------------------------------------
def can_mark_posted(post: ReelPost) -> tuple[bool, str]:
    if post.pii_errors:
        return False, "お客様の個人情報の可能性がある箇所があります。直してから投稿済みにしてください。"
    if post.hype_errors:
        return False, "誇大表現（" + "・".join(sorted({f['text'] for f in post.hype_errors})) + "）が残っています。直してから投稿済みにしてください。"
    return True, ""


def mark_posted(post: ReelPost) -> ReelPost:
    ok, reason = can_mark_posted(post)
    if not ok:
        raise ValueError(reason)
    post.status = "PUBLISHED"
    post.published_at = post.published_at or timezone.now()
    post.publish_result = {**(post.publish_result or {}), "manual": True}
    post.save(update_fields=["status", "published_at", "publish_result", "updated_at"])
    rec = post.recommendation
    if rec and rec.reaction == "pending":
        rec.react("accepted" if rec.post_type == post.post_type else "changed", "" if rec.post_type == post.post_type else post.post_type)
    return post


def skip_post(post: ReelPost) -> ReelPost:
    post.status = "SKIPPED"
    post.save(update_fields=["status", "updated_at"])
    rec = post.recommendation
    if rec and rec.reaction in ("pending", "accepted"):
        rec.react("skipped")
    return post


METRIC_FIELDS = ["m_saves", "m_profile_visits", "m_link_clicks", "m_dms", "m_new_customers"]
METRIC_LABELS = {"m_saves": "保存", "m_profile_visits": "プロフィールアクセス", "m_link_clicks": "予約リンククリック", "m_dms": "DM", "m_new_customers": "インスタ経由の新規"}


def update_metrics(post: ReelPost, data: dict) -> ReelPost:
    for key in METRIC_FIELDS:
        raw = data.get(key)
        raw = raw.strip() if isinstance(raw, str) else raw
        if raw in ("", None):
            setattr(post, key, None)
        else:
            try:
                setattr(post, key, max(int(raw), 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{METRIC_LABELS[key]}は数字で入れてください。") from exc
    post.metrics_note = (data.get("metrics_note") or "")[:200]
    post.metrics_updated_at = timezone.now()
    post.save(update_fields=[*METRIC_FIELDS, "metrics_note", "metrics_updated_at", "updated_at"])
    return post


def ensure_tracked_link(post: ReelPost):
    """ストーリーズのリンクスタンプ用に、クリックを数えられる予約リンクを発行する"""
    if post.tracked_link_id or not post.stylist.hotpepper_url:
        return post.tracked_link
    from apps.lineapp.models import TrackedLink

    post.tracked_link = TrackedLink.objects.create(stylist=post.stylist, target_url=post.stylist.hotpepper_url, kind="sns_post")
    post.save(update_fields=["tracked_link", "updated_at"])
    return post.tracked_link


def tracked_link_url(post: ReelPost) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/r/{post.tracked_link.code}/" if post.tracked_link_id else ""


def link_clicks(post: ReelPost) -> int:
    return post.tracked_link.clicks.count() if post.tracked_link_id else 0


def type_overview(stylist, n: int = 10) -> dict:
    """直近n件の型の内訳（偏りが一目で分かるように）"""
    recent = list(ReelPost.objects.filter(stylist=stylist).exclude(post_type="").exclude(status="SKIPPED").order_by("-created_at").values_list("post_type", flat=True)[:n])
    total = len(recent)
    rows = []
    for key, label in TYPE_LABELS.items():
        c = recent.count(key)
        rows.append({"key": key, "label": label, "count": c, "share": round(100 * c / total) if total else 0, "icon": POST_TYPES[key]["icon"]})
    streak = 0
    for k in recent:
        if k == recent[0]:
            streak += 1
        else:
            break
    return {"rows": rows, "total": total, "recent": recent, "streak": streak, "streak_label": TYPE_LABELS.get(recent[0], "") if recent else ""}


# ---------------------------------------------------------------------------
# 日次・定期処理
# ---------------------------------------------------------------------------
def publish_due() -> int:
    n = 0
    for post in ReelPost.objects.filter(status="SCHEDULED", scheduled_at__lte=timezone.now()).select_related("stylist"):
        publish_post(post)
        n += 1
    return n


def refresh_metrics() -> int:
    since = timezone.now() - timedelta(days=30)
    stale = timezone.now() - timedelta(hours=6)
    posts = ReelPost.objects.filter(status="PUBLISHED", published_at__gte=since).exclude(video="").annotate(last=Max("metrics__fetched_at")).filter(Q(last__isnull=True) | Q(last__lt=stale))
    n = 0
    for post in posts[:20]:
        if (post.publish_result or {}).get("manual"):
            continue
        try:
            fetch_metrics(post)
            n += 1
        except Exception:  # noqa: BLE001
            log.exception("数値の取り込みに失敗: %s", post.id)
    return n


def housekeeping(daily: bool = False) -> dict:
    summary = {"published": publish_due(), "metrics": refresh_metrics()}
    if daily:
        refresh_instagram_tokens()
        refresh_threads_tokens()
        summary["tokens_refreshed"] = True
    return summary


def latest_metrics(post: ReelPost) -> list:
    latest = {}
    for m in post.metrics.all():
        latest.setdefault(m.platform, m)
    return list(latest.values())


__all__ = ["week_count"]
