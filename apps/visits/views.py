import json
from datetime import datetime

from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import Stylist
from apps.core.dates import today_local
from apps.core.decorators import stylist_required
from apps.core.views import _internal_token_ok
from apps.customers.models import Customer

from .email_import import import_reservation_email, reparse_email
from .forms import ReservationForm, VisitForm
from .models import FollowUp, Reservation, ReservationEmail, Visit
from .services import attribute_reservation, mark_visited


# ---------------------------------------------------------------------------
# 予約通知メールの取り込み
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def internal_reservation_email(request):
    """n8n（IMAP）から: {"stylist_key": "...", "subject": "...", "body": "...", "received_at": ISO, "from": "..."}"""
    if not _internal_token_ok(request):
        return HttpResponseForbidden("forbidden")
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid json"}, status=400)
    key = (payload.get("stylist_key") or "").strip()
    stylist = Stylist.objects.filter(email_import_key=key).first() if key else None
    if stylist is None:
        return JsonResponse({"error": "unknown stylist_key"}, status=404)
    received_at = parse_datetime(payload.get("received_at") or "") or timezone.now()
    if timezone.is_naive(received_at):
        received_at = timezone.make_aware(received_at, timezone.get_current_timezone())
    email = import_reservation_email(stylist, payload.get("subject") or "", payload.get("body") or "", received_at, payload.get("from") or "", source="n8n")
    return JsonResponse({"status": email.status, "parse_method": email.parse_method, "reservation_id": email.reservation_id, "error": email.error})


@stylist_required
def reservation_emails(request):
    stylist = request.stylist
    stylist.ensure_email_import_key()
    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        body = (request.POST.get("body") or "").strip()
        if not body:
            messages.error(request, "メール本文を貼り付けてください")
        else:
            email = import_reservation_email(stylist, subject, body, timezone.now(), source="paste")
            if email.status == ReservationEmail.Status.APPLIED:
                messages.success(request, "予約として登録しました")
            elif email.status == ReservationEmail.Status.NEEDS_REVIEW:
                messages.warning(request, f"登録しましたが確認が必要です: {email.error}")
            else:
                messages.error(request, email.error or "読み取れませんでした")
        return redirect("visits:reservation_emails")
    emails = ReservationEmail.objects.filter(stylist=stylist).select_related("reservation", "reservation__customer")[:50]
    return render(request, "visits/reservation_emails.html", {"emails": emails, "import_key": stylist.email_import_key})


@stylist_required
@require_POST
def reservation_email_reparse(request, pk: int):
    email = get_object_or_404(ReservationEmail, pk=pk, stylist=request.stylist)
    reparse_email(email)
    messages.info(request, f"再解析しました: {email.get_status_display()}")
    return redirect("visits:reservation_emails")


@stylist_required
@require_POST
def reservation_email_ignore(request, pk: int):
    email = get_object_or_404(ReservationEmail, pk=pk, stylist=request.stylist)
    email.status = ReservationEmail.Status.IGNORED
    email.save(update_fields=["status", "updated_at"])
    return redirect("visits:reservation_emails")


@stylist_required
@require_POST
def reservation_email_key_regenerate(request):
    request.stylist.email_import_key = ""
    request.stylist.ensure_email_import_key()
    messages.success(request, "取り込みキーを再発行しました。n8n側の設定も更新してください。")
    return redirect("visits:reservation_emails")


@stylist_required
def reservation_list(request):
    today = today_local()
    qs = Reservation.objects.filter(stylist=request.stylist).select_related("customer", "attributed_message")
    upcoming = qs.filter(status=Reservation.Status.BOOKED, reserved_for__date__gte=today).order_by("reserved_for")
    past = qs.exclude(id__in=upcoming.values("id")).order_by("-reserved_for")[:30]
    return render(request, "visits/reservation_list.html", {"upcoming": upcoming, "past": past, "today": today})


@stylist_required
def reservation_create(request):
    initial = {}
    customer_id = request.GET.get("customer")
    if customer_id:
        customer = Customer.objects.filter(stylist=request.stylist, pk=customer_id).first()
        if customer:
            initial["customer"] = customer
    form = ReservationForm(request.POST or None, stylist=request.stylist, initial=initial)
    if request.method == "POST" and form.is_valid():
        reservation = form.save(commit=False)
        reservation.stylist = request.stylist
        reservation.source = Reservation.Source.MANUAL
        reservation.save()
        attribute_reservation(reservation)
        if reservation.attributed_message_id:
            messages.success(request, "予約を登録しました（直近の案内からの予約として記録）")
        else:
            messages.success(request, "予約を登録しました")
        return redirect("visits:reservation_list")
    return render(request, "visits/reservation_form.html", {"form": form, "is_new": True})


@stylist_required
def reservation_edit(request, pk: int):
    reservation = get_object_or_404(Reservation, pk=pk, stylist=request.stylist)
    form = ReservationForm(request.POST or None, instance=reservation, stylist=request.stylist)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("visits:reservation_list")
    return render(request, "visits/reservation_form.html", {"form": form, "reservation": reservation, "is_new": False})


@stylist_required
@require_POST
def reservation_visited(request, pk: int):
    reservation = get_object_or_404(Reservation, pk=pk, stylist=request.stylist)
    if reservation.customer is None:
        messages.error(request, "来店にするには、先にお客様を選んでください")
        return redirect("visits:reservation_edit", pk=pk)
    visit = mark_visited(reservation, visited_at=timezone.now() if reservation.reserved_for > timezone.now() else reservation.reserved_for)
    messages.success(request, "来店として記録しました。施術後のメモを録音しましょう。")
    return redirect(f"/memos/new/?customer={visit.customer_id}&visit={visit.id}")


@stylist_required
@require_POST
def reservation_cancel(request, pk: int):
    reservation = get_object_or_404(Reservation, pk=pk, stylist=request.stylist)
    reservation.status = Reservation.Status.NO_SHOW if request.POST.get("no_show") else Reservation.Status.CANCELLED
    reservation.save(update_fields=["status", "updated_at"])
    messages.success(request, "予約を取り消しました")
    return redirect("visits:reservation_list")


@stylist_required
def visit_create(request):
    initial = {"visited_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")}
    customer_id = request.GET.get("customer")
    if customer_id:
        initial["customer"] = Customer.objects.filter(stylist=request.stylist, pk=customer_id).first()
    form = VisitForm(request.POST or None, stylist=request.stylist, initial=initial)
    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.stylist = request.stylist
        visit.save()
        messages.success(request, "来店を記録しました")
        if request.POST.get("then_memo"):
            return redirect(f"/memos/new/?customer={visit.customer_id}&visit={visit.id}")
        return redirect("customers:detail", pk=visit.customer_id)
    return render(request, "visits/visit_form.html", {"form": form})


@stylist_required
def followup_list(request):
    today = today_local()
    qs = FollowUp.objects.filter(stylist=request.stylist).select_related("customer", "draft")
    due = qs.filter(status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY], due_date__lte=today)
    upcoming = qs.filter(status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY], due_date__gt=today)[:30]
    done = qs.filter(status__in=[FollowUp.Status.SENT, FollowUp.Status.SKIPPED]).order_by("-updated_at")[:20]
    return render(request, "visits/followup_list.html", {"due": due, "upcoming": upcoming, "done": done, "today": today})


@stylist_required
@require_POST
def followup_skip(request, pk: int):
    fu = get_object_or_404(FollowUp, pk=pk, stylist=request.stylist)
    fu.status = FollowUp.Status.SKIPPED
    fu.skip_reason = request.POST.get("reason", "手動で見送り")[:100]
    fu.completed_at = timezone.now()
    fu.save(update_fields=["status", "skip_reason", "completed_at", "updated_at"])
    messages.info(request, "このフォローは見送りにしました")
    return redirect(request.POST.get("next") or "visits:followup_list")


@stylist_required
@require_POST
def followup_prepare(request, pk: int):
    """今すぐ次回案内の下書きを作る（日次バッチを待たない）。"""
    from apps.drafts.services import prepare_follow_up_draft

    fu = get_object_or_404(FollowUp, pk=pk, stylist=request.stylist)
    draft, reason = prepare_follow_up_draft(fu)
    if draft is None:
        messages.warning(request, f"下書きは作成しませんでした（{reason}）")
        return redirect("visits:followup_list")
    return redirect("drafts:detail", pk=draft.pk)
