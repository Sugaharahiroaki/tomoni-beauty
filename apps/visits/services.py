"""予約・来店の業務ロジック（帰属・重複送信防止・来店化）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import FollowUp, Reservation, Visit


def find_attributable_message(customer, reserved_at: datetime, window_days: int | None = None):
    """予約登録時点から window_days 日以内に送った案内のうち最新のものを返す。"""
    from apps.lineapp.models import Message

    if customer is None:
        return None
    days = settings.ATTRIBUTION_WINDOW_DAYS if window_days is None else window_days
    since = reserved_at - timedelta(days=days)
    return (
        Message.objects.filter(customer=customer, status=Message.Status.SENT, sent_at__gte=since, sent_at__lte=reserved_at)
        .exclude(kind=Message.Kind.REPLY)
        .order_by("-sent_at")
        .first()
    )


def attribute_reservation(reservation: Reservation, now: datetime | None = None) -> Reservation:
    now = now or timezone.now()
    msg = find_attributable_message(reservation.customer, now)
    if msg and reservation.attributed_message_id != msg.id:
        reservation.attributed_message = msg
        reservation.save(update_fields=["attributed_message", "updated_at"])
    return reservation


def has_upcoming_reservation(customer, today: date | None = None) -> bool:
    """予約済みの人に次回案内を出さないための判定。"""
    today = today or timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, datetime.min.time()), timezone.get_current_timezone())
    return Reservation.objects.filter(customer=customer, status=Reservation.Status.BOOKED, reserved_for__gte=start).exists()


@transaction.atomic
def mark_visited(reservation: Reservation, visited_at: datetime | None = None, price: int | None = None) -> Visit:
    visited_at = visited_at or reservation.reserved_for
    reservation.status = Reservation.Status.VISITED
    reservation.save(update_fields=["status", "updated_at"])
    visit, _ = Visit.objects.get_or_create(
        reservation=reservation,
        defaults={
            "stylist": reservation.stylist,
            "customer": reservation.customer,
            "visited_at": visited_at,
            "menu": reservation.menu,
            "price": price,
        },
    )
    # 来店したら、この顧客の未送信フォローは役目を終える
    FollowUp.objects.filter(customer=reservation.customer, status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY]).update(
        status=FollowUp.Status.SKIPPED, skip_reason="来店済み", completed_at=timezone.now()
    )
    return visit


def schedule_follow_up(stylist, customer, karte, due_date: date, kind: str = FollowUp.Kind.NEXT_VISIT) -> FollowUp:
    """同じ顧客の未処理フォローは1件に保つ（新しいカルテで上書き）。"""
    FollowUp.objects.filter(customer=customer, kind=kind, status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY]).update(
        status=FollowUp.Status.SKIPPED, skip_reason="新しい来店で更新", completed_at=timezone.now()
    )
    return FollowUp.objects.create(stylist=stylist, customer=customer, karte=karte, kind=kind, due_date=due_date)
