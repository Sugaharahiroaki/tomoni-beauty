from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue
from apps.karte.models import Karte, KartePhoto
from apps.lineapp.models import Message
from apps.profiles.services import select_episode

from .forms import SnsPostForm
from .models import Draft, SnsPost
from .services import can_send_to_customer, episode_keywords_for, mark_draft_sent, recheck_pii


def _is_fetch(request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


# ---------------------------------------------------------------------------
# LINE 下書き
# ---------------------------------------------------------------------------
@stylist_required
def draft_list(request):
    qs = Draft.objects.filter(stylist=request.stylist).select_related("customer")
    pending = qs.filter(status__in=[Draft.Status.DRAFT, Draft.Status.APPROVED]).exclude(kind=Draft.Kind.REPLY).order_by("scheduled_for", "-created_at")
    sent = qs.filter(status=Draft.Status.SENT).order_by("-sent_at")[:30]
    return render(request, "drafts/draft_list.html", {"pending": pending, "sent": sent})


@stylist_required
def draft_detail(request, pk: int):
    draft = get_object_or_404(Draft.objects.select_related("customer", "karte", "inbound_message", "tracked_link"), pk=pk, stylist=request.stylist)
    customer = draft.customer
    channel = getattr(request.stylist, "line_channel", None)
    can_send, reason = (can_send_to_customer(customer, draft.kind) if customer else (False, "お客様が未設定です"))
    chat_url = channel.chat_url_for(customer) if (channel and customer) else None
    context = {
        "draft": draft,
        "customer": customer,
        "can_send": can_send and draft.is_sendable_status,
        "block_reason": reason if not can_send else ("すでに送信済みです" if draft.status == Draft.Status.SENT else ""),
        "chat_url": chat_url,
        "channel": channel,
        "push_quota": channel.quota_summary() if (channel and channel.push_enabled) else None,
    }
    return render(request, "drafts/draft_detail.html", context)


@stylist_required
@require_POST
def draft_update(request, pk: int):
    draft = get_object_or_404(Draft, pk=pk, stylist=request.stylist)
    body = (request.POST.get("body") or "").strip()
    if not body:
        return JsonResponse({"error": "本文が空です"}, status=400) if _is_fetch(request) else redirect("drafts:detail", pk=pk)
    if draft.is_sendable_status:
        draft.body = body
        draft.status = Draft.Status.APPROVED
        draft.save(update_fields=["body", "status", "updated_at"])
    if _is_fetch(request):
        return JsonResponse({"ok": True})
    messages.success(request, "保存しました")
    return redirect("drafts:detail", pk=pk)


@stylist_required
@require_POST
def draft_reset(request, pk: int):
    draft = get_object_or_404(Draft, pk=pk, stylist=request.stylist)
    if draft.generated_body and draft.is_sendable_status:
        draft.body = draft.generated_body
        draft.save(update_fields=["body", "updated_at"])
    return redirect("drafts:detail", pk=pk)


@stylist_required
@require_POST
def draft_mark_sent(request, pk: int):
    """コピー→LINEチャットで送った、を記録する（無料ルート）。"""
    draft = get_object_or_404(Draft.objects.select_related("customer"), pk=pk, stylist=request.stylist)
    if not draft.is_sendable_status:
        messages.info(request, "この下書きはすでに処理済みです")
        return redirect("drafts:detail", pk=pk)
    ok, reason = can_send_to_customer(draft.customer, draft.kind) if draft.customer else (False, "お客様が未設定です")
    if not ok:
        messages.error(request, f"送信を記録できません: {reason}")
        return redirect("drafts:detail", pk=pk)
    mark_draft_sent(draft, Message.Route.COPY, body=request.POST.get("body"))
    messages.success(request, "送信済みとして記録しました")
    if draft.inbound_message_id:
        return redirect("lineapp:inbox")
    return redirect(request.POST.get("next") or "core:today")


@stylist_required
@require_POST
def draft_discard(request, pk: int):
    draft = get_object_or_404(Draft, pk=pk, stylist=request.stylist)
    if draft.is_sendable_status:
        draft.status = Draft.Status.DISCARDED
        draft.save(update_fields=["status", "updated_at"])
        from apps.visits.models import FollowUp

        FollowUp.objects.filter(draft=draft, status=FollowUp.Status.DRAFT_READY).update(status=FollowUp.Status.PENDING, draft=None)
    messages.info(request, "下書きを破棄しました")
    return redirect(request.POST.get("next") or "core:today")


# ---------------------------------------------------------------------------
# SNS 投稿
# ---------------------------------------------------------------------------
@stylist_required
def sns_list(request):
    """旧「文章の投稿」一覧。SNS投稿は1つの流れにまとめたので、新しい画面へ"""
    return redirect("reels:home")


@stylist_required
def _sns_list_legacy(request):
    posts = SnsPost.objects.filter(stylist=request.stylist).exclude(status=SnsPost.Status.DISCARDED).select_related("customer", "karte")[:50]
    recent_kartes = Karte.objects.filter(stylist=request.stylist).select_related("customer")[:10]
    return render(request, "drafts/sns_list.html", {"posts": posts, "recent_kartes": recent_kartes})


@stylist_required
def sns_new(request):
    """旧「投稿文を作る」。新しい流れ（素材 → 型 → フック → 出来上がり）へ"""
    messages.info(request, "SNS投稿は「投稿をつくる」にまとめました。写真や動画を入れると、型と文章を提案します。")
    return redirect("reels:home")


@stylist_required
def _sns_new_legacy(request):
    karte = None
    if request.GET.get("karte"):
        karte = get_object_or_404(Karte.objects.select_related("customer"), pk=request.GET["karte"], stylist=request.stylist)
    form = SnsPostForm(request.POST or None, stylist=request.stylist, karte=karte)
    suggested = select_episode(request.stylist, episode_keywords_for(karte)) if karte else None

    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        episode = None
        if not cd.get("no_episode"):
            episode = cd.get("episode") or suggested
        post = SnsPost.objects.create(
            stylist=request.stylist,
            customer=karte.customer if karte else None,
            karte=karte,
            purpose=cd["purpose"],
            uses_story=bool(cd.get("uses_story")) and bool(karte and karte.customer.story_ok),
            episode=episode,
            extra_notes=cd.get("extra_notes", ""),
        )
        if karte:
            ids = [int(i) for i in cd.get("photos", [])]
            photos = [p for p in KartePhoto.objects.filter(pk__in=ids, karte=karte) if p.usable_for_sns()]
            post.photos.set(photos)
        enqueue("apps.drafts.tasks.generate_sns_post", post.id)
        return redirect("drafts:sns_detail", pk=post.pk)

    return render(request, "drafts/sns_form.html", {"form": form, "karte": karte, "suggested": suggested, "usable_photos": form.usable_photos})


@stylist_required
def sns_detail(request, pk: int):
    post = get_object_or_404(SnsPost.objects.select_related("customer", "karte", "episode").prefetch_related("photos"), pk=pk, stylist=request.stylist)
    return render(request, "drafts/sns_detail.html", {"post": post})


@stylist_required
def sns_status(request, pk: int):
    post = get_object_or_404(SnsPost, pk=pk, stylist=request.stylist)
    return JsonResponse({"status": post.status, "error": post.error, "done": not post.is_processing})


@stylist_required
@require_POST
def sns_update(request, pk: int):
    post = get_object_or_404(SnsPost, pk=pk, stylist=request.stylist)
    if post.status not in (SnsPost.Status.DRAFT, SnsPost.Status.POSTED):
        return redirect("drafts:sns_detail", pk=pk)
    post.feed_text = (request.POST.get("feed_text") or post.feed_text).strip()
    post.story_text = (request.POST.get("story_text") or post.story_text).strip()
    post.reel_script = (request.POST.get("reel_script") or post.reel_script).strip()
    raw_tags = request.POST.get("hashtags")
    if raw_tags is not None:
        post.hashtags = [t if t.startswith("#") else f"#{t}" for t in raw_tags.replace("＃", "#").split() if t.strip("#")]
    post.save()
    recheck_pii(post, use_llm=False)
    messages.success(request, "保存して個人情報チェックをやり直しました")
    return redirect("drafts:sns_detail", pk=pk)


@stylist_required
@require_POST
def sns_mark_posted(request, pk: int):
    post = get_object_or_404(SnsPost, pk=pk, stylist=request.stylist)
    if post.pii_errors and not request.POST.get("force"):
        messages.error(request, "個人情報の可能性がある箇所が残っています。修正してから投稿済みにしてください。")
        return redirect("drafts:sns_detail", pk=pk)
    post.status = SnsPost.Status.POSTED
    post.posted_at = timezone.now()
    post.save(update_fields=["status", "posted_at", "updated_at"])
    messages.success(request, "投稿済みとして記録しました")
    return redirect("drafts:sns_list")


@stylist_required
@require_POST
def sns_discard(request, pk: int):
    post = get_object_or_404(SnsPost, pk=pk, stylist=request.stylist)
    post.status = SnsPost.Status.DISCARDED
    post.save(update_fields=["status", "updated_at"])
    return redirect("drafts:sns_list")


@stylist_required
@require_POST
def sns_regenerate(request, pk: int):
    post = get_object_or_404(SnsPost, pk=pk, stylist=request.stylist)
    post.status = SnsPost.Status.GENERATING
    post.error = ""
    post.save(update_fields=["status", "error", "updated_at"])
    enqueue("apps.drafts.tasks.generate_sns_post", post.id)
    return redirect("drafts:sns_detail", pk=pk)
