"""Webhook処理・返信案・Reply/Push送信・通数取得。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai import services as ai_services
from apps.ai.claude_client import AIError
from apps.core.dates import year_month
from apps.core.jobs import enqueue
from apps.customers.models import Customer

from .client import LineApiError, LineClient
from .models import InboundMessage, LineChannel, Message, QuotaUsage, TrackedLink
from .quota import QuotaStatus

logger = logging.getLogger(__name__)


class SendError(Exception):
    pass


def client_for(channel: LineChannel) -> LineClient:
    return LineClient(channel.channel_access_token)


# ---------------------------------------------------------------------------
# チャネル確認・通数
# ---------------------------------------------------------------------------
def verify_channel(channel: LineChannel) -> bool:
    try:
        info = client_for(channel).get_bot_info()
    except LineApiError as exc:
        channel.is_verified = False
        channel.last_error = exc.message
        channel.save(update_fields=["is_verified", "last_error", "updated_at"])
        return False
    channel.bot_user_id = info.get("userId", channel.bot_user_id)
    channel.basic_id = info.get("basicId", channel.basic_id)
    channel.display_name = info.get("displayName", channel.display_name)
    channel.is_verified = True
    channel.last_verified_at = timezone.now()
    channel.last_error = ""
    channel.save()
    try:
        refresh_quota_for_channel(channel)
    except LineApiError as exc:
        logger.info("quota fetch failed after verify: %s", exc)
    return True


def refresh_quota_for_channel(channel: LineChannel) -> QuotaUsage:
    client = client_for(channel)
    quota = client.get_quota()
    consumption = client.get_quota_consumption()
    usage, _ = QuotaUsage.objects.get_or_create(channel=channel, year_month=year_month(timezone.localdate()))
    usage.quota_type = quota.get("type", "")
    usage.quota_limit = quota.get("value") if quota.get("type") == "limited" else None
    usage.total_usage = int(consumption.get("totalUsage", 0) or 0)
    usage.save()
    return usage


def quota_status_for(channel: LineChannel, planned: int = 0) -> QuotaStatus | None:
    usage = channel.current_quota()
    if usage is None:
        return None
    return usage.status(planned=planned)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
def _event_time(event: dict) -> datetime:
    ts = event.get("timestamp")
    if ts:
        return datetime.fromtimestamp(int(ts) / 1000, tz=dt_timezone.utc)
    return timezone.now()


def upsert_customer_from_line(channel: LineChannel, user_id: str) -> Customer:
    stylist = channel.stylist
    customer = Customer.objects.filter(stylist=stylist, line_user_id=user_id).first()
    if customer:
        return customer
    display_name, picture = "", ""
    try:
        profile = client_for(channel).get_profile(user_id)
        display_name = profile.get("displayName", "")
        picture = profile.get("pictureUrl", "")
    except LineApiError as exc:
        logger.info("profile fetch failed for %s: %s", user_id, exc)
    return Customer.objects.create(
        stylist=stylist,
        name=display_name or "LINEのお客様",
        line_user_id=user_id,
        line_display_name=display_name,
        line_picture_url=picture,
        line_followed=True,
        source=Customer.Source.LINE,
        needs_review=True,
    )


def handle_webhook_events(channel: LineChannel, events: list[dict]) -> int:
    handled = 0
    for event in events:
        try:
            if _handle_event(channel, event):
                handled += 1
        except Exception:  # noqa: BLE001 - 1イベントの失敗で他を止めない
            logger.exception("webhook event failed: %s", event.get("type"))
    return handled


def _handle_event(channel: LineChannel, event: dict) -> bool:
    etype = event.get("type")
    source = event.get("source") or {}
    user_id = source.get("userId")
    if not user_id or source.get("type") != "user":
        return False

    if etype == "follow":
        customer = upsert_customer_from_line(channel, user_id)
        customer.line_followed = True
        customer.line_blocked_at = None
        customer.save(update_fields=["line_followed", "line_blocked_at", "updated_at"])
        return True

    if etype == "unfollow":
        Customer.objects.filter(stylist=channel.stylist, line_user_id=user_id).update(line_followed=False, line_blocked_at=timezone.now())
        return True

    if etype == "message":
        message = event.get("message") or {}
        line_message_id = str(message.get("id", ""))
        if line_message_id and InboundMessage.objects.filter(stylist=channel.stylist, line_message_id=line_message_id).exists():
            return False  # 再送の重複
        customer = upsert_customer_from_line(channel, user_id)
        if not customer.line_followed:
            customer.line_followed = True
            customer.line_blocked_at = None
            customer.save(update_fields=["line_followed", "line_blocked_at", "updated_at"])
        mtype = message.get("type", "other")
        inbound = InboundMessage.objects.create(
            stylist=channel.stylist,
            customer=customer,
            line_message_id=line_message_id,
            message_type=mtype,
            text=message.get("text", "") if mtype == "text" else "",
            reply_token=event.get("replyToken", ""),
            received_at=_event_time(event),
            raw_event=event,
            suggestion_status=InboundMessage.SuggestionStatus.PENDING if mtype == "text" else InboundMessage.SuggestionStatus.NONE,
        )
        if mtype == "text" and inbound.text.strip():
            enqueue("apps.lineapp.tasks.suggest_reply", inbound.id)
        return True

    if etype == "postback":
        from apps.broadcasts.services import handle_postback

        customer = upsert_customer_from_line(channel, user_id)
        data = (event.get("postback") or {}).get("data", "")
        handle_postback(channel, customer, data, event.get("replyToken", ""), _event_time(event))
        return True

    return False


# ---------------------------------------------------------------------------
# 返信案
# ---------------------------------------------------------------------------
def suggest_reply_for_inbound(inbound_id: int):
    from apps.drafts.models import Draft
    from apps.drafts.services import fill_placeholders, style_for

    inbound = InboundMessage.objects.select_related("stylist", "customer").get(pk=inbound_id)
    stylist = inbound.stylist
    customer = inbound.customer
    history = []
    for m in Message.objects.filter(customer=customer).order_by("-sent_at")[:3]:
        history.append({"who": "美容師", "text": m.body[:200]})
    for m in InboundMessage.objects.filter(customer=customer).exclude(pk=inbound.pk).order_by("-received_at")[:3]:
        history.append({"who": "お客様", "text": m.display_text[:200]})
    try:
        result = ai_services.suggest_reply(inbound.text, style_for(stylist), stylist.has_hotpepper, customer.context_for_ai(), list(reversed(history)), stylist.menu_prompt_text())
    except AIError as exc:
        inbound.suggestion_status = InboundMessage.SuggestionStatus.FAILED
        inbound.note_for_stylist = str(exc)
        inbound.save(update_fields=["suggestion_status", "note_for_stylist", "updated_at"])
        return None

    link = None
    if stylist.has_hotpepper and "{予約リンク}" in result.get("reply_text", ""):
        link = TrackedLink.objects.create(stylist=stylist, customer=customer, target_url=stylist.hotpepper_url, kind="reply")
    body = fill_placeholders(result.get("reply_text", ""), customer, link.url if link else None)
    with transaction.atomic():
        Draft.objects.filter(inbound_message=inbound, status__in=[Draft.Status.DRAFT, Draft.Status.APPROVED]).update(status=Draft.Status.DISCARDED)
        draft = Draft.objects.create(
            stylist=stylist, customer=customer, inbound_message=inbound, kind=Draft.Kind.REPLY, body=body, generated_body=body, tracked_link=link
        )
        inbound.suggestion_status = InboundMessage.SuggestionStatus.DONE
        inbound.intent = result.get("intent", "")[:20]
        inbound.needs_attention = bool(result.get("needs_attention"))
        inbound.note_for_stylist = result.get("note_for_stylist", "")
        inbound.save(update_fields=["suggestion_status", "intent", "needs_attention", "note_for_stylist", "updated_at"])
    return draft


# ---------------------------------------------------------------------------
# 送信（Reply / Push）
# ---------------------------------------------------------------------------
def _record_message(stylist, customer, draft, kind, route, body, status, error="", response=None, tracked_link=None) -> Message:
    return Message.objects.create(
        stylist=stylist,
        customer=customer,
        draft=draft,
        kind=kind,
        route=route,
        body=body,
        status=status,
        sent_at=timezone.now(),
        error=error,
        line_response=response or {},
        tracked_link=tracked_link,
    )


def send_reply(inbound: InboundMessage, body: str, draft=None) -> Message:
    """Reply API（無料）。トークンの有効期限内のみ。

    失敗ログは必ず残したいので、API呼び出しはトランザクションの外で行い、成功時の更新だけを atomic にする。
    """
    from apps.drafts.models import Draft

    if not inbound.customer.can_contact:
        raise SendError(inbound.customer.contact_blocked_reason)
    if not inbound.reply_token_valid():
        raise SendError("返信トークンの有効期限（1分）が切れています。「コピーしてLINEで開く」で送ってください。")
    channel = inbound.stylist.line_channel
    try:
        response = client_for(channel).reply(inbound.reply_token, body)
    except LineApiError as exc:
        _record_message(inbound.stylist, inbound.customer, draft, Message.Kind.REPLY, Message.Route.REPLY, body, Message.Status.FAILED, error=exc.message)
        raise SendError(f"LINEへの送信に失敗しました: {exc.message}") from exc
    with transaction.atomic():
        inbound.reply_token_used = True
        inbound.replied_at = timezone.now()
        inbound.reply_route = Message.Route.REPLY
        inbound.save(update_fields=["reply_token_used", "replied_at", "reply_route", "updated_at"])
        message = _record_message(inbound.stylist, inbound.customer, draft, Message.Kind.REPLY, Message.Route.REPLY, body, Message.Status.SENT, response=response, tracked_link=getattr(draft, "tracked_link", None))
        if draft is not None:
            draft.body = body
            draft.status = Draft.Status.SENT
            draft.sent_at = message.sent_at
            draft.save(update_fields=["body", "status", "sent_at", "updated_at"])
    return message


def send_push(stylist, customer, body: str, draft=None, kind: str = Message.Kind.CUSTOM) -> Message:
    """Push API（通数を消費）。設定で有効にした美容師のみ。残数を事前確認する。"""
    from apps.drafts.models import Draft

    channel = getattr(stylist, "line_channel", None)
    if channel is None or not channel.is_verified:
        raise SendError("LINEチャネルが接続確認されていません")
    if not channel.push_enabled:
        raise SendError("Push送信は設定でオフになっています（通数を消費するため既定はオフ）")
    if not customer.can_contact:
        raise SendError(customer.contact_blocked_reason)
    if not customer.line_user_id:
        raise SendError("このお客様はLINEが紐付いていません")
    status = quota_status_for(channel, planned=1)
    if status is not None and status.would_exceed:
        raise SendError(f"今月の無料通数（{status.limit}通）を超えるため送信できません")
    try:
        response = client_for(channel).push(customer.line_user_id, body)
    except LineApiError as exc:
        _record_message(stylist, customer, draft, kind, Message.Route.PUSH, body, Message.Status.FAILED, error=exc.message)
        raise SendError(f"LINEへの送信に失敗しました: {exc.message}") from exc
    with transaction.atomic():
        message = _record_message(stylist, customer, draft, kind, Message.Route.PUSH, body, Message.Status.SENT, response=response, tracked_link=getattr(draft, "tracked_link", None))
        usage, _ = QuotaUsage.objects.get_or_create(channel=channel, year_month=year_month(timezone.localdate()))
        usage.local_push_count += 1
        usage.total_usage += 1  # API側の反映を待たずに手元で加算（次回取得で上書き）
        usage.save(update_fields=["local_push_count", "total_usage", "fetched_at"])
        if draft is not None:
            draft.body = body
            draft.status = Draft.Status.SENT
            draft.sent_at = message.sent_at
            draft.save(update_fields=["body", "status", "sent_at", "updated_at"])
            if draft.inbound_message_id:
                InboundMessage.objects.filter(pk=draft.inbound_message_id).update(replied_at=message.sent_at, reply_route=Message.Route.PUSH)
            from apps.visits.models import FollowUp

            FollowUp.objects.filter(draft=draft).update(status=FollowUp.Status.SENT, completed_at=message.sent_at)
    return message
