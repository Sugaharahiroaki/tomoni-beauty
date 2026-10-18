from datetime import date

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.dates import today_local
from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue
from apps.customers.models import Customer
from apps.visits.models import Visit

from .forms import KarteForm, KartePhotoForm
from .models import Karte, KartePhoto, VoiceMemo

MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _is_fetch(request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


@stylist_required
def memo_new(request):
    customer = None
    visit = None
    if request.GET.get("customer"):
        customer = Customer.objects.filter(stylist=request.stylist, pk=request.GET["customer"]).first()
    if request.GET.get("visit"):
        visit = Visit.objects.filter(stylist=request.stylist, pk=request.GET["visit"]).first()
    recent_customers = Customer.objects.filter(stylist=request.stylist).order_by("-updated_at")[:8]
    return render(
        request,
        "karte/memo_new.html",
        {"customer": customer, "visit": visit, "recent_customers": recent_customers, "today": today_local()},
    )


@stylist_required
@require_POST
def memo_create(request):
    stylist = request.stylist
    customer = None
    customer_id = request.POST.get("customer_id")
    new_name = (request.POST.get("new_customer_name") or "").strip()
    if customer_id:
        customer = Customer.objects.filter(stylist=stylist, pk=customer_id).first()
    if customer is None and new_name:
        customer = Customer.objects.create(stylist=stylist, name=new_name[:100])
    if customer is None:
        return _memo_error(request, "お客様を選択してください")

    audio = request.FILES.get("audio")
    text_input = (request.POST.get("text_input") or "").strip()
    if not audio and not text_input:
        return _memo_error(request, "録音するか、テキストで入力してください")
    if audio and audio.size > MAX_AUDIO_BYTES:
        return _memo_error(request, "音声ファイルが大きすぎます（25MBまで）")

    visited_on = today_local()
    if request.POST.get("visited_on"):
        try:
            visited_on = date.fromisoformat(request.POST["visited_on"])
        except ValueError:
            pass

    visit = None
    if request.POST.get("visit_id"):
        visit = Visit.objects.filter(stylist=stylist, pk=request.POST["visit_id"]).first()

    memo = VoiceMemo.objects.create(
        stylist=stylist,
        customer=customer,
        visit=visit,
        visited_on=visited_on,
        audio=audio,
        audio_mime=(audio.content_type if audio else ""),
        text_input=text_input,
    )
    try:
        duration = int(float(request.POST.get("duration_seconds") or 0))
        if duration > 0:
            memo.duration_seconds = duration
            memo.save(update_fields=["duration_seconds"])
    except ValueError:
        pass

    enqueue("apps.karte.tasks.process_voice_memo", memo.id)
    url = reverse("karte:memo_detail", kwargs={"pk": memo.pk})
    if _is_fetch(request):
        return JsonResponse({"ok": True, "redirect": url})
    return redirect(url)


def _memo_error(request, message):
    if _is_fetch(request):
        return JsonResponse({"error": message}, status=400)
    messages.error(request, message)
    return redirect("karte:memo_new")


@stylist_required
def memo_detail(request, pk: int):
    memo = get_object_or_404(VoiceMemo.objects.select_related("customer"), pk=pk, stylist=request.stylist)
    karte = getattr(memo, "karte", None)
    if memo.status == VoiceMemo.Status.DONE and karte is not None:
        return redirect("karte:detail", pk=karte.pk)
    return render(request, "karte/memo_processing.html", {"memo": memo})


@stylist_required
def memo_status(request, pk: int):
    memo = get_object_or_404(VoiceMemo, pk=pk, stylist=request.stylist)
    karte = getattr(memo, "karte", None)
    return JsonResponse(
        {
            "status": memo.status,
            "label": memo.get_status_display(),
            "percent": memo.progress_percent,
            "error": memo.error,
            "redirect": reverse("karte:detail", kwargs={"pk": karte.pk}) if (memo.status == VoiceMemo.Status.DONE and karte) else None,
        }
    )


@stylist_required
@require_POST
def memo_retry(request, pk: int):
    memo = get_object_or_404(VoiceMemo, pk=pk, stylist=request.stylist)
    if memo.status != VoiceMemo.Status.FAILED:
        return redirect("karte:memo_detail", pk=pk)
    text = (request.POST.get("text_input") or "").strip()
    if text:
        memo.text_input = text
        memo.audio = None  # テキストで再実行
    memo.status = VoiceMemo.Status.UPLOADED
    memo.error = ""
    memo.save()
    enqueue("apps.karte.tasks.process_voice_memo", memo.id)
    return redirect("karte:memo_detail", pk=pk)


@stylist_required
def karte_list(request):
    kartes = Karte.objects.filter(stylist=request.stylist).select_related("customer")[:50]
    pending = VoiceMemo.objects.filter(stylist=request.stylist).exclude(status=VoiceMemo.Status.DONE).select_related("customer")[:10]
    return render(request, "karte/karte_list.html", {"kartes": kartes, "pending": pending})


@stylist_required
def karte_detail(request, pk: int):
    karte = get_object_or_404(Karte.objects.select_related("customer", "memo"), pk=pk, stylist=request.stylist)
    from apps.drafts.models import Draft, SnsPost
    from apps.visits.models import FollowUp

    drafts = Draft.objects.filter(karte=karte).exclude(status=Draft.Status.DISCARDED).order_by("kind")
    context = {
        "karte": karte,
        "customer": karte.customer,
        "drafts": drafts,
        "photos": karte.photos.all(),
        "photo_form": KartePhotoForm(initial={"sns_ok": karte.customer.photo_ok}),
        "sns_posts": SnsPost.objects.filter(karte=karte).exclude(status=SnsPost.Status.DISCARDED),
        "follow_up": FollowUp.objects.filter(karte=karte).order_by("-created_at").first(),
        "consent_suggestions": karte.consent_suggestions(),
    }
    return render(request, "karte/karte_detail.html", context)


@stylist_required
def karte_edit(request, pk: int):
    karte = get_object_or_404(Karte, pk=pk, stylist=request.stylist)
    form = KarteForm(request.POST or None, instance=karte)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "カルテを保存しました")
        return redirect("karte:detail", pk=pk)
    menu_names = list(dict.fromkeys(request.stylist.menus.filter(is_active=True).values_list("name", flat=True)))[:30]
    return render(request, "karte/karte_form.html", {"form": form, "karte": karte, "menu_names": menu_names})


@stylist_required
@require_POST
def karte_regenerate(request, pk: int):
    karte = get_object_or_404(Karte, pk=pk, stylist=request.stylist)
    from apps.drafts.services import generate_visit_drafts

    try:
        generate_visit_drafts(karte, replace_existing=True)
        messages.success(request, "LINE文面を作り直しました")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"作り直しに失敗しました: {exc}")
    return redirect("karte:detail", pk=pk)


@stylist_required
@require_POST
def karte_delete(request, pk: int):
    karte = get_object_or_404(Karte, pk=pk, stylist=request.stylist)
    customer_id = karte.customer_id
    if karte.memo_id:
        karte.memo.delete()
    karte.delete()
    messages.success(request, "カルテを削除しました")
    return redirect("customers:detail", pk=customer_id)


@stylist_required
@require_POST
def photo_add(request, pk: int):
    karte = get_object_or_404(Karte, pk=pk, stylist=request.stylist)
    files = request.FILES.getlist("image")
    if not files:
        messages.error(request, "写真を選んでください")
        return redirect("karte:detail", pk=pk)
    sns_ok = request.POST.get("sns_ok") in ("on", "1", "true")
    face_visible = request.POST.get("face_visible") in ("on", "1", "true")
    for f in files[:10]:
        form = KartePhotoForm({"sns_ok": sns_ok, "face_visible": face_visible, "role": request.POST.get("role") if request.POST.get("role") in ("before", "after") else "after", "caption": request.POST.get("caption", "")}, {"image": f})
        if form.is_valid():
            photo = form.save(commit=False)
            photo.karte = karte
            photo.save()
        else:
            messages.error(request, "画像ファイルとして読み込めないものがありました")
    messages.success(request, "写真を追加しました")
    return redirect("karte:detail", pk=pk)


@stylist_required
@require_POST
def photo_update(request, pk: int):
    photo = get_object_or_404(KartePhoto, pk=pk, karte__stylist=request.stylist)
    if "sns_ok" in request.POST:
        photo.sns_ok = request.POST["sns_ok"] in ("1", "true", "on")
    if "face_visible" in request.POST:
        photo.face_visible = request.POST["face_visible"] in ("1", "true", "on")
    if request.POST.get("role") in ("before", "after"):
        photo.role = request.POST["role"]
    photo.save()
    if _is_fetch(request):
        return JsonResponse({"ok": True, "usable": photo.usable_for_sns(), "reason": photo.blocked_reason()})
    return redirect("karte:detail", pk=photo.karte_id)


@stylist_required
@require_POST
def photo_delete(request, pk: int):
    photo = get_object_or_404(KartePhoto, pk=pk, karte__stylist=request.stylist)
    karte_id = photo.karte_id
    photo.image.delete(save=False)
    photo.delete()
    return redirect("karte:detail", pk=karte_id)
