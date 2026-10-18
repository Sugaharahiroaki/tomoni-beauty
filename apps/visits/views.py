from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.dates import today_local
from apps.core.decorators import stylist_required
from apps.customers.models import Customer

from .forms import ReservationForm, VisitForm
from .models import FollowUp, Reservation, Visit
from .services import attribute_reservation, mark_visited


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
