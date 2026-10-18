import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.drafts.models import Draft
from apps.lineapp.client import LineApiError
from apps.lineapp.models import InboundMessage, Message, QuotaUsage
from apps.lineapp.services import SendError, send_push, send_reply


class FakeLineClient:
    def __init__(self):
        self.replies = []
        self.pushes = []
        self.fail_push = False

    def get_profile(self, user_id):
        return {"displayName": "はなこ", "pictureUrl": "https://example.com/p.jpg"}

    def get_bot_info(self):
        return {"userId": "Ubot", "basicId": "@bot", "displayName": "Bot"}

    def reply(self, token, text):
        self.replies.append((token, text))
        return {}

    def push(self, user_id, text):
        if self.fail_push:
            raise LineApiError(429, "quota exceeded")
        self.pushes.append((user_id, text))
        return {}


def _signed(secret: str, payload: dict):
    body = json.dumps(payload).encode()
    return body, base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def _event(user_id, text, mid="100", etype="message"):
    ev = {"type": etype, "timestamp": 1700000000000, "source": {"type": "user", "userId": user_id}, "replyToken": "rt-1"}
    if etype == "message":
        ev["message"] = {"type": "text", "id": mid, "text": text}
    return ev


@pytest.fixture
def fake_line():
    fake = FakeLineClient()
    with mock.patch("apps.lineapp.services.client_for", return_value=fake):
        yield fake


def test_webhook_rejects_bad_signature(channel):
    body, _ = _signed("secret-abc", {"events": []})
    resp = Client().post(reverse("lineapp:webhook", kwargs={"key": channel.webhook_key}), data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE="bad")
    assert resp.status_code == 403


def test_webhook_unknown_key(db):
    resp = Client().post(reverse("lineapp:webhook", kwargs={"key": "nope"}), data=b"{}", content_type="application/json")
    assert resp.status_code == 403


def test_webhook_message_creates_customer_inbound_and_reply_draft(channel, fake_line):
    body, sig = _signed("secret-abc", {"destination": "Ubot", "events": [_event("Unew00000000000000000000000000001", "来週の土曜は空いていますか？")]})
    resp = Client().post(reverse("lineapp:webhook", kwargs={"key": channel.webhook_key}), data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE=sig)
    assert resp.status_code == 200
    customer = Customer.objects.get(stylist=channel.stylist, line_user_id="Unew00000000000000000000000000001")
    assert customer.needs_review is True
    assert customer.source == Customer.Source.LINE
    assert customer.name == "はなこ"
    inbound = InboundMessage.objects.get(customer=customer)
    assert inbound.text == "来週の土曜は空いていますか？"
    assert inbound.reply_token == "rt-1"
    assert inbound.suggestion_status == InboundMessage.SuggestionStatus.DONE
    draft = inbound.latest_reply_draft
    assert draft is not None and draft.kind == Draft.Kind.REPLY
    assert "{お名前}" not in draft.body and "{予約リンク}" not in draft.body


def test_webhook_ignores_duplicate_message_id(channel, fake_line):
    payload = {"events": [_event("Udup0000000000000000000000000001", "こんにちは", mid="dup-1")]}
    body, sig = _signed("secret-abc", payload)
    url = reverse("lineapp:webhook", kwargs={"key": channel.webhook_key})
    Client().post(url, data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE=sig)
    Client().post(url, data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE=sig)
    assert InboundMessage.objects.filter(line_message_id="dup-1").count() == 1


def test_webhook_follow_and_unfollow(channel, fake_line, customer):
    url = reverse("lineapp:webhook", kwargs={"key": channel.webhook_key})
    body, sig = _signed("secret-abc", {"events": [_event(customer.line_user_id, "", etype="unfollow")]})
    Client().post(url, data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE=sig)
    customer.refresh_from_db()
    assert customer.line_followed is False and customer.line_blocked_at is not None
    assert customer.can_contact is False
    body, sig = _signed("secret-abc", {"events": [_event(customer.line_user_id, "", etype="follow")]})
    Client().post(url, data=body, content_type="application/json", HTTP_X_LINE_SIGNATURE=sig)
    customer.refresh_from_db()
    assert customer.line_followed is True and customer.line_blocked_at is None


def test_reply_token_validity(stylist, customer, settings):
    settings.LINE_REPLY_TOKEN_TTL_SECONDS = 50
    now = timezone.now()
    fresh = InboundMessage(stylist=stylist, customer=customer, reply_token="rt", received_at=now - timedelta(seconds=10))
    assert fresh.reply_token_valid(now) is True
    assert 39 <= fresh.reply_token_seconds_left(now) <= 40
    stale = InboundMessage(stylist=stylist, customer=customer, reply_token="rt", received_at=now - timedelta(seconds=60))
    assert stale.reply_token_valid(now) is False
    assert stale.reply_token_seconds_left(now) == 0
    used = InboundMessage(stylist=stylist, customer=customer, reply_token="rt", reply_token_used=True, received_at=now)
    assert used.reply_token_valid(now) is False
    empty = InboundMessage(stylist=stylist, customer=customer, reply_token="", received_at=now)
    assert empty.reply_token_valid(now) is False


def test_send_reply_requires_valid_token(channel, customer, fake_line):
    inbound = InboundMessage.objects.create(stylist=channel.stylist, customer=customer, text="hi", reply_token="rt", received_at=timezone.now() - timedelta(minutes=5))
    with pytest.raises(SendError):
        send_reply(inbound, "返信です")
    assert not fake_line.replies


def test_send_reply_success_marks_token_used(channel, customer, fake_line):
    inbound = InboundMessage.objects.create(stylist=channel.stylist, customer=customer, text="hi", reply_token="rt", received_at=timezone.now())
    draft = Draft.objects.create(stylist=channel.stylist, customer=customer, inbound_message=inbound, kind=Draft.Kind.REPLY, body="案")
    msg = send_reply(inbound, "返信です", draft=draft)
    inbound.refresh_from_db()
    draft.refresh_from_db()
    assert fake_line.replies == [("rt", "返信です")]
    assert msg.route == Message.Route.REPLY and msg.consumed_quota is False
    assert inbound.reply_token_used and inbound.replied_at is not None
    assert draft.status == Draft.Status.SENT and draft.body == "返信です"


def test_send_reply_blocked_for_contact_ng(channel, customer, fake_line):
    customer.contact_ok = False
    customer.save()
    inbound = InboundMessage.objects.create(stylist=channel.stylist, customer=customer, text="hi", reply_token="rt", received_at=timezone.now())
    with pytest.raises(SendError):
        send_reply(inbound, "x")


def test_send_push_is_opt_in(channel, customer, fake_line):
    with pytest.raises(SendError, match="オフ"):
        send_push(channel.stylist, customer, "本文")
    assert not fake_line.pushes


def test_send_push_checks_quota_and_counts(channel, customer, fake_line):
    channel.push_enabled = True
    channel.save()
    QuotaUsage.objects.create(channel=channel, year_month=timezone.localdate().strftime("%Y-%m"), quota_type="limited", quota_limit=200, total_usage=200)
    with pytest.raises(SendError, match="超える"):
        send_push(channel.stylist, customer, "本文")

    QuotaUsage.objects.filter(channel=channel).update(total_usage=10)
    msg = send_push(channel.stylist, customer, "本文")
    assert msg.route == Message.Route.PUSH and msg.consumed_quota is True
    usage = QuotaUsage.objects.get(channel=channel)
    assert usage.total_usage == 11 and usage.local_push_count == 1
    assert fake_line.pushes == [(customer.line_user_id, "本文")]


def test_send_push_records_failure(channel, customer, fake_line):
    channel.push_enabled = True
    channel.save()
    fake_line.fail_push = True
    with pytest.raises(SendError):
        send_push(channel.stylist, customer, "本文")
    assert Message.objects.filter(customer=customer, status=Message.Status.FAILED, route=Message.Route.PUSH).exists()


def test_chat_url_template(channel, customer):
    assert channel.chat_url_for(customer) == f"https://chat.line.biz/{channel.bot_user_id}/chat/{customer.line_user_id}"
    customer.line_user_id = None
    assert channel.chat_url_for(customer) == f"https://chat.line.biz/{channel.bot_user_id}"
    channel.bot_user_id = ""
    assert channel.chat_url_for(customer) is None


def test_tracked_link_redirect_logs_click(stylist, customer):
    from apps.lineapp.models import TrackedLink

    link = TrackedLink.objects.create(stylist=stylist, customer=customer, target_url=stylist.hotpepper_url)
    resp = Client().get(reverse("lineapp:link_redirect", kwargs={"code": link.code}))
    assert resp.status_code == 302 and resp.url == stylist.hotpepper_url
    assert link.click_count == 1
