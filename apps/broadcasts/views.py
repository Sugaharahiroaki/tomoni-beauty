from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.ai.claude_client import AIError
from apps.core.dates import today_local
from apps.core.decorators import stylist_required

from .forms import AvailabilitySlotForm, BroadcastForm, RichMenuForm, WaitlistForm
from .models import AvailabilitySlot, Broadcast, RichMenu, WaitlistEntry
from .richmenu import publish_rich_menu, render_rich_menu_image, unpublish_rich_menu
from .services import BroadcastError, availability_summary, estimate_broadcast, expire_past_slots, free_alternatives, frequency_status, generate_body, segment_summary, send_broadcast


# ---------------------------------------------------------------------------
# 一斉配信
# ---------------------------------------------------------------------------
@stylist_required
def broadcast_list(request):
    qs = Broadcast.objects.filter(stylist=request.stylist)
    channel = getattr(request.stylist, "line_channel", None)
    context = {
        "drafts": qs.filter(status=Broadcast.Status.DRAFT),
        "history": qs.exclude(status=Broadcast.Status.DRAFT)[:20],
        "frequency": frequency_status(request.stylist),
        "quota": channel.quota_summary() if channel else None,
        "channel": channel,
        "alternatives": free_alternatives(request.stylist),
    }
    return render(request, "broadcasts/broadcast_list.html", context)


@stylist_required
def broadcast_create(request):
    initial = {"kind": request.GET.get("kind") or Broadcast.Kind.ANNOUNCEMENT}
    if initial["kind"] == Broadcast.Kind.WAITLIST:
        initial["waitlist_only"] = True
    form = BroadcastForm(request.POST or None, stylist=request.stylist, initial=initial)
    if request.method == "POST" and form.is_valid():
        broadcast = form.save()
        if request.POST.get("action") == "draft_ai":
            try:
                generate_body(broadcast, form.cleaned_data.get("ai_notes", ""))
                messages.success(request, "AIで下書きを作りました。内容を確認・編集してください。")
            except AIError as exc:
                messages.error(request, str(exc))
            return redirect("broadcasts:edit", pk=broadcast.pk)
        return redirect("broadcasts:detail", pk=broadcast.pk)
    return render(request, "broadcasts/broadcast_form.html", {"form": form, "is_new": True})


@stylist_required
def broadcast_edit(request, pk: int):
    broadcast = get_object_or_404(Broadcast, pk=pk, stylist=request.stylist)
    if not broadcast.is_editable:
        return redirect("broadcasts:detail", pk=pk)
    form = BroadcastForm(request.POST or None, stylist=request.stylist, instance=broadcast)
    if request.method == "POST" and form.is_valid():
        broadcast = form.save()
        if request.POST.get("action") == "draft_ai":
            try:
                generate_body(broadcast, form.cleaned_data.get("ai_notes", ""))
                messages.success(request, "AIで下書きを作り直しました")
            except AIError as exc:
                messages.error(request, str(exc))
            return redirect("broadcasts:edit", pk=pk)
        return redirect("broadcasts:detail", pk=pk)
    return render(request, "broadcasts/broadcast_form.html", {"form": form, "broadcast": broadcast, "is_new": False})


@stylist_required
def broadcast_detail(request, pk: int):
    broadcast = get_object_or_404(Broadcast.objects.prefetch_related("slots"), pk=pk, stylist=request.stylist)
    estimate = estimate_broadcast(broadcast, refresh_quota=bool(request.GET.get("refresh"))) if broadcast.is_editable else None
    context = {
        "broadcast": broadcast,
        "estimate": estimate,
        "segment_lines": segment_summary(broadcast.segment),
        "recipients": broadcast.recipients.select_related("customer")[:50] if not broadcast.is_editable else None,
        "preview": estimate["audience"][:30] if estimate else [],
    }
    return render(request, "broadcasts/broadcast_detail.html", context)


@stylist_required
@require_POST
def broadcast_send(request, pk: int):
    broadcast = get_object_or_404(Broadcast, pk=pk, stylist=request.stylist)
    if request.POST.get("confirm") != "1":
        messages.error(request, "対象人数と消費通数を確認してチェックを入れてください")
        return redirect("broadcasts:detail", pk=pk)
    try:
        send_broadcast(broadcast, force_frequency=request.POST.get("force_frequency") == "1")
    except BroadcastError as exc:
        messages.error(request, str(exc))
        return redirect("broadcasts:detail", pk=pk)
    if broadcast.status == Broadcast.Status.SENT:
        messages.success(request, f"{broadcast.sent_count}人に配信しました（{broadcast.sent_count}通消費）")
    else:
        messages.error(request, f"配信に失敗しました: {broadcast.error}")
    return redirect("broadcasts:detail", pk=pk)


@stylist_required
@require_POST
def broadcast_cancel(request, pk: int):
    broadcast = get_object_or_404(Broadcast, pk=pk, stylist=request.stylist)
    if broadcast.is_editable:
        broadcast.status = Broadcast.Status.CANCELLED
        broadcast.save(update_fields=["status", "updated_at"])
        messages.info(request, "配信を取り消しました")
    return redirect("broadcasts:list")


# ---------------------------------------------------------------------------
# 空き枠
# ---------------------------------------------------------------------------
@stylist_required
def availability(request):
    from .auto_slots import sync_auto_slots

    expire_past_slots(request.stylist)
    sync_auto_slots(request.stylist)
    form = AvailabilitySlotForm(request.POST or None, initial={"date": today_local()})
    if request.method == "POST" and form.is_valid():
        slot = form.save(commit=False)
        slot.stylist = request.stylist
        slot.save()
        messages.success(request, "空き枠を追加しました")
        return redirect("broadcasts:availability")
    summary = availability_summary(request.stylist)
    slots = AvailabilitySlot.objects.filter(stylist=request.stylist, date__gte=today_local()).order_by("date", "start_time")
    return render(request, "broadcasts/availability.html", {"form": form, "summary": summary, "slots": slots})


@stylist_required
@require_POST
def slot_update(request, pk: int):
    slot = get_object_or_404(AvailabilitySlot, pk=pk, stylist=request.stylist)
    action = request.POST.get("action")
    if action == "delete":
        slot.delete()
    elif action == "filled":
        slot.status = AvailabilitySlot.Status.FILLED
        slot.save(update_fields=["status", "updated_at"])
    elif action == "close":
        slot.status = AvailabilitySlot.Status.CLOSED  # 自動の枠を「受けない」に（同じ時間に再び出さない）
        slot.save(update_fields=["status", "updated_at"])
    elif action == "reopen":
        slot.status = AvailabilitySlot.Status.OPEN
        slot.save(update_fields=["status", "updated_at"])
    return redirect("broadcasts:availability")


# ---------------------------------------------------------------------------
# キャンセル待ち
# ---------------------------------------------------------------------------
@stylist_required
def waitlist(request):
    form = WaitlistForm(request.POST or None, stylist=request.stylist)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.stylist = request.stylist
        entry.source = WaitlistEntry.Source.MANUAL
        entry.save()
        messages.success(request, "キャンセル待ちに登録しました")
        return redirect("broadcasts:waitlist")
    entries = WaitlistEntry.objects.filter(stylist=request.stylist).select_related("customer")
    channel = getattr(request.stylist, "line_channel", None)
    return render(
        request,
        "broadcasts/waitlist.html",
        {"form": form, "active": entries.filter(status=WaitlistEntry.Status.ACTIVE), "others": entries.exclude(status=WaitlistEntry.Status.ACTIVE)[:30], "channel": channel},
    )


@stylist_required
@require_POST
def waitlist_update(request, pk: int):
    entry = get_object_or_404(WaitlistEntry, pk=pk, stylist=request.stylist)
    action = request.POST.get("action")
    mapping = {"booked": WaitlistEntry.Status.BOOKED, "close": WaitlistEntry.Status.CLOSED, "reopen": WaitlistEntry.Status.ACTIVE}
    if action in mapping:
        entry.status = mapping[action]
        entry.save(update_fields=["status", "updated_at"])
    return redirect("broadcasts:waitlist")


# ---------------------------------------------------------------------------
# リッチメニュー
# ---------------------------------------------------------------------------
@stylist_required
def richmenu(request):
    rich_menu, _ = RichMenu.objects.get_or_create(stylist=request.stylist)
    form = RichMenuForm(request.POST or None, request.FILES or None, instance=rich_menu)
    channel = getattr(request.stylist, "line_channel", None)
    if request.method == "POST" and form.is_valid():
        form.save()
        action = request.POST.get("action")
        if action == "publish":
            try:
                publish_rich_menu(rich_menu)
                messages.success(request, "リッチメニューを公開しました（友だち全員に表示されます）")
            except ValueError as exc:
                messages.error(request, str(exc))
        elif action == "unpublish":
            try:
                unpublish_rich_menu(rich_menu)
                messages.info(request, "リッチメニューを取り下げました")
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.success(request, "保存しました")
        return redirect("broadcasts:richmenu")
    return render(request, "broadcasts/richmenu.html", {"form": form, "rich_menu": rich_menu, "channel": channel, "has_hotpepper": request.stylist.has_hotpepper})


@stylist_required
def richmenu_preview(request):
    rich_menu, _ = RichMenu.objects.get_or_create(stylist=request.stylist)
    data = render_rich_menu_image(rich_menu.labels)
    response = HttpResponse(data, content_type="image/png")
    response["Cache-Control"] = "no-store"
    return response
