"""一斉・セグメント配信、空き枠、キャンセル待ちの業務ロジック。"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.ai import services as ai_services
from apps.core.dates import today_local
from apps.customers.models import Customer
from apps.lineapp.client import LineApiError
from apps.lineapp.models import InboundMessage, Message, QuotaUsage, TrackedLink
from apps.lineapp.quota import QuotaStatus, planned_messages
from apps.lineapp.services import client_for, quota_status_for, refresh_quota_for_channel
from apps.visits.services import has_upcoming_reservation

from .models import AvailabilitySlot, Broadcast, BroadcastRecipient, WaitlistEntry
from .richmenu import parse_postback

logger = logging.getLogger(__name__)


class BroadcastError(Exception):
    pass


# ---------------------------------------------------------------------------
# 対象者の抽出
# ---------------------------------------------------------------------------
def last_visit_date(customer) -> date | None:
    visit = customer.visits.aggregate(m=Max("visited_at"))["m"]
    karte = customer.kartes.aggregate(m=Max("visited_on"))["m"]
    candidates = []
    if visit:
        candidates.append(timezone.localtime(visit).date())
    if karte:
        candidates.append(karte)
    return max(candidates) if candidates else None


def build_audience(stylist, segment: dict | None, kind: str = Broadcast.Kind.ANNOUNCEMENT, today: date | None = None) -> list[Customer]:
    """配信対象を抽出する。連絡NG・ブロック・LINE未連携は常に除外。"""
    segment = segment or {}
    today = today or today_local()
    qs = Customer.objects.filter(stylist=stylist, contact_ok=True, line_blocked_at__isnull=True, line_user_id__isnull=False).exclude(line_user_id="")

    tags = [t for t in segment.get("tags", []) if t]
    if tags:
        qs = qs.filter(tags__name__in=tags).distinct()
    timing = (segment.get("preferred_timing") or "").strip()
    if timing:
        qs = qs.filter(preferred_timing__icontains=timing)
    if segment.get("waitlist_only") or kind == Broadcast.Kind.WAITLIST:
        qs = qs.filter(waitlist_entries__status=WaitlistEntry.Status.ACTIVE).distinct()

    exclude_recent_days = segment.get("exclude_recent_days")
    if exclude_recent_days is None:
        exclude_recent_days = settings.BROADCAST_EXCLUDE_RECENT_DAYS_DEFAULT
    if exclude_recent_days and int(exclude_recent_days) > 0:
        since = timezone.now() - timedelta(days=int(exclude_recent_days))
        recent_ids = Message.objects.filter(stylist=stylist, kind=Message.Kind.BROADCAST, status=Message.Status.SENT, sent_at__gte=since).values_list("customer_id", flat=True)
        qs = qs.exclude(id__in=list(recent_ids))

    customers = list(qs.order_by("name"))

    min_days = segment.get("last_visit_min_days")
    max_days = segment.get("last_visit_max_days")
    menu_keyword = (segment.get("menu_keyword") or "").strip()
    include_never = bool(segment.get("include_never_visited"))
    exclude_reserved = segment.get("exclude_reserved")
    if exclude_reserved is None:
        exclude_reserved = kind in (Broadcast.Kind.AVAILABILITY, Broadcast.Kind.WAITLIST, Broadcast.Kind.SEGMENT)

    result = []
    for c in customers:
        if min_days or max_days:
            lv = last_visit_date(c)
            if lv is None:
                if not include_never:
                    continue
            else:
                days = (today - lv).days
                if min_days and days < int(min_days):
                    continue
                if max_days and days > int(max_days):
                    continue
        if menu_keyword:
            menus = " ".join(" ".join(k.menu_items or []) + " " + (k.treatment_summary or "") for k in c.kartes.all())
            if menu_keyword not in menus:
                continue
        if exclude_reserved and has_upcoming_reservation(c, today):
            continue
        result.append(c)
    return result


def segment_summary(segment: dict | None) -> list[str]:
    segment = segment or {}
    out = []
    if segment.get("tags"):
        out.append("タグ: " + "、".join(segment["tags"]))
    if segment.get("last_visit_min_days"):
        out.append(f"最終来店から{segment['last_visit_min_days']}日以上")
    if segment.get("last_visit_max_days"):
        out.append(f"最終来店から{segment['last_visit_max_days']}日以内")
    if segment.get("include_never_visited"):
        out.append("来店記録なしも含む")
    if segment.get("preferred_timing"):
        out.append(f"希望時期に「{segment['preferred_timing']}」")
    if segment.get("menu_keyword"):
        out.append(f"メニューに「{segment['menu_keyword']}」")
    if segment.get("waitlist_only"):
        out.append("キャンセル待ち登録者のみ")
    days = segment.get("exclude_recent_days")
    if days:
        out.append(f"直近{days}日に配信した人を除く")
    if segment.get("exclude_reserved"):
        out.append("予約済みの人を除く")
    return out


# ---------------------------------------------------------------------------
# 頻度・通数の事前確認
# ---------------------------------------------------------------------------
def frequency_status(stylist, today: date | None = None) -> dict:
    today = today or today_local()
    month_start = today.replace(day=1)
    sent_qs = Broadcast.objects.filter(stylist=stylist, status=Broadcast.Status.SENT)
    sent_this_month = sent_qs.filter(sent_at__date__gte=month_start).count()
    last = sent_qs.order_by("-sent_at").first()
    blocked = False
    reasons = []
    if sent_this_month >= stylist.max_broadcasts_per_month:
        blocked = True
        reasons.append(f"今月の配信回数が上限（{stylist.max_broadcasts_per_month}回）に達しています")
    if last and last.sent_at:
        days = (today - timezone.localtime(last.sent_at).date()).days
        if days < stylist.broadcast_min_interval_days:
            blocked = True
            reasons.append(f"前回の配信（{days}日前）から{stylist.broadcast_min_interval_days}日経っていません")
    return {"blocked": blocked, "reasons": reasons, "sent_this_month": sent_this_month, "last_sent_at": last.sent_at if last else None}


def estimate_broadcast(broadcast: Broadcast, refresh_quota: bool = False) -> dict:
    stylist = broadcast.stylist
    channel = getattr(stylist, "line_channel", None)
    audience = build_audience(stylist, broadcast.segment, broadcast.kind)
    planned = planned_messages(len(audience), 1)

    quota = None
    quota_error = ""
    if channel and channel.is_verified:
        if refresh_quota:
            try:
                refresh_quota_for_channel(channel)
            except LineApiError as exc:
                quota_error = exc.message
        quota = quota_status_for(channel, planned=planned)
    if quota is None:
        # 通数が取得できないときは無料プランの上限を仮定して警告だけ出す
        used = QuotaUsage.objects.filter(channel=channel).order_by("-year_month").first().total_usage if (channel and QuotaUsage.objects.filter(channel=channel).exists()) else 0
        quota = QuotaStatus(limit=settings.LINE_FREE_PLAN_MONTHLY_LIMIT, used=used, planned=planned)
        quota_error = quota_error or "通数を取得できていないため、無料プラン（200通）として計算しています"

    freq = frequency_status(stylist)
    warnings = []
    if quota.would_exceed:
        warnings.append(f"今月の残り通数を超えます（残り {quota.remaining} 通、必要 {planned} 通）")
    elif quota.warn(settings.LINE_QUOTA_WARN_RATIO):
        warnings.append("この配信で今月の通数の8割以上を使います")
    if not audience:
        warnings.append("対象のお客様がいません")
    if not (channel and channel.is_verified):
        warnings.append("LINEチャネルが未接続のため送信できません")

    broadcast.target_count = len(audience)
    broadcast.planned_messages = planned
    broadcast.quota_limit_snapshot = quota.limit
    broadcast.quota_used_snapshot = quota.used
    broadcast.save(update_fields=["target_count", "planned_messages", "quota_limit_snapshot", "quota_used_snapshot", "updated_at"])

    return {
        "audience": audience,
        "target_count": len(audience),
        "planned": planned,
        "quota": quota.to_dict(settings.LINE_QUOTA_WARN_RATIO),
        "quota_error": quota_error,
        "frequency": freq,
        "warnings": warnings,
        "can_send": bool(audience) and not quota.would_exceed and bool(channel and channel.is_verified),
    }


# ---------------------------------------------------------------------------
# 本文
# ---------------------------------------------------------------------------
def slots_text(slots) -> str:
    return "\n".join(f"・{s.label}" for s in slots)


def ensure_tracked_link(broadcast: Broadcast):
    stylist = broadcast.stylist
    if not stylist.hotpepper_url:
        return None
    if broadcast.tracked_link is None:
        broadcast.tracked_link = TrackedLink.objects.create(stylist=stylist, target_url=stylist.hotpepper_url, kind=f"broadcast_{broadcast.kind}")
        broadcast.save(update_fields=["tracked_link", "updated_at"])
    return broadcast.tracked_link


def render_body(broadcast: Broadcast) -> str:
    """{予約リンク} を計測リンクに置換。リンクが無ければその行を落とす。"""
    body = broadcast.body or ""
    link = ensure_tracked_link(broadcast)
    if link:
        return body.replace("{予約リンク}", link.url).strip()
    return "\n".join(ln for ln in body.splitlines() if "{予約リンク}" not in ln).strip()


def generate_body(broadcast: Broadcast, notes: str) -> dict:
    from apps.drafts.services import style_for

    result = ai_services.draft_broadcast(
        broadcast.kind,
        notes,
        style_for(broadcast.stylist),
        broadcast.stylist.has_hotpepper,
        slots_text(broadcast.slots.all()),
        " / ".join(segment_summary(broadcast.segment)),
    )
    broadcast.body = result.get("body", "").strip()
    broadcast.ai_alternatives = [a for a in result.get("free_alternatives", []) if isinstance(a, str)][:5]
    broadcast.save(update_fields=["body", "ai_alternatives", "updated_at"])
    return result


# ---------------------------------------------------------------------------
# 送信
# ---------------------------------------------------------------------------
def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def send_broadcast(broadcast: Broadcast, force_frequency: bool = False) -> Broadcast:
    if broadcast.status != Broadcast.Status.DRAFT:
        raise BroadcastError("この配信はすでに処理済みです")
    stylist = broadcast.stylist
    channel = getattr(stylist, "line_channel", None)
    if channel is None or not channel.is_verified:
        raise BroadcastError("LINEチャネルが接続確認されていません")
    if not broadcast.body.strip():
        raise BroadcastError("本文が空です")

    est = estimate_broadcast(broadcast, refresh_quota=True)
    if not est["audience"]:
        raise BroadcastError("対象のお客様がいません")
    if est["quota"]["would_exceed"]:
        raise BroadcastError(f"今月の通数上限を超えるため送信できません（残り {est['quota']['remaining']} 通、必要 {est['planned']} 通）")
    if est["frequency"]["blocked"] and not force_frequency:
        raise BroadcastError("配信頻度の上限です: " + " / ".join(est["frequency"]["reasons"]))

    body = render_body(broadcast)
    audience = est["audience"]
    with transaction.atomic():
        broadcast.status = Broadcast.Status.SENDING
        broadcast.save(update_fields=["status", "updated_at"])
        BroadcastRecipient.objects.filter(broadcast=broadcast).delete()
        BroadcastRecipient.objects.bulk_create([BroadcastRecipient(broadcast=broadcast, customer=c, line_user_id=c.line_user_id) for c in audience])

    client = client_for(channel)
    now = timezone.now()
    sent = failed = 0
    errors = []
    for chunk in _chunks(audience, settings.LINE_MULTICAST_CHUNK):
        ids = [c.line_user_id for c in chunk]
        try:
            client.multicast(ids, body)
        except LineApiError as exc:
            failed += len(chunk)
            errors.append(exc.message)
            BroadcastRecipient.objects.filter(broadcast=broadcast, customer__in=chunk).update(status=BroadcastRecipient.Status.FAILED, error=exc.message[:200])
            continue
        sent += len(chunk)
        BroadcastRecipient.objects.filter(broadcast=broadcast, customer__in=chunk).update(status=BroadcastRecipient.Status.SENT, sent_at=now)
        Message.objects.bulk_create(
            [
                Message(stylist=stylist, customer=c, kind=Message.Kind.BROADCAST, route=Message.Route.PUSH, body=body, status=Message.Status.SENT, sent_at=now, tracked_link=broadcast.tracked_link)
                for c in chunk
            ]
        )

    with transaction.atomic():
        if sent:
            from apps.core.dates import year_month

            usage, _ = QuotaUsage.objects.get_or_create(channel=channel, year_month=year_month(timezone.localdate()))
            usage.local_push_count += sent
            usage.total_usage += sent
            usage.save(update_fields=["local_push_count", "total_usage", "fetched_at"])
            if broadcast.kind in (Broadcast.Kind.WAITLIST, Broadcast.Kind.AVAILABILITY):
                WaitlistEntry.objects.filter(stylist=stylist, customer__in=audience, status=WaitlistEntry.Status.ACTIVE).update(status=WaitlistEntry.Status.NOTIFIED, notified_at=now)
        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.sent_at = now
        broadcast.error = " / ".join(errors)[:1000]
        broadcast.status = Broadcast.Status.SENT if sent else Broadcast.Status.FAILED
        broadcast.save()
    return broadcast


# ---------------------------------------------------------------------------
# リッチメニューの postback（キャンセル待ち登録）
# ---------------------------------------------------------------------------
def handle_postback(channel, customer, data: str, reply_token: str, event_time: datetime) -> None:
    params = parse_postback(data)
    action = params.get("action", "")
    stylist = channel.stylist
    if action == "waitlist":
        entry, created = WaitlistEntry.objects.get_or_create(
            stylist=stylist, customer=customer, status=WaitlistEntry.Status.ACTIVE, defaults={"source": WaitlistEntry.Source.RICHMENU}
        )
        inbound = InboundMessage.objects.create(
            stylist=stylist,
            customer=customer,
            message_type="postback",
            text="【リッチメニュー】キャンセル待ちに登録",
            reply_token=reply_token or "",
            received_at=event_time,
            suggestion_status=InboundMessage.SuggestionStatus.NONE,
            raw_event={"postback": data},
        )
        rich_menu = getattr(stylist, "rich_menu", None)
        if rich_menu and rich_menu.auto_reply_enabled and reply_token and rich_menu.waitlist_reply.strip():
            try:
                client_for(channel).reply(reply_token, rich_menu.waitlist_reply)
                inbound.replied_at = timezone.now()
                inbound.reply_route = Message.Route.REPLY
                inbound.reply_token_used = True
                inbound.save(update_fields=["replied_at", "reply_route", "reply_token_used", "updated_at"])
                Message.objects.create(stylist=stylist, customer=customer, kind=Message.Kind.CUSTOM, route=Message.Route.REPLY, body=rich_menu.waitlist_reply, status=Message.Status.SENT, sent_at=timezone.now())
            except LineApiError as exc:
                logger.warning("waitlist auto reply failed: %s", exc)
        else:
            inbound.ignored = False
            inbound.save(update_fields=["ignored"])
        return
    logger.info("unknown postback from %s: %s", customer.id, data)


# ---------------------------------------------------------------------------
# 空き枠
# ---------------------------------------------------------------------------
def potential_monthly_income(open_hours_per_week: Decimal | float | int, avg_price: int | None, commission_rate_pct: Decimal | float | None, avg_service_minutes: int) -> int:
    """週の空き時間が埋まった場合の月の取り分（概算）。

    来店数/週 = 空き時間 × 60 / 平均施術時間、月 = 4.33週、取り分 = 客単価 × 歩合率。
    """
    if not avg_price or not avg_service_minutes or avg_service_minutes <= 0:
        return 0
    hours = Decimal(str(open_hours_per_week))
    if hours <= 0:
        return 0
    customers_per_week = hours * Decimal(60) / Decimal(avg_service_minutes)
    rate = Decimal(str(commission_rate_pct)) / Decimal(100) if commission_rate_pct else Decimal(1)
    return int(customers_per_week * Decimal("4.33") * Decimal(avg_price) * rate)


def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=7)


def weekly_open_hours(stylist, today: date | None = None) -> Decimal:
    today = today or today_local()
    start, end = week_bounds(today)
    total = Decimal(0)
    for slot in AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN, date__gte=start, date__lt=end):
        total += slot.hours
    return total


def availability_summary(stylist, today: date | None = None) -> dict:
    today = today or today_local()
    hours = weekly_open_hours(stylist, today)
    start, end = week_bounds(today)
    return {
        "week_start": start,
        "week_end": end - timedelta(days=1),
        "open_hours": hours,
        "potential_income": potential_monthly_income(hours, stylist.avg_price, stylist.commission_rate, stylist.avg_service_minutes),
        "upcoming_slots": AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN, date__gte=today).order_by("date", "start_time")[:20],
        "waitlist_count": WaitlistEntry.objects.filter(stylist=stylist, status=WaitlistEntry.Status.ACTIVE).count(),
        "needs_settings": not (stylist.avg_price and stylist.commission_rate),
    }


def expire_past_slots(stylist, today: date | None = None) -> int:
    today = today or today_local()
    return AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN, date__lt=today).update(status=AvailabilitySlot.Status.CLOSED)


def free_alternatives(stylist) -> list[dict]:
    """通数を使わない告知手段の提案（固定文）。"""
    link = stylist.hotpepper_url or "（予約URL未設定）"
    return [
        {"title": "リッチメニューを更新する", "detail": "ボタンの文字や画像を変えるだけで、友だち全員が次にトークを開いたときに伝わります。通数0。", "url_name": "broadcasts:richmenu"},
        {"title": "あいさつメッセージに載せる", "detail": f"LINE公式アカウントマネージャー › あいさつメッセージ に「今月の空き状況」や「新メニュー」を追記。新しく友だち追加した人に自動で届きます。予約URL: {link}", "url_name": ""},
        {"title": "LINE VOOM・Instagramに投稿する", "detail": "空き枠や新メニューは VOOM とストーリーズに同じ内容を投稿。SNS投稿の生成機能で下書きを作れます。", "url_name": "drafts:sns_list"},
        {"title": "個別に送る（少人数なら無料）", "detail": "キャンセル待ちの人が数名なら、1人ずつ「コピーしてLINEで開く」で送れば通数を使いません。", "url_name": "broadcasts:waitlist"},
    ]
