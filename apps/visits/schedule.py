"""予約のタイムライン（週の帯 ＋ 1日の時間軸）。

リストだと「いつ空いているか」「詰まっているか」が分かりにくいので、1日を時間軸で描く。
予約の長さは、メニュー名が料金表に合えばその所要時間、無ければ美容師の平均施術時間。
空き枠（broadcasts.AvailabilitySlot）も同じ軸に重ねる。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.core.dates import local_date_range_to_datetimes, now_local, today_local

DAY_START, DAY_END = 9, 23  # 既定の営業時間（予約がはみ出せば広げる）
HOUR_PX = 56  # 1時間の高さ（px）
MIN_BLOCK_MIN = 30  # 短い予約も指で押せる高さに
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def week_days(day: date) -> list[date]:
    start = day - timedelta(days=day.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def duration_minutes(stylist, menu_text: str) -> int:
    """メニュー名が料金表に合えばその所要時間（複数なら最長）、無ければ平均施術時間"""
    text = (menu_text or "").replace("＋", "+").replace("・", "+").replace("、", "+").replace(" ", "+")
    tokens = [t for t in text.split("+") if t.strip()]
    best, best_score = 0, (0, 0)
    if tokens:
        for m in stylist.menus.filter(is_active=True, minutes__isnull=False):
            hits = sum(1 for t in tokens if t in m.name or m.name in t)
            score = (hits, -len(m.name))  # 多くの語が合うメニューを優先。同点なら名前が短い（より近い）方
            if hits and score > best_score:
                best, best_score = m.minutes, score
    if best:
        return best
    # 料金表に合わなければ、種類（カット・カラー…）ごとの目安。複数なら一番長いもの＋30分ずつ
    from apps.accounts.menus import guess_category

    cats = []
    for t in tokens:
        c = guess_category(t)
        if c != "other" and c not in cats:
            cats.append(c)
    if cats:
        minutes = sorted((stylist.minutes_for_category(c) or 0 for c in cats), reverse=True)
        return minutes[0] + 30 * (len(minutes) - 1)
    return stylist.avg_service_minutes or 90


def _lanes(items: list[dict]) -> int:
    """重なる予定を横に並べる。各 item に lane を書き、レーン数を返す"""
    ends: list[int] = []
    for it in sorted(items, key=lambda x: (x["start_min"], -x["end_min"])):
        for i, end in enumerate(ends):
            if end <= it["start_min"]:
                ends[i] = it["end_min"]
                it["lane"] = i
                break
        else:
            ends.append(it["end_min"])
            it["lane"] = len(ends) - 1
    return max(len(ends), 1)


def build_day(stylist, day: date) -> dict:
    from apps.broadcasts.models import AvailabilitySlot
    from apps.visits.models import Reservation

    start_dt, end_dt = local_date_range_to_datetimes(day, day + timedelta(days=1))
    reservations = list(Reservation.objects.filter(stylist=stylist, reserved_for__gte=start_dt, reserved_for__lt=end_dt).select_related("customer", "attributed_message").order_by("reserved_for"))
    slots = list(AvailabilitySlot.objects.filter(stylist=stylist, date=day).exclude(status=AvailabilitySlot.Status.CLOSED))

    start_hour, end_hour = DAY_START, DAY_END
    items = []
    for r in reservations:
        local = timezone.localtime(r.reserved_for)
        start_min = local.hour * 60 + local.minute
        dur = duration_minutes(stylist, r.menu)
        items.append({"kind": "reservation", "obj": r, "start_min": start_min, "end_min": start_min + dur, "duration": dur, "time": local.strftime("%H:%M"), "name": r.customer.name if r.customer else (r.customer_name_raw or "お名前未設定"), "status": r.status, "menu": r.menu})
        start_hour = min(start_hour, local.hour)
        end_hour = max(end_hour, (start_min + dur + 59) // 60)
    slot_items = []
    for s in slots:
        a = s.start_time.hour * 60 + s.start_time.minute
        b = s.end_time.hour * 60 + s.end_time.minute
        if b <= a:
            b = 24 * 60
        slot_items.append({"kind": "slot", "obj": s, "start_min": a, "end_min": b, "status": s.status, "auto": s.auto, "label": f"{s.start_time:%H:%M}〜{s.end_time:%H:%M} {'空き' if s.status == AvailabilitySlot.Status.OPEN else '埋まった'}{'（自動）' if s.auto else ''}"})
        start_hour = min(start_hour, s.start_time.hour)
        end_hour = max(end_hour, (b + 59) // 60)
    end_hour = min(max(end_hour, start_hour + 1), 24)
    base = start_hour * 60
    lanes = _lanes(items)

    def px(minutes: int) -> int:
        return round(minutes / 60 * HOUR_PX)

    for it in items:
        shown = max(it["end_min"] - it["start_min"], MIN_BLOCK_MIN)
        it.update({"top": px(it["start_min"] - base), "height": px(shown), "lane": it.get("lane", 0), "width_f": round(1 / lanes, 4), "left_f": round(it.get("lane", 0) / lanes, 4)})
    for it in slot_items:
        it.update({"top": px(it["start_min"] - base), "height": px(it["end_min"] - it["start_min"])})

    now_top = None
    if day == today_local():
        now = now_local()
        minutes = now.hour * 60 + now.minute
        if base <= minutes <= end_hour * 60:
            now_top = px(minutes - base)

    hours = [{"hour": h, "top": px(h * 60 - base), "at": f"{day.isoformat()}T{h:02d}:00"} for h in range(start_hour, end_hour)]
    return {
        "day": day,
        "weekday": WEEKDAYS[day.weekday()],
        "hours": hours,
        "height": px((end_hour - start_hour) * 60),
        "items": items,
        "slots": slot_items,
        "now_top": now_top,
        "booked": sum(1 for r in reservations if r.status == Reservation.Status.BOOKED),
        "open_hours": sum((s.hours for s in slots if s.status == AvailabilitySlot.Status.OPEN), 0),
        "lanes": lanes,
    }


def build_week(stylist, day: date) -> list[dict]:
    from apps.broadcasts.models import AvailabilitySlot
    from apps.visits.models import Reservation

    days = week_days(day)
    start_dt, end_dt = local_date_range_to_datetimes(days[0], days[-1] + timedelta(days=1))
    counts: dict[date, int] = {}
    for r in Reservation.objects.filter(stylist=stylist, status=Reservation.Status.BOOKED, reserved_for__gte=start_dt, reserved_for__lt=end_dt):
        d = timezone.localtime(r.reserved_for).date()
        counts[d] = counts.get(d, 0) + 1
    open_days = set(AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN, date__gte=days[0], date__lte=days[-1]).values_list("date", flat=True))
    today = today_local()
    return [{"date": d, "weekday": WEEKDAYS[d.weekday()], "count": counts.get(d, 0), "has_open": d in open_days, "is_today": d == today, "is_selected": d == day} for d in days]


def parse_day(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return today_local()


def parse_at(value: str | None) -> datetime | None:
    """予約登録の初期値（?at=2026-10-20T14:00）"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
