"""空き枠の自動作成（稼働時間 − 予約）"""
from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.broadcasts.auto_slots import free_gaps, sync_auto_slots, working_window
from apps.broadcasts.models import AvailabilitySlot
from apps.core.dates import today_local
from apps.visits.models import Reservation


def _res(stylist, customer, day, hour, minute=0, **kw):
    return Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.make_aware(datetime.combine(day, time(hour, minute))), **kw)


def test_free_gaps_subtract_reservations_and_short_gaps(stylist, customer):
    stylist.work_start, stylist.work_end, stylist.avg_service_minutes = time(10, 0), time(20, 0), 90
    stylist.save()
    day = today_local() + timedelta(days=3)
    _res(stylist, customer, day, 11, menu="")  # 11:00〜12:30（メニュー未設定 → 平均90分）
    _res(stylist, customer, day, 15, menu="")  # 15:00〜16:30
    _res(stylist, customer, day, 18, status=Reservation.Status.CANCELLED)  # キャンセルは空き扱い
    assert free_gaps(stylist, day) == [(12 * 60 + 30, 15 * 60), (16 * 60 + 30, 20 * 60)]  # 10:00〜11:00 は60分で90分未満なので出さない


def test_free_gaps_respects_off_days_today_and_manual_slots(stylist, customer):
    stylist.work_days = [0, 1, 2, 3, 4]  # 土日休み
    stylist.work_start, stylist.work_end, stylist.avg_service_minutes = time(10, 0), time(18, 0), 60
    stylist.save()
    day = today_local() + timedelta(days=1)
    while day.weekday() < 5:
        day += timedelta(days=1)
    assert working_window(stylist, day) is None and free_gaps(stylist, day) == []
    weekday = day + timedelta(days=2)
    AvailabilitySlot.objects.create(stylist=stylist, date=weekday, start_time=time(13, 0), end_time=time(15, 0))  # 手で登録した枠
    assert free_gaps(stylist, weekday) == [(10 * 60, 13 * 60), (15 * 60, 18 * 60)]
    today = today_local()
    if today.weekday() < 5:
        now = timezone.make_aware(datetime.combine(today, time(13, 7)))
        gaps = free_gaps(stylist, today, now=now)
        assert gaps and gaps[0][0] == 13 * 60 + 15  # いまより前は出さない（15分単位に切り上げ）
    assert free_gaps(stylist, today - timedelta(days=1)) == []


def test_sync_creates_removes_and_keeps_closed(stylist, customer):
    stylist.work_start, stylist.work_end, stylist.avg_service_minutes = time(10, 0), time(16, 0), 60
    stylist.save()
    day = today_local() + timedelta(days=2)
    result = sync_auto_slots(stylist, days=4)
    assert result["created"] >= 1
    slot = AvailabilitySlot.objects.get(stylist=stylist, date=day, auto=True)
    assert (slot.start_time, slot.end_time) == (time(10, 0), time(16, 0)) and slot.status == "open"
    _res(stylist, customer, day, 12, menu="カット")  # シグナルで同期 → 10〜12 と 13〜16 に割れる
    slots = list(AvailabilitySlot.objects.filter(stylist=stylist, date=day, auto=True).order_by("start_time"))
    assert [(s.start_time, s.end_time) for s in slots] == [(time(10, 0), time(12, 0)), (time(13, 0), time(16, 0))]
    slots[0].status = AvailabilitySlot.Status.CLOSED  # 午前は受けない（取り下げ）
    slots[0].save()
    sync_auto_slots(stylist, days=4)
    kept = AvailabilitySlot.objects.filter(stylist=stylist, date=day, auto=True).order_by("start_time")
    assert [(s.start_time, s.status) for s in kept] == [(time(10, 0), "closed"), (time(13, 0), "open")]
    manual = AvailabilitySlot.objects.create(stylist=stylist, date=day + timedelta(days=1), start_time=time(11, 0), end_time=time(12, 0))
    sync_auto_slots(stylist, days=4)
    assert AvailabilitySlot.objects.filter(pk=manual.pk).exists()


def test_pages_sync_and_settings_save_hours(client_logged, stylist, customer):
    stylist.avg_service_minutes = 60
    stylist.save()
    assert client_logged.get(reverse("visits:schedule")).status_code == 200
    assert AvailabilitySlot.objects.filter(stylist=stylist, auto=True).exists()
    body = client_logged.get(reverse("broadcasts:availability")).content.decode()
    assert "自動" in body
    data = {
        "display_name": "佐藤 美咲", "salon_name": "salon", "salon_access": "", "hotpepper_url": "", "commission_rate": "", "nominated_commission_rate": "", "expense_rate": "", "avg_price": "", "weekly_slot_hours": "",
        "avg_service_minutes": "90", "default_cycle_weeks": "6", "follow_up_lead_days": "7", "max_broadcasts_per_month": "1", "broadcast_min_interval_days": "14",
        "work_days": ["1", "2", "3"], "work_start": "11:00", "work_end": "21:00",
    }
    assert client_logged.post(reverse("accounts:stylist_settings"), data).status_code == 302
    stylist.refresh_from_db()
    assert stylist.work_days == [1, 2, 3] and stylist.work_start == time(11, 0) and stylist.work_end == time(21, 0)
    assert not AvailabilitySlot.objects.filter(stylist=stylist, auto=True, date__week_day__in=[1, 2, 6, 7]).exists()  # 日・月・金・土には自動枠が無い
