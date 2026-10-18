"""日付計算ロジック（テスト対象）。"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone


def today_local() -> date:
    return timezone.localdate()


def now_local() -> datetime:
    return timezone.localtime()


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end_exclusive(d: date) -> date:
    """翌月1日（半開区間の終端）。"""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last_day) + timedelta(days=1)


def year_month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def shift_months(d: date, months: int) -> date:
    """月初日を基準に months ヶ月ずらす。"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def recommended_visit_date(visited_on: date, next_visit_weeks: int | None, default_cycle_weeks: int | None = None) -> date:
    weeks = next_visit_weeks if next_visit_weeks and next_visit_weeks > 0 else (
        default_cycle_weeks or settings.DEFAULT_VISIT_CYCLE_WEEKS
    )
    return visited_on + timedelta(weeks=weeks)


def compute_follow_up_date(
    visited_on: date,
    next_visit_weeks: int | None,
    default_cycle_weeks: int | None = None,
    lead_days: int | None = None,
) -> date:
    """次回案内を送るべき日。

    推奨来店日の lead_days 日前。来店翌日より前には絶対にならない
    （施術直後にお礼とは別に次回案内が出るのを防ぐ）。
    """
    lead = settings.FOLLOW_UP_LEAD_DAYS_DEFAULT if lead_days is None else lead_days
    target = recommended_visit_date(visited_on, next_visit_weeks, default_cycle_weeks)
    due = target - timedelta(days=max(lead, 0))
    floor = visited_on + timedelta(days=1)
    return max(due, floor)


def local_date_range_to_datetimes(start: date, end_exclusive: date):
    """ローカル日付の半開区間を aware datetime の半開区間へ。"""
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start, datetime.min.time()), tz)
    end_dt = timezone.make_aware(datetime.combine(end_exclusive, datetime.min.time()), tz)
    return start_dt, end_dt


def days_between(a: date, b: date) -> int:
    return (b - a).days
