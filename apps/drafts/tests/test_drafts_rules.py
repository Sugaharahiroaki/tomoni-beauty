from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.dates import compute_follow_up_date, today_local
from apps.drafts.models import Draft
from apps.drafts.services import can_send_to_customer, fill_placeholders, generate_visit_drafts, mark_draft_sent, prepare_follow_up_draft
from apps.karte.models import Karte
from apps.lineapp.models import Message
from apps.visits.models import FollowUp, Reservation


@pytest.fixture
def karte(stylist, customer):
    return Karte.objects.create(
        stylist=stylist,
        customer=customer,
        visited_on=today_local(),
        treatment_summary="落ち着いたブラウンにカラー",
        menu_items=["カラー"],
        concerns=["色落ちが早い"],
        results="赤みが出にくい配合に",
        next_visit_weeks=6,
        private_notes="離婚の話をしていた（非公開）",
    )


def test_fill_placeholders_replaces_name_and_link(customer):
    text = "{お名前}、ありがとうございました\nご予約はこちら\n{予約リンク}\nまたお待ちしています"
    out = fill_placeholders(text, customer, "https://app.example.test/r/abc/")
    assert out.startswith("山田さん、")
    assert "https://app.example.test/r/abc/" in out
    assert "{" not in out


def test_fill_placeholders_drops_link_line_when_no_link(customer):
    out = fill_placeholders("本文\nご予約はこちら {予約リンク}\n締め", customer, None)
    assert "予約リンク" not in out
    assert out == "本文\n締め"


def test_call_name_override(customer):
    customer.call_name = "はなこさん"
    assert fill_placeholders("{お名前}", customer, None) == "はなこさん"


def test_generate_visit_drafts_creates_two_drafts_and_follow_up(stylist, customer, karte):
    drafts = generate_visit_drafts(karte)
    kinds = {d.kind for d in drafts}
    assert kinds == {Draft.Kind.THANKS_CARE, Draft.Kind.NEXT_VISIT}
    for d in drafts:
        assert "{お名前}" not in d.body and "{予約リンク}" not in d.body
        assert d.tracked_link is not None  # hotpepper_url あり
        assert d.tracked_link.url in d.body
    nxt = next(d for d in drafts if d.kind == Draft.Kind.NEXT_VISIT)
    expected_due = compute_follow_up_date(karte.visited_on, 6, stylist.default_cycle_weeks, stylist.follow_up_lead_days)
    assert nxt.scheduled_for == expected_due
    fu = FollowUp.objects.get(karte=karte)
    assert fu.due_date == expected_due and fu.draft == nxt and fu.status == FollowUp.Status.DRAFT_READY


def test_generate_visit_drafts_is_idempotent_unless_replace(karte):
    first = generate_visit_drafts(karte)
    again = generate_visit_drafts(karte)
    assert {d.id for d in first} == {d.id for d in again}
    replaced = generate_visit_drafts(karte, replace_existing=True)
    assert {d.id for d in replaced}.isdisjoint({d.id for d in first})
    assert Draft.objects.filter(karte=karte, status=Draft.Status.DISCARDED).count() == 2


def test_no_hotpepper_url_means_no_link(stylist, customer, karte):
    stylist.hotpepper_url = ""
    stylist.save()
    drafts = generate_visit_drafts(karte)
    assert all(d.tracked_link is None for d in drafts)
    assert all("http" not in d.body for d in drafts)


def test_can_send_blocks_contact_ng(customer):
    customer.contact_ok = False
    ok, reason = can_send_to_customer(customer, Draft.Kind.THANKS_CARE)
    assert ok is False and "NG" in reason


def test_can_send_blocks_blocked_line(customer):
    customer.line_blocked_at = timezone.now()
    ok, _ = can_send_to_customer(customer, Draft.Kind.THANKS_CARE)
    assert ok is False


def test_can_send_blocks_recent_same_kind(stylist, customer, settings):
    settings.MIN_DAYS_BETWEEN_SAME_KIND_MESSAGES = 7
    Message.objects.create(stylist=stylist, customer=customer, kind=Message.Kind.NEXT_VISIT, route=Message.Route.COPY, body="x", sent_at=timezone.now() - timedelta(days=3))
    ok, reason = can_send_to_customer(customer, Draft.Kind.NEXT_VISIT)
    assert ok is False and "7日以内" in reason
    # 違う種類なら送れる
    assert can_send_to_customer(customer, Draft.Kind.THANKS_CARE)[0] is True
    # 8日前なら送れる
    Message.objects.update(sent_at=timezone.now() - timedelta(days=8))
    assert can_send_to_customer(customer, Draft.Kind.NEXT_VISIT)[0] is True


def test_can_send_next_visit_blocked_when_reservation_exists(stylist, customer):
    Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(days=3))
    ok, reason = can_send_to_customer(customer, Draft.Kind.NEXT_VISIT)
    assert ok is False and "予約" in reason
    # お礼は送れる
    assert can_send_to_customer(customer, Draft.Kind.THANKS_CARE)[0] is True


def test_cancelled_reservation_does_not_block(stylist, customer):
    Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(days=3), status=Reservation.Status.CANCELLED)
    assert can_send_to_customer(customer, Draft.Kind.NEXT_VISIT)[0] is True


def test_mark_draft_sent_records_message_and_completes_follow_up(karte):
    drafts = generate_visit_drafts(karte)
    nxt = next(d for d in drafts if d.kind == Draft.Kind.NEXT_VISIT)
    msg = mark_draft_sent(nxt, Message.Route.COPY, body="編集した本文")
    nxt.refresh_from_db()
    assert nxt.status == Draft.Status.SENT and nxt.body == "編集した本文"
    assert msg.kind == Message.Kind.NEXT_VISIT and msg.route == Message.Route.COPY and msg.body == "編集した本文"
    assert FollowUp.objects.get(karte=karte).status == FollowUp.Status.SENT


def test_prepare_follow_up_skips_when_reserved(stylist, customer, karte):
    generate_visit_drafts(karte)
    fu = FollowUp.objects.get(karte=karte)
    Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now() + timedelta(days=2))
    draft, reason = prepare_follow_up_draft(fu)
    fu.refresh_from_db()
    assert draft is None and "予約" in reason
    assert fu.status == FollowUp.Status.SKIPPED


def test_prepare_follow_up_returns_existing_draft(karte):
    generate_visit_drafts(karte)
    fu = FollowUp.objects.get(karte=karte)
    draft, reason = prepare_follow_up_draft(fu)
    assert draft == fu.draft and reason == ""


def test_prepare_follow_up_generates_when_draft_discarded(karte):
    generate_visit_drafts(karte)
    fu = FollowUp.objects.get(karte=karte)
    fu.draft.status = Draft.Status.DISCARDED
    fu.draft.save()
    draft, _ = prepare_follow_up_draft(fu)
    assert draft is not None and draft.pk != fu.draft_id or draft.is_sendable_status
    fu.refresh_from_db()
    assert fu.draft == draft and fu.status == FollowUp.Status.DRAFT_READY
