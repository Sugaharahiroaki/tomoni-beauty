"""django-q2 から呼ばれるタスク（文字列パスで参照されるので名前を変えない）。"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.jobs import enqueue

from .models import ReelPost, RenderJob

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2
FRIENDLY_ERROR = "動画を作れませんでした。写真を差し替えるか、もう一度「動画を作る」を押してください。"


def generate_script(post_id: str) -> None:
    from .ai import generate_script as _generate

    post = ReelPost.objects.get(pk=post_id)
    try:
        _generate(post)
    except ValueError as exc:
        post.status = "DRAFT"
        post.notes = [str(exc)]
        post.save(update_fields=["status", "notes", "updated_at"])
    except Exception as exc:  # noqa: BLE001
        log.exception("script generation failed %s", post_id)
        post.status = "DRAFT"
        post.notes = [f"台本を作れませんでした。もう一度お試しください。（{exc}）"]
        post.save(update_fields=["status", "notes", "updated_at"])


def run_render_job(job_id: int) -> None:
    from .render_service import render_post

    with transaction.atomic():
        job = RenderJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status not in ("queued",):
            return
        job.status, job.started_at, job.attempts = "running", timezone.now(), job.attempts + 1
        job.save(update_fields=["status", "started_at", "attempts", "updated_at"])
    post = job.post
    ReelPost.objects.filter(pk=post.pk).update(status="RENDERING")
    try:
        job.log = render_post(post)
        job.status, job.error = "done", ""
    except Exception as exc:  # noqa: BLE001
        log.exception("render failed %s", post.id)
        job.error = str(exc)
        if job.attempts < MAX_ATTEMPTS:
            job.status = "queued"
            job.finished_at = timezone.now()
            job.save()
            enqueue("apps.reels.tasks.run_render_job", job.id)
            return
        job.status = "failed"
        ReelPost.objects.filter(pk=post.pk).update(status="FAILED", error=f"{FRIENDLY_ERROR}\n{exc}"[:2000])
    job.finished_at = timezone.now()
    job.save()


def publish_now(post_id: str) -> None:
    from .publishing import publish_post

    post = ReelPost.objects.filter(pk=post_id, status="SCHEDULED").first()
    if post:
        publish_post(post)


def housekeeping(daily: bool = False) -> dict:
    from .services import housekeeping as _housekeeping

    return _housekeeping(daily=daily)


def bump_render_attempts(job_id: int) -> None:  # pragma: no cover - 互換用
    RenderJob.objects.filter(pk=job_id).update(attempts=F("attempts") + 1)
