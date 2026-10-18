"""インタビュー → エピソード生成、エピソード選択ロジック。"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.ai import services as ai_services
from apps.ai.transcription import TranscriptionError, get_transcriber

from .models import Episode, EpisodeUsage, InterviewAnswer, StylistProfile

logger = logging.getLogger(__name__)


def get_or_create_profile(stylist) -> StylistProfile:
    profile, _ = StylistProfile.objects.get_or_create(stylist=stylist)
    return profile


def transcribe_answer(answer_id: int) -> None:
    answer = InterviewAnswer.objects.select_related("question").get(pk=answer_id)
    if not answer.audio:
        answer.status = InterviewAnswer.Status.DONE
        answer.save(update_fields=["status", "updated_at"])
        return
    answer.status = InterviewAnswer.Status.TRANSCRIBING
    answer.save(update_fields=["status", "updated_at"])
    try:
        with answer.audio.open("rb") as f:
            data = f.read()
        text = get_transcriber().transcribe(data, answer.audio.name, fallback_text=answer.transcript)
        answer.transcript = text
        answer.status = InterviewAnswer.Status.DONE
        answer.error = ""
    except TranscriptionError as exc:
        answer.status = InterviewAnswer.Status.FAILED
        answer.error = str(exc)
    answer.save(update_fields=["transcript", "status", "error", "updated_at"])


def build_episodes_from_interview(stylist) -> int:
    """回答済みの質問から人柄エピソードを生成。既存のAI生成エピソードは残し、追記する。"""
    answers = (
        InterviewAnswer.objects.filter(stylist=stylist, status=InterviewAnswer.Status.DONE)
        .exclude(transcript="")
        .select_related("question")
        .order_by("question__order")
    )
    qa_pairs = [{"order": a.question.order, "question": a.question.text, "answer": a.transcript} for a in answers]
    if not qa_pairs:
        return 0
    result = ai_services.build_episodes(qa_pairs, stylist.display_name)
    answer_by_order = {a.question.order: a for a in answers}

    created = 0
    with transaction.atomic():
        for ep in result.get("episodes", []):
            title = (ep.get("title") or "").strip()[:100]
            body = (ep.get("body") or "").strip()
            if not title or not body:
                continue
            Episode.objects.create(
                stylist=stylist,
                title=title,
                body=body,
                themes=[t for t in ep.get("themes", []) if isinstance(t, str)][:8],
                source=Episode.Source.AI,
                source_answer=answer_by_order.get(ep.get("question_order")),
            )
            created += 1
        profile = get_or_create_profile(stylist)
        if result.get("style_summary") and not profile.style_summary:
            profile.style_summary = result["style_summary"]
        if result.get("suggested_first_person") and profile.first_person == "私":
            profile.first_person = result["suggested_first_person"][:10]
        profile.save()
        if created:
            stylist.interview_completed = True
            stylist.save(update_fields=["interview_completed", "updated_at"])
    return created


def _theme_score(episode_themes: list[str], keywords: list[str]) -> int:
    score = 0
    for theme in episode_themes or []:
        for kw in keywords:
            if not kw:
                continue
            if theme == kw or theme in kw or kw in theme:
                score += 2
    return score


def select_episode(stylist, keywords: list[str], purpose: str = "general", exclude_days: int = 14) -> Episode | None:
    """今日の施術と相性の良いエピソードを1つ選ぶ。

    - テーマ一致でスコア加点
    - 目的（purpose）に合うテーマ（初めての方 / 価値観 など）を加点
    - 直近 exclude_days 日に使ったものは減点（同じ話の連続を避ける）
    - 使用回数が少ないものを優先
    """
    episodes = list(Episode.objects.filter(stylist=stylist, is_active=True))
    if not episodes:
        return None
    since = timezone.now() - timedelta(days=exclude_days)
    recent_ids = set(EpisodeUsage.objects.filter(episode__stylist=stylist, used_at__gte=since).values_list("episode_id", flat=True))
    usage_counts = {e.id: e.usages.count() for e in episodes}

    purpose_themes = {
        "first_timer": ["初めての方", "カウンセリング", "接客", "安心"],
        "nomination": ["価値観", "きっかけ", "修業時代", "丁寧さ", "想い"],
        "weekday_daytime": ["休日", "働き方", "時間"],
        "repeat": ["ホームケア", "色落ち", "ダメージケア", "想い"],
    }.get(purpose, [])

    def score(e: Episode):
        s = _theme_score(e.themes, keywords) * 3 + _theme_score(e.themes, purpose_themes)
        if e.id in recent_ids:
            s -= 10
        s -= usage_counts.get(e.id, 0)
        return (s, e.created_at)

    return max(episodes, key=score)
