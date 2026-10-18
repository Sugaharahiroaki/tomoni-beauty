"""音声メモ → 文字起こし → カルテ → 文面 のパイプライン。"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai import services as ai_services
from apps.ai.claude_client import AIError
from apps.ai.transcription import TranscriptionError, get_transcriber

from .models import Karte, VoiceMemo

logger = logging.getLogger(__name__)


def _set_status(memo: VoiceMemo, status: str, **fields):
    memo.status = status
    for k, v in fields.items():
        setattr(memo, k, v)
    memo.save(update_fields=["status", "updated_at", *fields.keys()])


def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def create_karte_from_extraction(memo: VoiceMemo, data: dict) -> Karte:
    weeks = data.get("next_visit_weeks")
    try:
        weeks = int(weeks) if weeks is not None else None
        if weeks is not None and not (1 <= weeks <= 52):
            weeks = None
    except (TypeError, ValueError):
        weeks = None
    return Karte.objects.create(
        stylist=memo.stylist,
        customer=memo.customer,
        visit=memo.visit,
        memo=memo,
        visited_on=memo.visited_on,
        treatment_summary=(data.get("treatment_summary") or "").strip(),
        menu_items=_as_list(data.get("menu_items")),
        design_details=(data.get("design_details") or "").strip(),
        concerns=_as_list(data.get("concerns")),
        results=(data.get("results") or "").strip(),
        products_used=_as_list(data.get("products_used")),
        home_care_advice=_as_list(data.get("home_care_advice")),
        next_check_items=_as_list(data.get("next_check_items")),
        next_visit_weeks=weeks,
        customer_requests=_as_list(data.get("customer_requests")),
        permission_mentions=data.get("permission_mentions") or {},
        private_notes=(data.get("private_notes") or "").strip(),
        raw_json=data,
    )


def process_voice_memo(memo_id: int) -> None:
    memo = VoiceMemo.objects.select_related("stylist", "customer").get(pk=memo_id)
    if memo.status == VoiceMemo.Status.DONE:
        return
    try:
        # 1. 文字起こし
        _set_status(memo, VoiceMemo.Status.TRANSCRIBING, error="")
        if memo.audio:
            with memo.audio.open("rb") as f:
                data = f.read()
            transcript = get_transcriber().transcribe(data, memo.audio.name, fallback_text=memo.text_input)
        else:
            transcript = memo.text_input
        transcript = (transcript or "").strip()
        if not transcript:
            raise TranscriptionError("音声を文字にできませんでした。静かな場所でもう一度録音するか、テキストで入力してください。")
        memo.transcript = transcript
        if memo.audio and settings.DELETE_AUDIO_AFTER_TRANSCRIPTION:
            # 文字起こしが取れたら音声は保持しない（個人情報の最小化）
            memo.audio.delete(save=False)
            memo.audio = None

        # 2. カルテ構造化
        _set_status(memo, VoiceMemo.Status.STRUCTURING, transcript=transcript, audio=memo.audio)
        karte = getattr(memo, "karte", None)
        if karte is None:
            extracted = ai_services.extract_karte(
                transcript, memo.stylist.display_name, memo.visited_on, memo.customer.context_for_ai(),
                list(memo.stylist.menus.filter(is_active=True).values_list("name", flat=True)[:40]),
            )
            with transaction.atomic():
                karte = create_karte_from_extraction(memo, extracted)

        # 3. LINE文面・フォロー予定
        _set_status(memo, VoiceMemo.Status.GENERATING)
        from apps.drafts.services import generate_visit_drafts

        generate_visit_drafts(karte)

        _set_status(memo, VoiceMemo.Status.DONE, processed_at=timezone.now())
    except (TranscriptionError, AIError) as exc:
        logger.warning("memo %s failed: %s", memo_id, exc)
        _set_status(memo, VoiceMemo.Status.FAILED, error=str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("memo %s failed unexpectedly", memo_id)
        _set_status(memo, VoiceMemo.Status.FAILED, error="予期しないエラーが発生しました。もう一度お試しください。")
