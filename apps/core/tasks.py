"""日次バッチ（n8n / cron / manage.py run_daily から呼ぶ）。"""
from __future__ import annotations

import logging

from apps.core.dates import today_local

logger = logging.getLogger(__name__)


def run_daily_tasks() -> dict:
    from apps.accounts.models import Stylist
    from apps.drafts.services import prepare_due_follow_ups
    from apps.lineapp.services import refresh_quota_for_channel

    today = today_local()
    summary = {"date": today.isoformat(), "stylists": 0, "follow_ups_prepared": 0, "follow_ups_skipped": 0, "quota_refreshed": 0, "errors": []}

    for stylist in Stylist.objects.filter(onboarding_completed=True):
        summary["stylists"] += 1
        try:
            prepared, skipped = prepare_due_follow_ups(stylist, today=today)
            summary["follow_ups_prepared"] += prepared
            summary["follow_ups_skipped"] += skipped
        except Exception as exc:  # noqa: BLE001 - 1人の失敗で全体を止めない
            logger.exception("prepare_due_follow_ups failed for stylist %s", stylist.id)
            summary["errors"].append(f"stylist {stylist.id}: {exc}")

        channel = getattr(stylist, "line_channel", None)
        if channel and channel.is_verified:
            try:
                refresh_quota_for_channel(channel)
                summary["quota_refreshed"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("quota refresh failed for channel %s: %s", channel.id, exc)
                summary["errors"].append(f"channel {channel.id}: {exc}")
    return summary
