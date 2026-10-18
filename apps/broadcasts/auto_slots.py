"""空き枠の自動作成：稼働時間 − 予約 ＝ 空き。

- 稼働時間（曜日・開始・終了）は基本情報に持つ。予約の長さは料金表の所要時間か平均施術時間（visits.schedule と同じ）
- 平均施術時間（最低60分）より短い空きは出さない
- 手で登録した枠（auto=False）はそのまま。自動の枠は毎回作り直す。自動の枠を「取り下げ」にしたものは、その時間に再び出さない
- 予約の追加・変更・キャンセル（シグナル）、基本情報の保存、予約・空き枠の画面を開いたときに同期する
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.dates import local_date_range_to_datetimes, now_local, today_local

from .models import AvailabilitySlot

SYNC_DAYS = 14
MIN_GAP_FLOOR = 60
ROUND_MIN = 15


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _time(minutes: int) -> time:
    minutes = min(max(minutes, 0), 24 * 60 - 1)
    return time(minutes // 60, minutes % 60)


def working_window(stylist, day: date) -> tuple[int, int] | None:
    """その日の稼働時間（分）。休みなら None"""
    days = stylist.work_days if stylist.work_days is not None else list(range(7))
    if day.weekday() not in [int(d) for d in days]:
        return None
    start, end = _minutes(stylist.work_start), _minutes(stylist.work_end)
    if end <= start:
        return None
    return start, end


def _busy_blocks(stylist, day: date) -> list[tuple[int, int]]:
    from apps.visits.models import Reservation
    from apps.visits.schedule import duration_minutes

    start_dt, end_dt = local_date_range_to_datetimes(day, day + timedelta(days=1))
    blocks = []
    for r in Reservation.objects.filter(stylist=stylist, reserved_for__gte=start_dt, reserved_for__lt=end_dt, status__in=[Reservation.Status.BOOKED, Reservation.Status.VISITED]):
        local = timezone.localtime(r.reserved_for)
        s = local.hour * 60 + local.minute
        blocks.append((s, s + duration_minutes(stylist, r.menu)))
    for s in AvailabilitySlot.objects.filter(stylist=stylist, date=day).exclude(auto=True, status=AvailabilitySlot.Status.OPEN):
        blocks.append((_minutes(s.start_time), _minutes(s.end_time) if _minutes(s.end_time) > _minutes(s.start_time) else 24 * 60))  # 手で登録した枠・取り下げた自動枠の時間には重ねない
    return sorted(blocks)


def free_gaps(stylist, day: date, now=None) -> list[tuple[int, int]]:
    """稼働時間から予約（と手動の枠）を引いた空き（分）。今日はいまより前を除く"""
    window = working_window(stylist, day)
    if window is None:
        return []
    start, end = window
    if day == today_local():
        now = now or now_local()
        cursor = now.hour * 60 + now.minute
        cursor = ((cursor + ROUND_MIN - 1) // ROUND_MIN) * ROUND_MIN
        start = max(start, cursor)
    if day < today_local() or start >= end:
        return []
    min_gap = max(stylist.avg_service_minutes or 0, MIN_GAP_FLOOR)
    gaps = []
    cursor = start
    for b_start, b_end in _busy_blocks(stylist, day):
        if b_end <= cursor:
            continue
        if b_start > cursor and b_start - cursor >= min_gap:
            gaps.append((cursor, min(b_start, end)))
        cursor = max(cursor, b_end)
        if cursor >= end:
            break
    if end - cursor >= min_gap:
        gaps.append((cursor, end))
    return [(s, e) for s, e in gaps if e - s >= min_gap and s < end]


@transaction.atomic
def sync_auto_slots(stylist, days: int = SYNC_DAYS, today: date | None = None) -> dict:
    """今日から days 日分の自動の空き枠を作り直す。手動の枠と、取り下げた自動の枠は触らない"""
    today = today or today_local()
    created = removed = 0
    for i in range(days):
        day = today + timedelta(days=i)
        desired = {(_time(s), _time(e)) for s, e in free_gaps(stylist, day)}
        existing = {(s.start_time, s.end_time): s for s in AvailabilitySlot.objects.filter(stylist=stylist, date=day, auto=True).exclude(status=AvailabilitySlot.Status.CLOSED)}
        for key, slot in existing.items():
            if key not in desired:
                slot.delete()
                removed += 1
        for key in desired - set(existing):
            AvailabilitySlot.objects.create(stylist=stylist, date=day, start_time=key[0], end_time=key[1], auto=True, note="稼働時間と予約から自動")
            created += 1
    # 過去の自動枠は消す
    removed += AvailabilitySlot.objects.filter(stylist=stylist, auto=True, date__lt=today).delete()[0]
    return {"created": created, "removed": removed}
