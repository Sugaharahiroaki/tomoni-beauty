"""文面生成・送信可否・SNS投稿生成（個人情報の絞り込みとチェックを含む）。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai import pii as pii_module
from apps.ai import services as ai_services
from apps.ai.claude_client import AIError
from apps.core.dates import compute_follow_up_date, today_local
from apps.visits.models import FollowUp
from apps.visits.services import has_upcoming_reservation, schedule_follow_up

from .models import Draft, SnsPost

logger = logging.getLogger(__name__)

NAME_PLACEHOLDER = "{お名前}"
LINK_PLACEHOLDER = "{予約リンク}"


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------
def style_for(stylist) -> dict:
    profile = getattr(stylist, "profile", None)
    return profile.as_style_dict() if profile else {}


def area_tags_for(stylist) -> list[str]:
    profile = getattr(stylist, "profile", None)
    return profile.area_tag_list() if profile else []


def fill_placeholders(text: str, customer, link_url: str | None) -> str:
    text = (text or "").replace(NAME_PLACEHOLDER, customer.display_call_name if customer else "")
    if link_url:
        text = text.replace(LINK_PLACEHOLDER, link_url)
    else:
        # リンクが無い場合はプレースホルダー行を落とす
        lines = [ln for ln in text.splitlines() if LINK_PLACEHOLDER not in ln]
        text = "\n".join(lines)
    return text.strip()


def create_tracked_link(stylist, customer, kind: str):
    if not stylist.hotpepper_url:
        return None
    from apps.lineapp.models import TrackedLink

    return TrackedLink.objects.create(stylist=stylist, customer=customer, target_url=stylist.hotpepper_url, kind=kind)


# ---------------------------------------------------------------------------
# 送信可否ルール（テスト対象）
# ---------------------------------------------------------------------------
def can_send_to_customer(customer, kind: str, now=None, min_days: int | None = None) -> tuple[bool, str]:
    """連絡NG・ブロック・短期間の連続送信・予約済みへの次回案内 を防ぐ。"""
    from apps.lineapp.models import Message

    if not customer.can_contact:
        return False, customer.contact_blocked_reason
    now = now or timezone.now()
    days = settings.MIN_DAYS_BETWEEN_SAME_KIND_MESSAGES if min_days is None else min_days
    if kind in (Draft.Kind.THANKS_CARE, Draft.Kind.NEXT_VISIT):
        recent = Message.objects.filter(customer=customer, kind=kind, status=Message.Status.SENT, sent_at__gte=now - timedelta(days=days)).exists()
        if recent:
            return False, f"同じ種類の案内を{days}日以内に送っています"
    if kind == Draft.Kind.NEXT_VISIT and has_upcoming_reservation(customer, timezone.localtime(now).date()):
        return False, "すでに次回の予約が入っています"
    return True, ""


# ---------------------------------------------------------------------------
# 来店後の文面（お礼＋お手入れ / 次回案内）
# ---------------------------------------------------------------------------
@transaction.atomic
def generate_visit_drafts(karte, replace_existing: bool = False) -> list[Draft]:
    stylist = karte.stylist
    customer = karte.customer
    existing = Draft.objects.filter(karte=karte, kind__in=[Draft.Kind.THANKS_CARE, Draft.Kind.NEXT_VISIT]).exclude(status=Draft.Status.DISCARDED)
    if existing.exists() and not replace_existing:
        return list(existing)
    existing.filter(status__in=[Draft.Status.DRAFT, Draft.Status.APPROVED]).update(status=Draft.Status.DISCARDED)

    data = ai_services.generate_line_drafts(
        karte.as_prompt_dict(), style_for(stylist), stylist.has_hotpepper, karte.next_visit_weeks, karte.visited_on, stylist.menu_prompt_text()
    )

    drafts = []
    thanks_link = create_tracked_link(stylist, customer, Draft.Kind.THANKS_CARE)
    thanks_body = fill_placeholders(data.get("thanks_care", ""), customer, thanks_link.url if thanks_link else None)
    drafts.append(
        Draft.objects.create(
            stylist=stylist, customer=customer, karte=karte, kind=Draft.Kind.THANKS_CARE, body=thanks_body, generated_body=thanks_body, tracked_link=thanks_link
        )
    )

    due = compute_follow_up_date(karte.visited_on, karte.next_visit_weeks, stylist.default_cycle_weeks, stylist.follow_up_lead_days)
    next_link = create_tracked_link(stylist, customer, Draft.Kind.NEXT_VISIT)
    next_body = fill_placeholders(data.get("next_visit", ""), customer, next_link.url if next_link else None)
    next_draft = Draft.objects.create(
        stylist=stylist, customer=customer, karte=karte, kind=Draft.Kind.NEXT_VISIT, body=next_body, generated_body=next_body, scheduled_for=due, tracked_link=next_link
    )
    drafts.append(next_draft)

    follow_up = schedule_follow_up(stylist, customer, karte, due)
    follow_up.draft = next_draft
    follow_up.status = FollowUp.Status.DRAFT_READY
    follow_up.save(update_fields=["draft", "status", "updated_at"])
    return drafts


def prepare_follow_up_draft(follow_up: FollowUp, today: date | None = None) -> tuple[Draft | None, str]:
    """フォロー予定に対して送れる下書きを用意する。送るべきでない場合は見送りにして理由を返す。"""
    today = today or today_local()
    customer = follow_up.customer
    ok, reason = can_send_to_customer(customer, Draft.Kind.NEXT_VISIT)
    if not ok:
        follow_up.status = FollowUp.Status.SKIPPED
        follow_up.skip_reason = reason[:100]
        follow_up.completed_at = timezone.now()
        follow_up.save(update_fields=["status", "skip_reason", "completed_at", "updated_at"])
        return None, reason

    draft = follow_up.draft
    if draft and draft.is_sendable_status:
        if follow_up.status != FollowUp.Status.DRAFT_READY:
            follow_up.status = FollowUp.Status.DRAFT_READY
            follow_up.save(update_fields=["status", "updated_at"])
        return draft, ""

    karte = follow_up.karte
    if karte is None:
        karte = customer.kartes.order_by("-visited_on").first()
    if karte is None:
        return None, "カルテが無いため文面を作れません"

    stylist = follow_up.stylist
    data = ai_services.generate_line_drafts(karte.as_prompt_dict(), style_for(stylist), stylist.has_hotpepper, karte.next_visit_weeks, karte.visited_on, stylist.menu_prompt_text())
    link = create_tracked_link(stylist, customer, Draft.Kind.NEXT_VISIT)
    body = fill_placeholders(data.get("next_visit", ""), customer, link.url if link else None)
    draft = Draft.objects.create(
        stylist=stylist, customer=customer, karte=karte, kind=Draft.Kind.NEXT_VISIT, body=body, generated_body=body, scheduled_for=follow_up.due_date, tracked_link=link
    )
    follow_up.draft = draft
    follow_up.status = FollowUp.Status.DRAFT_READY
    follow_up.save(update_fields=["draft", "status", "updated_at"])
    return draft, ""


def prepare_due_follow_ups(stylist, today: date | None = None) -> tuple[int, int]:
    today = today or today_local()
    prepared = skipped = 0
    qs = FollowUp.objects.filter(stylist=stylist, status__in=[FollowUp.Status.PENDING, FollowUp.Status.DRAFT_READY], due_date__lte=today).select_related("customer", "karte", "draft")
    for fu in qs:
        try:
            draft, _ = prepare_follow_up_draft(fu, today=today)
        except AIError as exc:
            logger.warning("follow-up %s draft generation failed: %s", fu.id, exc)
            continue
        if draft is None:
            skipped += 1
        else:
            prepared += 1
    return prepared, skipped


# ---------------------------------------------------------------------------
# 送信記録
# ---------------------------------------------------------------------------
@transaction.atomic
def mark_draft_sent(draft: Draft, route: str, body: str | None = None):
    from apps.lineapp.models import Message

    now = timezone.now()
    if body is not None and body.strip():
        draft.body = body.strip()
    message = Message.objects.create(
        stylist=draft.stylist,
        customer=draft.customer,
        draft=draft,
        kind=draft.kind,
        route=route,
        body=draft.body,
        status=Message.Status.SENT,
        sent_at=now,
        tracked_link=draft.tracked_link,
    )
    draft.status = Draft.Status.SENT
    draft.sent_at = now
    draft.save(update_fields=["body", "status", "sent_at", "updated_at"])
    FollowUp.objects.filter(draft=draft).update(status=FollowUp.Status.SENT, completed_at=now)
    if draft.inbound_message_id:
        inbound = draft.inbound_message
        inbound.replied_at = now
        inbound.reply_route = route
        inbound.save(update_fields=["replied_at", "reply_route"])
    return message


# ---------------------------------------------------------------------------
# SNS 投稿
# ---------------------------------------------------------------------------
def forbidden_terms_for(customer) -> set[str]:
    if customer is None:
        return set()
    return pii_module.name_variants(customer.name, customer.kana, customer.call_name, customer.line_display_name)


def build_sns_inputs(post: SnsPost) -> dict:
    """カルテから投稿用に渡す情報を明示的に絞り込む。

    ここを通らない情報（顧客名・private_notes・customer_requests・メモ）はSNS生成に渡らない。
    """
    karte = post.karte
    customer = post.customer
    safe = karte.sns_safe_fields() if karte else {"concerns": [], "results": "", "treatment_summary": "", "design_details": "", "menu_items": []}
    story_allowed = bool(post.uses_story and customer and customer.story_ok and (safe["concerns"] or safe["results"]))

    generalized = None
    if story_allowed:
        generalized = ai_services.generalize_story(safe["concerns"], safe["results"], safe["treatment_summary"])
        # 一般化結果にも名前が残っていないか確認
        terms = forbidden_terms_for(customer)
        for key in ("concern", "result"):
            hits = pii_module.find_forbidden_terms(generalized.get(key, ""), terms)
            if hits:
                for h in hits:
                    generalized[key] = generalized[key].replace(h, "お客様")
        post.generalized_story = generalized
        post.save(update_fields=["generalized_story", "updated_at"])

    return {
        "purpose": post.purpose,
        "story_allowed": story_allowed,
        "generalized": generalized,
        "treatment_summary": safe["treatment_summary"],
        "design_details": safe["design_details"],
        "episode": post.episode.as_prompt_dict() if post.episode else None,
        "style": style_for(post.stylist),
        "photo_count": post.photos.count(),
        "area_tags": area_tags_for(post.stylist),
        "extra_notes": post.extra_notes,
    }


def run_pii_checks(post: SnsPost, result: dict, use_llm: bool = True) -> dict:
    terms = forbidden_terms_for(post.customer)
    findings = []
    for field in ("feed_text", "story_text", "reel_script"):
        r = pii_module.check_text(result.get(field, ""), terms)
        for f in r.findings:
            findings.append({"kind": f.kind, "text": f.text, "severity": f.severity, "field": field})
    hashtags_text = " ".join(result.get("hashtags", []))
    for h in pii_module.find_forbidden_terms(hashtags_text, terms):
        findings.append({"kind": "customer_name", "text": h, "severity": "error", "field": "hashtags"})

    llm = None
    if use_llm:
        try:
            llm = ai_services.llm_pii_check("\n\n".join([result.get("feed_text", ""), result.get("story_text", ""), result.get("reel_script", "")]))
            for f in llm.get("findings", []):
                findings.append({"kind": "llm", "text": f.get("text", ""), "severity": "error" if llm.get("has_pii") else "warning", "field": "feed_text", "reason": f.get("reason", "")})
        except AIError as exc:
            logger.warning("llm pii check failed: %s", exc)
            findings.append({"kind": "check_failed", "text": "", "severity": "warning", "field": "", "reason": str(exc)})

    passed = not any(f["severity"] == "error" for f in findings)
    return {"passed": passed, "findings": findings, "llm_checked": llm is not None}


def generate_sns_post(post_id: int) -> None:
    post = SnsPost.objects.select_related("stylist", "customer", "karte", "episode").get(pk=post_id)
    try:
        inputs = build_sns_inputs(post)
        result = ai_services.generate_sns(**inputs)
        post.feed_text = (result.get("feed_text") or "").strip()
        post.story_text = (result.get("story_text") or "").strip()
        post.reel_script = (result.get("reel_script") or "").strip()
        tags = []
        for t in result.get("hashtags", []):
            t = str(t).strip().replace("＃", "#")
            if not t:
                continue
            tags.append(t if t.startswith("#") else f"#{t}")
        post.hashtags = tags[:20]
        post.pii_check = run_pii_checks(post, {"feed_text": post.feed_text, "story_text": post.story_text, "reel_script": post.reel_script, "hashtags": post.hashtags})
        post.status = SnsPost.Status.DRAFT
        post.error = ""
        post.save()
        if post.episode_id:
            from apps.profiles.models import EpisodeUsage

            EpisodeUsage.objects.get_or_create(episode=post.episode, sns_post=post)
    except AIError as exc:
        post.status = SnsPost.Status.FAILED
        post.error = str(exc)
        post.save(update_fields=["status", "error", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("sns post %s failed", post_id)
        post.status = SnsPost.Status.FAILED
        post.error = "予期しないエラーが発生しました"
        post.save(update_fields=["status", "error", "updated_at"])


def recheck_pii(post: SnsPost, use_llm: bool = False) -> dict:
    post.pii_check = run_pii_checks(post, {"feed_text": post.feed_text, "story_text": post.story_text, "reel_script": post.reel_script, "hashtags": post.hashtags}, use_llm=use_llm)
    post.save(update_fields=["pii_check", "updated_at"])
    return post.pii_check


def episode_keywords_for(karte) -> list[str]:
    if karte is None:
        return []
    safe = karte.sns_safe_fields()
    return [*safe["menu_items"], *safe["concerns"], safe["treatment_summary"]]
