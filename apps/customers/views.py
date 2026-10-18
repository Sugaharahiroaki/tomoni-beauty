from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required

from .forms import CustomerForm, LinkLineForm
from .models import Customer
from .services import merge_line_shell_into

CONSENT_FIELDS = {"contact_ok", "photo_ok", "face_ok", "story_ok"}


@stylist_required
def customer_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = Customer.objects.filter(stylist=request.stylist).prefetch_related("tags")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(kana__icontains=q) | Q(line_display_name__icontains=q) | Q(tags__name__icontains=q)).distinct()
    review = qs.filter(needs_review=True)
    return render(request, "customers/customer_list.html", {"customers": qs, "q": q, "review_count": review.count()})


@stylist_required
def customer_detail(request, pk: int):
    customer = get_object_or_404(Customer.objects.prefetch_related("tags"), pk=pk, stylist=request.stylist)
    from apps.drafts.models import Draft, SnsPost
    from apps.karte.models import Karte
    from apps.lineapp.models import InboundMessage, Message
    from apps.visits.models import FollowUp, Reservation, Visit

    context = {
        "customer": customer,
        "kartes": Karte.objects.filter(customer=customer).order_by("-visited_on")[:10],
        "visits": Visit.objects.filter(customer=customer).order_by("-visited_at")[:10],
        "reservations": Reservation.objects.filter(customer=customer).order_by("-reserved_for")[:5],
        "drafts": Draft.objects.filter(customer=customer).exclude(status=Draft.Status.DISCARDED).order_by("-created_at")[:10],
        "messages_sent": Message.objects.filter(customer=customer).order_by("-sent_at")[:10],
        "inbound": InboundMessage.objects.filter(customer=customer).order_by("-received_at")[:10],
        "followups": FollowUp.objects.filter(customer=customer, status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY]).order_by("due_date"),
        "sns_posts": SnsPost.objects.filter(customer=customer).order_by("-created_at")[:5],
        "link_form": LinkLineForm(stylist=request.stylist, exclude_pk=customer.pk) if customer.is_line_linked and customer.needs_review else None,
    }
    return render(request, "customers/customer_detail.html", context)


@stylist_required
def customer_create(request):
    form = CustomerForm(request.POST or None, stylist=request.stylist)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        messages.success(request, f"{customer.name} さんを登録しました")
        nxt = request.GET.get("next")
        if nxt == "memo":
            return redirect(f"{reverse_memo_new()}?customer={customer.pk}")
        return redirect("customers:detail", pk=customer.pk)
    return render(request, "customers/customer_form.html", {"form": form, "is_new": True})


def reverse_memo_new():
    from django.urls import reverse

    return reverse("karte:memo_new")


@stylist_required
def customer_edit(request, pk: int):
    customer = get_object_or_404(Customer, pk=pk, stylist=request.stylist)
    form = CustomerForm(request.POST or None, instance=customer, stylist=request.stylist)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("customers:detail", pk=customer.pk)
    return render(request, "customers/customer_form.html", {"form": form, "customer": customer, "is_new": False})


@stylist_required
@require_POST
def customer_delete(request, pk: int):
    customer = get_object_or_404(Customer, pk=pk, stylist=request.stylist)
    name = customer.name
    customer.delete()  # カルテ・下書き・メッセージ履歴もすべて削除（個人情報の削除要求に対応）
    messages.success(request, f"{name} さんのデータをすべて削除しました")
    return redirect("customers:list")


@stylist_required
@require_POST
def customer_consent(request, pk: int):
    """同意フラグのワンタップ切り替え（詳細画面・カルテ画面から）。"""
    customer = get_object_or_404(Customer, pk=pk, stylist=request.stylist)
    changed = False
    for field in CONSENT_FIELDS:
        if field in request.POST:
            value = request.POST.get(field) in ("1", "true", "on", "True")
            if getattr(customer, field) != value:
                setattr(customer, field, value)
                changed = True
    if changed:
        customer.record_consent_change()
        customer.save()
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "consents": dict(customer.consent_summary()), "updated_at": timezone.localtime(customer.consent_updated_at).isoformat() if customer.consent_updated_at else None})
    messages.success(request, "掲載・連絡の設定を更新しました")
    nxt = request.POST.get("next", "")
    if nxt.startswith("/"):
        return redirect(nxt)
    return redirect("customers:detail", pk=customer.pk)


@stylist_required
@require_POST
def customer_link_line(request, pk: int):
    """LINEから自動作成された仮顧客を、既存のお客様に統合する。"""
    shell = get_object_or_404(Customer, pk=pk, stylist=request.stylist)
    form = LinkLineForm(request.POST, stylist=request.stylist, exclude_pk=shell.pk)
    if not shell.is_line_linked:
        messages.error(request, "このお客様にはLINEが紐付いていません")
        return redirect("customers:detail", pk=pk)
    if form.is_valid():
        target = form.cleaned_data["target"]
        try:
            merge_line_shell_into(shell, target)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("customers:detail", pk=pk)
        messages.success(request, f"LINEアカウントを {target.name} さんに紐付けました")
        return redirect("customers:detail", pk=target.pk)
    messages.error(request, "紐付け先を選んでください")
    return redirect("customers:detail", pk=pk)


@stylist_required
def customer_search_json(request):
    """録音画面のインクリメンタル検索用。"""
    q = (request.GET.get("q") or "").strip()
    qs = Customer.objects.filter(stylist=request.stylist)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(kana__icontains=q) | Q(line_display_name__icontains=q))
    data = [{"id": c.id, "name": c.name, "kana": c.kana, "line": c.is_line_linked} for c in qs.order_by("name")[:20]]
    return JsonResponse({"results": data})
