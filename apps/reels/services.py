"""SNS動画投稿の業務ロジック（開始・素材・台本の修正・動画作成の依頼・予約・日次処理）。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from apps.core.jobs import enqueue

from . import media
from .connect import available as connect_available
from .connect import refresh_instagram_tokens, refresh_threads_tokens
from .models import MediaAsset, NarrationTake, ReelPost, ReelProfile, RenderJob
from .publishing import best_time, fetch_metrics, publish_post
from .recipes import TEMPLATES, choose_template, shot_list, theme_for

log = logging.getLogger(__name__)
MIN_ASSETS = 2


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
        "voices": VOICES,
        "templates": [{"key": k, "label": t["label"], "goal": t["goal"], "seconds": t["seconds"], "cta": t["cta"]} for k, t in TEMPLATES.items()],
    }


def month_count(stylist) -> int:
    now = timezone.localtime()
    return ReelPost.objects.filter(stylist=stylist, created_at__year=now.year, created_at__month=now.month).count()


# ---------------------------------------------------------------------------
# 開始
# ---------------------------------------------------------------------------
@transaction.atomic
def start_post(stylist, template_key: str | None = None, karte=None, menu_items: list[str] | None = None, purpose: str | None = None, uses_story: bool = False, import_photos: bool = True) -> ReelPost:
    recent = list(ReelPost.objects.filter(stylist=stylist).order_by("-created_at").values_list("template_key", flat=True)[:6])
    menu_items = menu_items or (list(karte.menu_items or []) if karte else [])
    key = template_key if template_key in TEMPLATES else choose_template(menu_items, recent, purpose)
    profile = profile_of(stylist)
    customer = karte.customer if karte else None
    post = ReelPost.objects.create(
        stylist=stylist,
        karte=karte,
        customer=customer,
        template_key=key,
        menu_items=menu_items,
        theme_title=theme_for(key, menu_items),
        shot_list=shot_list(key),
        narration_mode=profile.narration_mode,
        ai_label=profile.ai_label,
        uses_story=bool(uses_story and customer and customer.story_ok),
        face_allowed=(customer.face_ok if customer else True),
    )
    if karte and import_photos:
        import_karte_photos(post, karte)
    return post


def import_karte_photos(post: ReelPost, karte) -> int:
    """カルテの写真のうち、掲載できるもの（写真OK・顔出しの条件を満たす）だけを素材として取り込む。"""
    count = 0
    slots = [s["key"] for s in post.shot_list]
    for i, photo in enumerate(karte.photos.all()):
        if not photo.usable_for_sns():
            continue
        try:
            with photo.image.open("rb") as f:
                content = ContentFile(f.read(), name=Path(photo.image.name).name)
        except (OSError, ValueError):
            continue
        slot = slots[min(i, len(slots) - 1)] if slots else ""
        try:
            save_asset(post, content, content.name, "image/jpeg", content.size, "photo", slot, face_visible=photo.face_visible, source="karte", karte_photo=photo)
            count += 1
        except media.MediaError:
            continue
    return count


# ---------------------------------------------------------------------------
# 素材
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
    asset.save()
    return asset


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


def request_render(post: ReelPost) -> RenderJob:
    if not post.script:
        raise ValueError("先に台本を作ってください。")
    job = RenderJob.objects.filter(post=post, status__in=["queued", "running"]).first()
    if job is None:
        job = RenderJob.objects.create(post=post)
        enqueue("apps.reels.tasks.run_render_job", job.id)
    post.status = "RENDERING"
    post.save(update_fields=["status", "updated_at"])
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
    posts = ReelPost.objects.filter(status="PUBLISHED", published_at__gte=since).annotate(last=Max("metrics__fetched_at")).filter(Q(last__isnull=True) | Q(last__lt=stale))
    n = 0
    for post in posts[:20]:
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
