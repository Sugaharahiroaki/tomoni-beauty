from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ai.claude_client import AIError
from apps.ai.transcription import TranscriptionError
from apps.core.dates import today_local
from apps.drafts.models import Draft
from apps.karte.models import Karte, VoiceMemo
from apps.karte.services import process_voice_memo
from apps.visits.models import FollowUp


def test_text_memo_pipeline_creates_karte_drafts_follow_up(stylist, customer):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), text_input="ブラウンにカラー。色落ちが気になる。次回は6週間後。写真は掲載OK、顔出しNG")
    process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.DONE
    assert memo.transcript == memo.text_input
    karte = Karte.objects.get(memo=memo)
    assert karte.customer == customer and karte.menu_items == ["カラー"]
    assert karte.next_visit_weeks == 6
    assert karte.permission_mentions["photo_ok"] is True and karte.permission_mentions["face_ok"] is False
    assert Draft.objects.filter(karte=karte).count() == 2
    assert FollowUp.objects.filter(karte=karte, status=FollowUp.Status.DRAFT_READY).exists()


def test_consent_suggestions_only_show_differences(stylist, customer):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), text_input="写真は掲載OK、顔出しNG")
    process_voice_memo(memo.id)
    karte = Karte.objects.get(memo=memo)
    # customer: photo_ok=True, face_ok=False → どちらも一致しているので提案なし
    assert karte.consent_suggestions() == []
    customer.photo_ok = False
    customer.save()
    karte.refresh_from_db()
    suggestions = karte.consent_suggestions()
    assert len(suggestions) == 1 and suggestions[0]["field"] == "photo_ok" and suggestions[0]["value"] is True


def test_pipeline_marks_failed_on_transcription_error(stylist, customer):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), audio=SimpleUploadedFile("memo.webm", b"\x00" * 2000, content_type="audio/webm"))
    with mock.patch("apps.karte.services.get_transcriber") as gt:
        gt.return_value.transcribe.side_effect = TranscriptionError("聞き取れませんでした")
        process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.FAILED
    assert "聞き取れませんでした" in memo.error
    assert not Karte.objects.filter(memo=memo).exists()


def test_pipeline_marks_failed_on_ai_error(stylist, customer):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), text_input="テキスト")
    with mock.patch("apps.karte.services.ai_services.extract_karte", side_effect=AIError("混み合っています")):
        process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.FAILED and "混み合って" in memo.error


def test_empty_transcript_fails_gracefully(stylist, customer):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), text_input="")
    process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.FAILED


def test_memo_create_view_with_new_customer(client_logged, stylist):
    resp = client_logged.post(
        reverse("karte:memo_create"),
        {"new_customer_name": "鈴木 一郎", "text_input": "カットのみ。次回は1か月後", "visited_on": today_local().isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    data = resp.json()
    memo = VoiceMemo.objects.get(customer__name="鈴木 一郎", stylist=stylist)
    assert data["redirect"] == reverse("karte:memo_detail", kwargs={"pk": memo.pk})
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.DONE  # Q_SYNC=True で即処理


def test_memo_create_requires_customer_and_content(client_logged):
    resp = client_logged.post(reverse("karte:memo_create"), {"text_input": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400
    resp = client_logged.post(reverse("karte:memo_create"), {"new_customer_name": "A"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400


def test_memo_create_rejects_other_tenants_customer(client_logged, other_stylist):
    from apps.customers.models import Customer

    foreign = Customer.objects.create(stylist=other_stylist, name="他店")
    resp = client_logged.post(reverse("karte:memo_create"), {"customer_id": foreign.pk, "text_input": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400
    assert not VoiceMemo.objects.filter(customer=foreign).exists()
