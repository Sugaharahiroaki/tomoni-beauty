"""予約通知メールの取り込み（n8n からの POST / 画面での貼り付け）。"""
from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.ai import services as ai_services
from apps.ai.claude_client import AIError
from apps.customers.models import Customer

from .email_parser import name_key, regex_parse
from .models import Reservation, ReservationEmail
from .services import attribute_reservation

logger = logging.getLogger(__name__)


def match_customer(stylist, name: str, kana: str = "") -> tuple[Customer | None, list[Customer]]:
    """氏名・カナで顧客を照合。完全一致1件なら確定、複数・部分一致は候補として返す。"""
    keys = {name_key(v) for v in (name, kana) if v}
    keys.discard("")
    if not keys:
        return None, []
    candidates = []
    exact = []
    for c in Customer.objects.filter(stylist=stylist):
        c_keys = {name_key(c.name), name_key(c.kana), name_key(c.line_display_name)}
        c_keys.discard("")
        if keys & c_keys:
            exact.append(c)
        elif any(k and ck and (k in ck or ck in k) for k in keys for ck in c_keys):
            candidates.append(c)
    if len(exact) == 1:
        return exact[0], exact
    return None, exact + candidates


def parse_email(subject: str, body: str, received_at: datetime) -> tuple[dict | None, str]:
    """正規表現で解析し、足りなければ AI で補完する。戻り値: (parsed, method)"""
    ref = timezone.localtime(received_at).date()
    parsed = regex_parse(subject, body, reference=ref)
    if parsed and parsed.get("reserved_for") and (parsed.get("customer_name") or parsed["kind"] == "cancelled"):
        return parsed, "regex"
    try:
        ai = ai_services.parse_reservation_email(subject, body, timezone.localtime(received_at).isoformat())
    except AIError as exc:
        logger.warning("ai email parse failed: %s", exc)
        return parsed, "regex" if parsed else "failed"
    if parsed:
        for k, v in ai.items():
            if v and not parsed.get(k):
                parsed[k] = v
        parsed["confidence"] = ai.get("confidence", "low")
        return parsed, "regex+ai"
    if ai.get("reserved_for") or ai.get("customer_name"):
        return ai, "ai"
    return None, "failed"


def apply_parsed(email: ReservationEmail) -> Reservation | None:
    stylist = email.stylist
    parsed = email.parsed or {}
    reserved_for = None
    if parsed.get("reserved_for"):
        try:
            naive = datetime.fromisoformat(parsed["reserved_for"][:16])
            reserved_for = timezone.make_aware(naive, timezone.get_current_timezone())
        except ValueError:
            reserved_for = None

    customer, candidates = match_customer(stylist, parsed.get("customer_name", ""), parsed.get("customer_kana", ""))
    kind = parsed.get("kind", "unknown")

    with transaction.atomic():
        if kind == "cancelled":
            qs = Reservation.objects.filter(stylist=stylist, status=Reservation.Status.BOOKED)
            if customer:
                qs = qs.filter(customer=customer)
            elif parsed.get("customer_name"):
                qs = qs.filter(customer_name_raw__icontains=parsed["customer_name"][:10])
            if reserved_for:
                qs = qs.filter(reserved_for__date=timezone.localtime(reserved_for).date())
            target = qs.order_by("reserved_for").first()
            if target:
                target.status = Reservation.Status.CANCELLED
                target.note = (target.note + "\n" if target.note else "") + "予約通知メール（キャンセル）で更新"
                target.save(update_fields=["status", "note", "updated_at"])
                email.reservation = target
                email.status = ReservationEmail.Status.APPLIED
                email.save(update_fields=["reservation", "status", "updated_at"])
                return target
            email.status = ReservationEmail.Status.NEEDS_REVIEW
            email.error = "キャンセル対象の予約が見つかりませんでした"
            email.save(update_fields=["status", "error", "updated_at"])
            return None

        if reserved_for is None:
            email.status = ReservationEmail.Status.NEEDS_REVIEW
            email.error = "予約日時を読み取れませんでした"
            email.save(update_fields=["status", "error", "updated_at"])
            return None

        # 変更: 同一顧客の同日の予約があれば日時を更新
        if kind == "changed" and customer:
            existing = Reservation.objects.filter(stylist=stylist, customer=customer, status=Reservation.Status.BOOKED).order_by("reserved_for").first()
            if existing:
                existing.reserved_for = reserved_for
                existing.menu = parsed.get("menu") or existing.menu
                existing.save(update_fields=["reserved_for", "menu", "updated_at"])
                email.reservation = existing
                email.status = ReservationEmail.Status.APPLIED
                email.save(update_fields=["reservation", "status", "updated_at"])
                return existing

        # 重複（同一顧客・同一日時）はスキップ
        dup = Reservation.objects.filter(stylist=stylist, reserved_for=reserved_for)
        dup = dup.filter(customer=customer) if customer else dup.filter(customer_name_raw=parsed.get("customer_name", ""))
        if dup.exists():
            email.reservation = dup.first()
            email.status = ReservationEmail.Status.APPLIED
            email.error = "同じ予約が登録済みのためスキップ"
            email.save(update_fields=["reservation", "status", "error", "updated_at"])
            return dup.first()

        reservation = Reservation.objects.create(
            stylist=stylist,
            customer=customer,
            customer_name_raw="" if customer else (parsed.get("customer_name") or parsed.get("customer_kana") or "（不明）")[:100],
            reserved_for=reserved_for,
            menu=(parsed.get("menu") or "")[:200],
            source=Reservation.Source.EMAIL,
            note=f"予約通知メールから取り込み（{email.parse_method}）" + (f" / 候補: {', '.join(c.name for c in candidates[:3])}" if candidates and not customer else ""),
        )
        if customer:
            attribute_reservation(reservation, now=email.received_at)
        email.reservation = reservation
        email.status = ReservationEmail.Status.APPLIED if customer else ReservationEmail.Status.NEEDS_REVIEW
        email.error = "" if customer else "お客様を照合できませんでした（予約は未照合で登録）"
        email.save(update_fields=["reservation", "status", "error", "updated_at"])
        return reservation


def import_reservation_email(stylist, subject: str, body: str, received_at: datetime | None = None, sender: str = "", source: str = "n8n") -> ReservationEmail:
    received_at = received_at or timezone.now()
    email = ReservationEmail.objects.create(stylist=stylist, subject=subject[:300], body=body[:20000], sender=sender[:200], received_at=received_at, source=source)
    parsed, method = parse_email(subject, body, received_at)
    email.parse_method = method
    if not parsed:
        email.status = ReservationEmail.Status.UNPARSED
        email.error = "予約情報を読み取れませんでした。手入力で登録してください。"
        email.save(update_fields=["parse_method", "status", "error", "updated_at"])
        return email
    email.parsed = parsed
    email.status = ReservationEmail.Status.PARSED
    email.save(update_fields=["parse_method", "parsed", "status", "updated_at"])
    apply_parsed(email)
    return email


def reparse_email(email: ReservationEmail) -> ReservationEmail:
    parsed, method = parse_email(email.subject, email.body, email.received_at)
    email.parse_method = method
    email.parsed = parsed or {}
    email.reservation = None
    email.error = ""
    email.status = ReservationEmail.Status.PARSED if parsed else ReservationEmail.Status.UNPARSED
    email.save()
    if parsed:
        apply_parsed(email)
    return email
