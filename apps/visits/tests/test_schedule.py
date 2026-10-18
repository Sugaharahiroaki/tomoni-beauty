"""予約のタイムライン（週の帯＋1日の時間軸）"""
from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import MenuItem
from apps.broadcasts.models import AvailabilitySlot
from apps.core.dates import today_local
from apps.visits.models import Reservation
from apps.visits.schedule import HOUR_PX, build_day, build_week, duration_minutes, parse_at, parse_day, week_days


def _res(stylist, customer, day: date, hour: int, minute: int = 0, **kw):
    return Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.make_aware(datetime.combine(day, time(hour, minute))), **kw)


def test_duration_uses_menu_minutes_then_average(stylist):
    stylist.avg_service_minutes = 75
    MenuItem.objects.create(stylist=stylist, name="カット+透明感カラー", price=6500, minutes=120)
    MenuItem.objects.create(stylist=stylist, name="ドライカット", price=2800, minutes=45)
    MenuItem.objects.create(stylist=stylist, name="カット+ブリーチカラー+バイカルテTR", price=13900, minutes=180)
    assert duration_minutes(stylist, "ドライカット") == 45
    assert duration_minutes(stylist, "カラー＋カット") == 120  # 多くの語が合うメニューを優先（「カット」だけで180分の方を取らない）
    assert duration_minutes(stylist, "カット+透明感カラー") == 120
    assert duration_minutes(stylist, "ブリーチカラー") == 180
    assert duration_minutes(stylist, "縮毛矯正") == 180  # 料金表に無い → 種類（縮毛矯正）の既定値
    assert duration_minutes(stylist, "") == 75


def test_build_day_positions_lanes_and_range(stylist, customer):
    day = today_local() + timedelta(days=1)
    a = _res(stylist, customer, day, 10, 0, menu="")  # メニュー未設定 → 平均施術時間
    b = _res(stylist, customer, day, 10, 30, menu="カラー")  # a と重なる → 横に並ぶ
    c = _res(stylist, customer, day, 7, 30, status=Reservation.Status.CANCELLED)  # 営業時間より前 → 軸を広げる
    AvailabilitySlot.objects.create(stylist=stylist, date=day, start_time=time(14, 0), end_time=time(17, 0))
    d = build_day(stylist, day)
    assert d["hours"][0]["hour"] == 7 and d["hours"][-1]["hour"] == 22
    items = {it["obj"].pk: it for it in d["items"]}
    assert items[a.pk]["top"] == round((10 * 60 - 7 * 60) / 60 * HOUR_PX)
    assert items[a.pk]["height"] == round(stylist.avg_service_minutes / 60 * HOUR_PX)
    assert {items[a.pk]["lane"], items[b.pk]["lane"]} == {0, 1} and items[a.pk]["width_f"] == 0.5
    assert items[c.pk]["status"] == "cancelled" and items[c.pk]["lane"] == 0
    assert d["lanes"] == 2 and d["booked"] == 2
    manual = next(s for s in d["slots"] if not s["auto"])
    assert manual["height"] == 3 * HOUR_PX and manual["status"] == "open" and "（自動）" not in manual["label"]
    autos = [s for s in d["slots"] if s["auto"]]  # 稼働時間（既定10〜20時）− 予約 − 手動の枠 ＝ 12〜14時・17〜20時
    assert [(s["start_min"] // 60, s["end_min"] // 60) for s in autos] == [(12, 14), (17, 20)] and all("（自動）" in s["label"] for s in autos)
    assert float(d["open_hours"]) == 3 + 1.5 + 3  # 手動3h ＋ 自動（12:30〜14:00、17:00〜20:00）
    assert d["now_top"] is None  # 今日ではない
    assert d["hours"][3]["at"] == f"{day.isoformat()}T10:00"


def test_build_week_counts_and_helpers(stylist, customer):
    today = today_local()
    _res(stylist, customer, today, 11)
    _res(stylist, customer, today, 15)
    AvailabilitySlot.objects.create(stylist=stylist, date=today + timedelta(days=1), start_time=time(10, 0), end_time=time(12, 0))
    week = build_week(stylist, today)
    assert len(week) == 7 and week[0]["date"].weekday() == 0
    me = next(w for w in week if w["is_today"])
    assert me["count"] == 2 and me["is_selected"]
    assert week_days(date(2026, 10, 18))[0] == date(2026, 10, 12)
    assert parse_day("nonsense") == today and parse_day("2026-10-20") == date(2026, 10, 20)
    assert parse_at("2026-10-20T14:00") == datetime(2026, 10, 20, 14, 0) and parse_at("bad") is None


def test_schedule_page_and_prefilled_create(client_logged, stylist, customer):
    day = today_local()
    _res(stylist, customer, day, 13, menu="カット")
    resp = client_logged.get(reverse("visits:schedule"))
    body = resp.content.decode()
    assert resp.status_code == 200 and "13:00 山田 花子" in body and 'class="tl-now"' in body
    assert client_logged.get(reverse("visits:schedule") + "?date=2026-10-20").status_code == 200
    resp = client_logged.get(reverse("visits:reservation_create") + "?at=2026-10-20T14:00")
    assert resp.status_code == 200 and "2026-10-20T14:00" in resp.content.decode()
    assert client_logged.get(reverse("visits:reservation_list")).status_code == 200
    assert client_logged.get(reverse("core:today")).status_code == 200


def test_duration_falls_back_to_category_minutes(stylist, client_logged):
    stylist.avg_service_minutes = 75
    stylist.save()
    assert duration_minutes(stylist, "縮毛矯正") == 180  # 料金表に無い → 種類の既定値
    assert duration_minutes(stylist, "カット＋カラー") == 120 + 30  # 一番長いもの＋30分
    assert duration_minutes(stylist, "よくわからないメニュー") == 75
    resp = client_logged.post(reverse("accounts:category_minutes"), {"cat_cut": "45", "cat_color": "150", "cat_perm": ""})
    assert resp.status_code == 302
    stylist.refresh_from_db()
    assert stylist.category_minutes == {"cut": 45, "color": 150}
    assert duration_minutes(stylist, "カット") == 45 and duration_minutes(stylist, "パーマ") == 120
    assert "種類ごとの所要時間" in client_logged.get(reverse("accounts:menu_list")).content.decode()

