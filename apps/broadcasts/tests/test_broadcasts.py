from datetime import date, time, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.broadcasts.models import AvailabilitySlot, Broadcast, BroadcastRecipient, RichMenu, WaitlistEntry
from apps.broadcasts.richmenu import build_rich_menu_payload, parse_postback, render_rich_menu_image
from apps.broadcasts.services import BroadcastError, build_audience, estimate_broadcast, frequency_status, handle_postback, potential_monthly_income, send_broadcast, weekly_open_hours
from apps.customers.models import Customer, Tag
from apps.lineapp.client import LineApiError
from apps.lineapp.models import InboundMessage, Message, QuotaUsage
from apps.visits.models import Reservation, Visit


class FakeLine:
    def __init__(self):
        self.multicasts = []
        self.replies = []
        self.fail = False

    def multicast(self, ids, text):
        if self.fail:
            raise LineApiError(429, "quota")
        self.multicasts.append((list(ids), text))
        return {}

    def reply(self, token, text):
        self.replies.append((token, text))
        return {}

    def get_profile(self, user_id):
        return {"displayName": "x"}


@pytest.fixture
def fake_line():
    fake = FakeLine()
    with mock.patch("apps.broadcasts.services.client_for", return_value=fake), mock.patch("apps.broadcasts.services.refresh_quota_for_channel", return_value=None):
        yield fake


def _c(stylist, name, **kw):
    defaults = {"line_user_id": f"U{name}", "line_followed": True, "contact_ok": True}
    defaults.update(kw)
    return Customer.objects.create(stylist=stylist, name=name, **defaults)


def test_potential_monthly_income():
    assert potential_monthly_income(6, 8000, 50, 90) == 69_280
    assert potential_monthly_income(6, 8000, None, 90) == 138_560
    assert potential_monthly_income(0, 8000, 50, 90) == 0
    assert potential_monthly_income(6, None, 50, 90) == 0
    assert potential_monthly_income(Decimal("2.5"), 10000, Decimal("60"), 60) == 64_950


def test_weekly_open_hours_and_slot_hours(stylist):
    stylist.work_days = []  # 手で登録した枠だけを数えるテストなので、自動の空き枠は出さない
    stylist.save()
    today = date(2026, 10, 21)  # 水曜
    AvailabilitySlot.objects.create(stylist=stylist, date=date(2026, 10, 22), start_time=time(13, 0), end_time=time(16, 30))
    AvailabilitySlot.objects.create(stylist=stylist, date=date(2026, 10, 19), start_time=time(10, 0), end_time=time(12, 0))  # 同じ週の月曜
    AvailabilitySlot.objects.create(stylist=stylist, date=date(2026, 10, 27), start_time=time(10, 0), end_time=time(12, 0))  # 翌週
    AvailabilitySlot.objects.create(stylist=stylist, date=date(2026, 10, 23), start_time=time(10, 0), end_time=time(12, 0), status=AvailabilitySlot.Status.FILLED)
    assert weekly_open_hours(stylist, today) == Decimal("5.5")


def test_build_audience_exclusions(stylist, customer):
    a = _c(stylist, "A")
    _c(stylist, "B", contact_ok=False)
    _c(stylist, "C", line_user_id=None)
    _c(stylist, "D", line_blocked_at=timezone.now())
    e = _c(stylist, "E")
    Reservation.objects.create(stylist=stylist, customer=e, reserved_for=timezone.now() + timedelta(days=2))
    f = _c(stylist, "F")
    Message.objects.create(stylist=stylist, customer=f, kind=Message.Kind.BROADCAST, route=Message.Route.PUSH, body="x", sent_at=timezone.now() - timedelta(days=5))

    names = {c.name for c in build_audience(stylist, {}, Broadcast.Kind.ANNOUNCEMENT)}
    assert names == {customer.name, "A", "E"}  # 予約済みは告知では除外しない。直近配信者Fは除外
    names = {c.name for c in build_audience(stylist, {}, Broadcast.Kind.AVAILABILITY)}
    assert names == {customer.name, "A"}  # 空き枠案内は予約済みを除外
    names = {c.name for c in build_audience(stylist, {"exclude_recent_days": 0}, Broadcast.Kind.ANNOUNCEMENT)}
    assert "F" in names


def test_build_audience_segments(stylist, customer):
    a = _c(stylist, "A", preferred_timing="平日昼")
    b = _c(stylist, "B")
    tag = Tag.objects.create(stylist=stylist, name="カラー")
    a.tags.add(tag)
    Visit.objects.create(stylist=stylist, customer=a, visited_at=timezone.now() - timedelta(days=90), menu="カラー")
    Visit.objects.create(stylist=stylist, customer=b, visited_at=timezone.now() - timedelta(days=10), menu="カット")
    assert [c.name for c in build_audience(stylist, {"tags": ["カラー"]})] == ["A"]
    assert [c.name for c in build_audience(stylist, {"last_visit_min_days": 60})] == ["A"]
    assert {c.name for c in build_audience(stylist, {"last_visit_min_days": 60, "include_never_visited": True})} == {"A", customer.name}
    assert [c.name for c in build_audience(stylist, {"last_visit_max_days": 30})] == ["B"]
    assert [c.name for c in build_audience(stylist, {"preferred_timing": "平日"})] == ["A"]
    WaitlistEntry.objects.create(stylist=stylist, customer=b)
    assert [c.name for c in build_audience(stylist, {"waitlist_only": True})] == ["B"]
    assert [c.name for c in build_audience(stylist, {}, Broadcast.Kind.WAITLIST)] == ["B"]


def test_frequency_status_blocks_after_limit(stylist):
    assert frequency_status(stylist)["blocked"] is False
    Broadcast.objects.create(stylist=stylist, title="x", body="x", status=Broadcast.Status.SENT, sent_at=timezone.now() - timedelta(days=3))
    st = frequency_status(stylist)
    assert st["blocked"] is True and len(st["reasons"]) == 2


def test_estimate_warns_when_quota_exceeded(stylist, channel, customer):
    for i in range(3):
        _c(stylist, f"C{i}")
    QuotaUsage.objects.create(channel=channel, year_month=timezone.localdate().strftime("%Y-%m"), quota_type="limited", quota_limit=200, total_usage=198)
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    est = estimate_broadcast(b)
    assert est["target_count"] == 4 and est["planned"] == 4
    assert est["quota"]["would_exceed"] is True and est["can_send"] is False
    b.refresh_from_db()
    assert b.target_count == 4 and b.quota_used_snapshot == 198


def test_send_broadcast_success(stylist, channel, customer, fake_line):
    _c(stylist, "A")
    QuotaUsage.objects.create(channel=channel, year_month=timezone.localdate().strftime("%Y-%m"), quota_type="limited", quota_limit=200, total_usage=10)
    b = Broadcast.objects.create(stylist=stylist, title="空き", body="空きが出ました\n{予約リンク}", kind=Broadcast.Kind.AVAILABILITY)
    WaitlistEntry.objects.create(stylist=stylist, customer=customer)
    send_broadcast(b)
    b.refresh_from_db()
    assert b.status == Broadcast.Status.SENT and b.sent_count == 2 and b.failed_count == 0
    assert len(fake_line.multicasts) == 1 and set(fake_line.multicasts[0][0]) == {customer.line_user_id, "UA"}
    assert b.tracked_link is not None and b.tracked_link.url in fake_line.multicasts[0][1]
    assert Message.objects.filter(stylist=stylist, kind=Message.Kind.BROADCAST, route=Message.Route.PUSH).count() == 2
    assert BroadcastRecipient.objects.filter(broadcast=b, status=BroadcastRecipient.Status.SENT).count() == 2
    assert QuotaUsage.objects.get(channel=channel).total_usage == 12
    assert WaitlistEntry.objects.get(customer=customer).status == WaitlistEntry.Status.NOTIFIED


def test_send_broadcast_blocked_by_quota_and_frequency(stylist, channel, customer, fake_line):
    QuotaUsage.objects.create(channel=channel, year_month=timezone.localdate().strftime("%Y-%m"), quota_type="limited", quota_limit=200, total_usage=200)
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    with pytest.raises(BroadcastError, match="通数"):
        send_broadcast(b)
    QuotaUsage.objects.filter(channel=channel).update(total_usage=0)
    Broadcast.objects.create(stylist=stylist, title="prev", body="x", status=Broadcast.Status.SENT, sent_at=timezone.now() - timedelta(days=1))
    with pytest.raises(BroadcastError, match="頻度"):
        send_broadcast(b)
    send_broadcast(b, force_frequency=True)
    b.refresh_from_db()
    assert b.status == Broadcast.Status.SENT


def test_send_broadcast_records_failure(stylist, channel, customer, fake_line):
    fake_line.fail = True
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    send_broadcast(b)
    b.refresh_from_db()
    assert b.status == Broadcast.Status.FAILED and b.failed_count == 1 and b.sent_count == 0
    assert not Message.objects.filter(kind=Message.Kind.BROADCAST).exists()


def test_send_requires_verified_channel(stylist, customer):
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    with pytest.raises(BroadcastError):
        send_broadcast(b)


def test_handle_postback_registers_waitlist_and_auto_replies(stylist, channel, customer, fake_line):
    RichMenu.objects.create(stylist=stylist, auto_reply_enabled=True, waitlist_reply="登録しました")
    handle_postback(channel, customer, "action=waitlist", "rt-1", timezone.now())
    handle_postback(channel, customer, "action=waitlist", "rt-2", timezone.now())
    assert WaitlistEntry.objects.filter(customer=customer, status=WaitlistEntry.Status.ACTIVE).count() == 1
    assert len(fake_line.replies) == 2
    inbound = InboundMessage.objects.filter(customer=customer, message_type="postback")
    assert inbound.count() == 2 and all(m.replied_at for m in inbound)
    assert Message.objects.filter(customer=customer, route=Message.Route.REPLY).count() == 2


def test_handle_postback_without_auto_reply(stylist, channel, customer, fake_line):
    RichMenu.objects.create(stylist=stylist, auto_reply_enabled=False)
    handle_postback(channel, customer, "action=waitlist", "rt", timezone.now())
    assert not fake_line.replies
    assert InboundMessage.objects.get(customer=customer).replied_at is None


def test_rich_menu_payload_and_image(stylist):
    rm = RichMenu(stylist=stylist)
    payload = build_rich_menu_payload(rm, "https://app.example.test/r/abc/")
    assert payload["size"] == {"width": 2500, "height": 843}
    assert [a["action"]["type"] for a in payload["areas"]] == ["uri", "message", "postback"]
    assert payload["areas"][2]["action"]["data"] == "action=waitlist"
    assert build_rich_menu_payload(rm, None)["areas"][0]["action"]["type"] == "message"
    assert parse_postback("action=waitlist&x=1") == {"action": "waitlist", "x": "1"}
    png = render_rich_menu_image(rm.labels)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_broadcast_pages_render(client_logged, stylist, channel, customer):
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    sent = Broadcast.objects.create(stylist=stylist, title="s", body="b", status=Broadcast.Status.SENT, sent_at=timezone.now(), sent_count=1)
    urls = [
        reverse("broadcasts:list"),
        reverse("broadcasts:create"),
        reverse("broadcasts:create") + "?kind=waitlist",
        reverse("broadcasts:detail", kwargs={"pk": b.pk}),
        reverse("broadcasts:detail", kwargs={"pk": sent.pk}),
        reverse("broadcasts:edit", kwargs={"pk": b.pk}),
        reverse("broadcasts:availability"),
        reverse("broadcasts:waitlist"),
        reverse("broadcasts:richmenu"),
        reverse("broadcasts:richmenu_preview"),
    ]
    for url in urls:
        assert client_logged.get(url).status_code == 200, url


def test_broadcast_create_view_saves_segment(client_logged, stylist):
    resp = client_logged.post(
        reverse("broadcasts:create"),
        {"kind": "segment", "title": "久しぶりの方へ", "body": "本文", "last_visit_min_days": 60, "exclude_recent_days": 30, "exclude_reserved": "on", "action": "save"},
    )
    assert resp.status_code == 302
    b = Broadcast.objects.get(stylist=stylist)
    assert b.segment["last_visit_min_days"] == 60 and b.segment["exclude_reserved"] is True


def test_broadcast_send_view_requires_confirm(client_logged, stylist, channel, customer):
    b = Broadcast.objects.create(stylist=stylist, title="t", body="b")
    resp = client_logged.post(reverse("broadcasts:send", kwargs={"pk": b.pk}), {})
    assert resp.status_code == 302
    b.refresh_from_db()
    assert b.status == Broadcast.Status.DRAFT
