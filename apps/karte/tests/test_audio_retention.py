from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.dates import today_local
from apps.karte.models import VoiceMemo
from apps.karte.services import process_voice_memo


def _memo_with_audio(stylist, customer):
    return VoiceMemo.objects.create(
        stylist=stylist, customer=customer, visited_on=today_local(), audio=SimpleUploadedFile("memo.webm", b"\x00" * 4000, content_type="audio/webm")
    )


def test_audio_deleted_after_transcription_when_enabled(stylist, customer, settings):
    settings.DELETE_AUDIO_AFTER_TRANSCRIPTION = True
    memo = _memo_with_audio(stylist, customer)
    with mock.patch("apps.karte.services.get_transcriber") as gt:
        gt.return_value.transcribe.return_value = "ブラウンにカラー。次回は6週間後"
        process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.DONE
    assert not memo.audio
    assert memo.transcript.startswith("ブラウン")


def test_audio_kept_when_disabled(stylist, customer, settings):
    settings.DELETE_AUDIO_AFTER_TRANSCRIPTION = False
    memo = _memo_with_audio(stylist, customer)
    with mock.patch("apps.karte.services.get_transcriber") as gt:
        gt.return_value.transcribe.return_value = "カットのみ"
        process_voice_memo(memo.id)
    memo.refresh_from_db()
    assert memo.status == VoiceMemo.Status.DONE
    assert memo.audio and memo.audio.name.endswith(".webm")
