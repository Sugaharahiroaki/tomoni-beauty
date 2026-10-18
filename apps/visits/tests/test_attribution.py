from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.dates import today_local
from apps.lineapp.models import Message
from apps.visits.models import FollowUp, Reservation, Visit
from apps.visits.services import attribute_reservation, find_attributable_message, has_upcoming_reservation, mark_visited, schedule_follow_up


def _msg(stylist, customer, days_ago, kind=Message.Kind.NEXT_VISIT):
    return Message.objects.create(stylist=stylist, customer=customer, kind=kind, route=Message.Route.COPY, body="案内", sent_at=timezone.now() - timedelta(days=days_ago))


def test_attribution_within_window(stylist, customer, settings):
    settings.ATTRIBUTION_WINDOW_DAYS = 14
    msg = _msg(stylist, customer, 5)
    r = Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(days=7))
    attribute_reservation(r)
    r.refresh_from_db()
    assert r.attributed_message == msg


def test_attribution_outside_window(stylist, customer, settings):
    settings.ATTRIBUTION_WINDOW_DAYS = 14
    _msg(stylist, customer, 20)
    r = Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(days=7))
    attribute_reservation(r)
    r.refresh_from_db()
    assert r.attributed_message is None


def test_attribution_boundary_is_inclusive(stylist, customer):
    now = timezone.now()
    msg = _msg(stylist, customer, 14)
    assert find_attributable_message(customer, now, window_days=14) == msg
    assert find_attributable_message(customer, now, window_days=13) is None


def test_attribution_picks_latest_and_ignores_replies(stylist, customer):
    old = _msg(stylist, customer, 10)
    newest = _msg(stylist, customer, 2)
    _msg(stylist, customer, 1, kind=Message.Kind.REPLY)
    assert find_attributable_message(customer, timezone.now(), 14) == newest
    assert old != newest


def test_attribution_ignores_failed_messages(stylist, customer):
    Message.objects.create(stylist=stylist, customer=customer, kind=Message.Kind.NEXT_VISIT, route=Message.Route.PUSH, body="x", status=Message.Status.FAILED, sent_at=timezone.now())
    assert find_attributable_message(customer, timezone.now(), 14) is None


def test_attribution_without_customer(stylist):
    assert find_attributable_message(None, timezone.now()) is None


def test_has_upcoming_reservation(stylist, customer):
    assert has_upcoming_reservation(customer) is False
    Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() - timedelta(days=1))
    assert has_upcoming_reservation(customer) is False  # 過去の予約は対象外
    r = Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(hours=1))
    assert has_upcoming_reservation(customer) is True
    r.status = Reservation.Status.CANCELLED
    r.save()
    assert has_upcoming_reservation(customer) is False


def test_mark_visited_creates_visit_and_skips_follow_ups(stylist, customer):
    fu = FollowUp.objects.create(stylist=stylist, customer=customer, due_date=today_local())
    r = Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now(), menu="カット")
    visit = mark_visited(r, price=6600)
    r.refresh_from_db()
    fu.refresh_from_db()
    assert r.status == Reservation.Status.VISITED
    assert visit.customer == customer and visit.menu == "カット" and visit.price == 6600
    assert Visit.objects.filter(reservation=r).count() == 1
    assert fu.status == FollowUp.Status.SKIPPED and fu.skip_reason == "来店済み"
    # 二重に呼んでも来店は1件
    mark_visited(r)
    assert Visit.objects.filter(reservation=r).count() == 1


def test_schedule_follow_up_supersedes_pending(stylist, customer):
    first = schedule_follow_up(stylist, customer, None, today_local() + timedelta(days=10))
    second = schedule_follow_up(stylist, customer, None, today_local() + timedelta(days=20))
    first.refresh_from_db()
    assert first.status == FollowUp.Status.SKIPPED
    assert second.status == FollowUp.Status.PENDING
    assert FollowUp.objects.filter(customer=customer, status=FollowUp.Status.PENDING).count() == 1


@pytest.mark.django_db
def test_reservation_create_view_attributes(client_logged, stylist, customer):
    from django.urls import reverse

    msg = _msg(stylist, customer, 3)
    resp = client_logged.post(
        reverse("visits:reservation_create"),
        {"customer": customer.pk, "customer_name_raw": "", "reserved_for": (timezone.localtime() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M"), "menu": "カラー", "note": ""},
    )
    assert resp.status_code == 302
    r = Reservation.objects.get(customer=customer)
    assert r.attributed_message == msg
