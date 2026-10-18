"""「今日のおすすめ対応」と月次集計。"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q

from apps.core.dates import local_date_range_to_datetimes, month_start, month_end_exclusive, shift_months, today_local, year_month


def build_today(stylist, today=None) -> dict:
    from apps.drafts.models import Draft
    from apps.karte.models import VoiceMemo
    from apps.lineapp.models import InboundMessage
    from apps.visits.models import FollowUp, Reservation

    today = today or today_local()
    start_dt, end_dt = local_date_range_to_datetimes(today, today + timedelta(days=1))

    processing_memos = VoiceMemo.objects.filter(stylist=stylist, status__in=VoiceMemo.PROCESSING_STATUSES).select_related("customer")
    failed_memos = VoiceMemo.objects.filter(stylist=stylist, status=VoiceMemo.Status.FAILED).select_related("customer")[:5]

    unreplied = (
        InboundMessage.objects.filter(stylist=stylist, replied_at__isnull=True, ignored=False)
        .select_related("customer")
        .order_by("-received_at")[:20]
    )

    drafts_to_send = (
        Draft.objects.filter(
            stylist=stylist,
            status__in=[Draft.Status.DRAFT, Draft.Status.APPROVED],
            kind__in=[Draft.Kind.THANKS_CARE, Draft.Kind.NEXT_VISIT, Draft.Kind.CUSTOM],
        )
        .filter(Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=today))
        .select_related("customer")
        .order_by("scheduled_for", "-created_at")[:20]
    )

    due_followups = (
        FollowUp.objects.filter(stylist=stylist, status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY], due_date__lte=today)
        .select_related("customer", "draft")
        .order_by("due_date")[:20]
    )

    todays_reservations = (
        Reservation.objects.filter(stylist=stylist, reserved_for__gte=start_dt, reserved_for__lt=end_dt)
        .exclude(status=Reservation.Status.CANCELLED)
        .select_related("customer")
        .order_by("reserved_for")
    )

    month_stats = monthly_stats(stylist, months=1)["rows"][0]

    from apps.reels.recommend import week_count, weekly_plan

    sns_plan = weekly_plan(stylist, today)

    return {
        "today": today,
        "sns_plan": sns_plan,
        "sns_week_count": week_count(stylist, today),
        "processing_memos": processing_memos,
        "failed_memos": failed_memos,
        "unreplied": unreplied,
        "drafts_to_send": drafts_to_send,
        "due_followups": due_followups,
        "todays_reservations": todays_reservations,
        "month_stats": month_stats,
        "has_anything": any(
            [processing_memos.exists(), unreplied, drafts_to_send, due_followups, todays_reservations.exists()]
        ),
    }


def stats_for_period(stylist, start, end_exclusive) -> dict:
    from apps.drafts.models import SnsPost
    from apps.lineapp.models import LinkClick, Message
    from apps.visits.models import Reservation, Visit

    start_dt, end_dt = local_date_range_to_datetimes(start, end_exclusive)

    messages = Message.objects.filter(stylist=stylist, sent_at__gte=start_dt, sent_at__lt=end_dt, status=Message.Status.SENT)
    by_route = {row["route"]: row["n"] for row in messages.values("route").annotate(n=Count("id"))}

    reservations = Reservation.objects.filter(stylist=stylist, created_at__gte=start_dt, created_at__lt=end_dt).exclude(
        status=Reservation.Status.CANCELLED
    )
    attributed = reservations.filter(attributed_message__isnull=False).count()

    visits = Visit.objects.filter(stylist=stylist, visited_at__gte=start_dt, visited_at__lt=end_dt)
    clicks = LinkClick.objects.filter(link__stylist=stylist, clicked_at__gte=start_dt, clicked_at__lt=end_dt).count()
    sns_posted = SnsPost.objects.filter(stylist=stylist, posted_at__gte=start_dt, posted_at__lt=end_dt).count()

    return {
        "label": year_month(start),
        "messages_total": messages.count(),
        "messages_copy": by_route.get(Message.Route.COPY, 0),
        "messages_reply": by_route.get(Message.Route.REPLY, 0),
        "messages_push": by_route.get(Message.Route.PUSH, 0),
        "reservations_total": reservations.count(),
        "reservations_attributed": attributed,
        "visits": visits.count(),
        "link_clicks": clicks,
        "sns_posted": sns_posted,
    }


def monthly_stats(stylist, months: int = 6) -> dict:
    today = today_local()
    rows = []
    for i in range(months):
        start = shift_months(month_start(today), -i)
        end = month_end_exclusive(start)
        rows.append(stats_for_period(stylist, start, end))
    return {"rows": rows, "current": rows[0]}


def build_digest() -> list[dict]:
    from apps.accounts.models import Stylist

    out = []
    for stylist in Stylist.objects.select_related("user").filter(onboarding_completed=True):
        t = build_today(stylist)
        out.append(
            {
                "stylist_id": stylist.id,
                "display_name": stylist.display_name,
                "email": stylist.user.email,
                "unreplied_messages": len(t["unreplied"]),
                "drafts_to_send": len(t["drafts_to_send"]),
                "due_followups": len(t["due_followups"]),
                "todays_reservations": t["todays_reservations"].count(),
            }
        )
    return out
