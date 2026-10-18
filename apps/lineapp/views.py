import hashlib
import json
import logging

from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue
from apps.drafts.models import Draft
from apps.drafts.services import mark_draft_sent

from .client import LineApiError, verify_signature
from .forms import LineChannelForm
from .models import InboundMessage, LineChannel, LinkClick, Message, TrackedLink
from .services import SendError, handle_webhook_events, refresh_quota_for_channel, send_push, send_reply, verify_channel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook（LINE → アプリ）
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def webhook(request, key: str):
    channel = LineChannel.objects.filter(webhook_key=key).select_related("stylist").first()
    if channel is None:
        return HttpResponseForbidden("unknown channel")
    if not verify_signature(channel.channel_secret, request.body, request.headers.get("X-Line-Signature")):
        logger.warning("invalid LINE signature for channel %s", channel.id)
        return HttpResponseForbidden("bad signature")
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid json")
    events = payload.get("events") or []
    if payload.get("destination") and not channel.bot_user_id:
        channel.bot_user_id = payload["destination"]
        channel.save(update_fields=["bot_user_id", "updated_at"])
    handle_webhook_events(channel, events)
    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# クリック計測付きリンク
# ---------------------------------------------------------------------------
def link_redirect(request, code: str):
    link = get_object_or_404(TrackedLink, code=code)
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
    LinkClick.objects.create(
        link=link,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        ip_hash=hashlib.sha256(ip.encode("utf-8")).hexdigest() if ip else "",
    )
    return redirect(link.target_url)


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
@stylist_required
def line_settings(request):
    channel = LineChannel.objects.filter(stylist=request.stylist).first()
    form = LineChannelForm(request.POST or None, instance=channel)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.stylist = request.stylist
        if channel and (form.cleaned_data["channel_access_token"] != channel.channel_access_token or form.cleaned_data["channel_secret"] != channel.channel_secret):
            obj.is_verified = False
        obj.save()
        messages.success(request, "保存しました。「接続を確認」を押して動作確認してください。")
        return redirect("lineapp:settings")
    quota = channel.quota_summary() if channel else None
    return render(request, "lineapp/settings.html", {"form": form, "channel": channel, "quota": quota})


@stylist_required
@require_POST
def line_verify(request):
    channel = get_object_or_404(LineChannel, stylist=request.stylist)
    if verify_channel(channel):
        messages.success(request, f"接続を確認しました：{channel.display_name}（{channel.basic_id}）")
    else:
        messages.error(request, f"接続できませんでした: {channel.last_error}")
    return redirect("lineapp:settings")


@stylist_required
@require_POST
def line_refresh_quota(request):
    channel = get_object_or_404(LineChannel, stylist=request.stylist)
    try:
        usage = refresh_quota_for_channel(channel)
        messages.success(request, f"今月の通数: {usage.total_usage} / {usage.quota_limit or '上限なし'}")
    except LineApiError as exc:
        messages.error(request, f"通数を取得できませんでした: {exc.message}")
    return redirect("lineapp:settings")


# ---------------------------------------------------------------------------
# 受信ボックス
# ---------------------------------------------------------------------------
@stylist_required
def inbox(request):
    qs = InboundMessage.objects.filter(stylist=request.stylist).select_related("customer")
    unreplied = qs.filter(replied_at__isnull=True, ignored=False)
    recent = qs.exclude(id__in=unreplied.values("id"))[:30]
    channel = getattr(request.stylist, "line_channel", None)
    return render(request, "lineapp/inbox.html", {"unreplied": unreplied, "recent": recent, "channel": channel})


@stylist_required
def inbound_detail(request, pk: int):
    inbound = get_object_or_404(InboundMessage.objects.select_related("customer", "stylist"), pk=pk, stylist=request.stylist)
    channel = getattr(request.stylist, "line_channel", None)
    draft = inbound.latest_reply_draft
    history = InboundMessage.objects.filter(customer=inbound.customer).exclude(pk=pk).order_by("-received_at")[:5]
    sent_history = Message.objects.filter(customer=inbound.customer).order_by("-sent_at")[:5]
    context = {
        "inbound": inbound,
        "customer": inbound.customer,
        "draft": draft,
        "channel": channel,
        "chat_url": channel.chat_url_for(inbound.customer) if channel else None,
        "token_valid": inbound.reply_token_valid(),
        "token_seconds_left": inbound.reply_token_seconds_left(),
        "push_quota": channel.quota_summary() if (channel and channel.push_enabled) else None,
        "history": history,
        "sent_history": sent_history,
    }
    return render(request, "lineapp/inbound_detail.html", context)


@stylist_required
def inbound_status(request, pk: int):
    inbound = get_object_or_404(InboundMessage, pk=pk, stylist=request.stylist)
    draft = inbound.latest_reply_draft
    return JsonResponse({"suggestion_status": inbound.suggestion_status, "has_draft": draft is not None, "token_seconds_left": inbound.reply_token_seconds_left()})


@stylist_required
@require_POST
def inbound_regenerate(request, pk: int):
    inbound = get_object_or_404(InboundMessage, pk=pk, stylist=request.stylist)
    inbound.suggestion_status = InboundMessage.SuggestionStatus.PENDING
    inbound.save(update_fields=["suggestion_status", "updated_at"])
    enqueue("apps.lineapp.tasks.suggest_reply", inbound.id)
    return redirect("lineapp:inbound_detail", pk=pk)


@stylist_required
@require_POST
def inbound_ignore(request, pk: int):
    inbound = get_object_or_404(InboundMessage, pk=pk, stylist=request.stylist)
    inbound.ignored = True
    inbound.save(update_fields=["ignored", "updated_at"])
    messages.info(request, "対応不要にしました")
    return redirect("lineapp:inbox")


@stylist_required
@require_POST
def inbound_send(request, pk: int):
    """返信の送信。route = reply（無料・1分以内） / copy（無料・手動） / push（通数消費・任意設定）"""
    inbound = get_object_or_404(InboundMessage.objects.select_related("customer", "stylist"), pk=pk, stylist=request.stylist)
    route = request.POST.get("route", "copy")
    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "本文が空です")
        return redirect("lineapp:inbound_detail", pk=pk)
    draft = inbound.latest_reply_draft
    if draft is None or not draft.is_sendable_status:
        draft = Draft.objects.create(stylist=request.stylist, customer=inbound.customer, inbound_message=inbound, kind=Draft.Kind.REPLY, body=body)

    if not inbound.customer.can_contact:
        messages.error(request, f"送信できません: {inbound.customer.contact_blocked_reason}")
        return redirect("lineapp:inbound_detail", pk=pk)

    try:
        if route == Message.Route.REPLY:
            send_reply(inbound, body, draft=draft)
            messages.success(request, "Reply APIで返信しました（通数は消費しません）")
        elif route == Message.Route.PUSH:
            send_push(request.stylist, inbound.customer, body, draft=draft, kind=Message.Kind.REPLY)
            messages.success(request, "Pushで送信しました（1通消費）")
        else:
            mark_draft_sent(draft, Message.Route.COPY, body=body)
            messages.success(request, "返信済みとして記録しました")
    except SendError as exc:
        messages.error(request, str(exc))
        return redirect("lineapp:inbound_detail", pk=pk)
    return redirect("lineapp:inbox")


@stylist_required
@require_POST
def draft_push(request, pk: int):
    """下書き（お礼・次回案内）を Push API で送る（任意機能）。"""
    draft = get_object_or_404(Draft.objects.select_related("customer"), pk=pk, stylist=request.stylist)
    body = (request.POST.get("body") or draft.body).strip()
    try:
        send_push(request.stylist, draft.customer, body, draft=draft, kind=draft.kind)
        messages.success(request, "Pushで送信しました（1通消費）")
    except SendError as exc:
        messages.error(request, str(exc))
        return redirect("drafts:detail", pk=pk)
    return redirect("core:today")
