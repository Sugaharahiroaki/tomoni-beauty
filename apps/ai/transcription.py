"""音声→文字起こし。OpenAI の音声認識API（Whisper系）を使う。キーが無ければダミー。"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# 美容室特有の語彙を認識しやすくするヒント（Whisper / gpt-4o-transcribe の prompt）
DOMAIN_PROMPT = (
    "美容室の施術後メモ。カット、カラー、ブリーチ、ハイライト、インナーカラー、パーマ、縮毛矯正、"
    "トリートメント、ヘッドスパ、色落ち、褪色、赤み、黄み、アッシュ、ベージュ、ブラウン、ショート、ボブ、"
    "レイヤー、前髪、根元、毛先、ダメージ、乾燥、くせ毛、ボリューム、次回、週間後、SNS掲載OK、顔出しNG。"
)

SUPPORTED_EXTENSIONS = {".webm", ".mp4", ".m4a", ".mp3", ".wav", ".mpeg", ".mpga", ".ogg"}


class TranscriptionError(Exception):
    pass


class BaseTranscriber:
    def transcribe(self, data: bytes, filename: str, fallback_text: str = "") -> str:  # pragma: no cover
        raise NotImplementedError


class FakeTranscriber(BaseTranscriber):
    SAMPLE = (
        "今日は落ち着いたブラウンにカラー。色落ちが早くて毎回すぐ明るくなるのが気になるとのこと。"
        "赤みが出にくいように少しマット寄りに調整。次回は6週間後くらいにリタッチの相談。"
        "ホームケアは紫シャンプーじゃなくてカラーシャンプーを週2回。写真はSNS掲載OK、顔出しはNG。"
    )

    def transcribe(self, data: bytes, filename: str, fallback_text: str = "") -> str:
        if fallback_text:
            return fallback_text
        return self.SAMPLE


class OpenAITranscriber(BaseTranscriber):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI

        self.model = model or settings.TRANSCRIPTION_MODEL
        self.client = OpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    def transcribe(self, data: bytes, filename: str, fallback_text: str = "") -> str:
        if not data:
            if fallback_text:
                return fallback_text
            raise TranscriptionError("音声データが空です")
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            filename = Path(filename).stem + ".webm"
        kwargs = {"model": self.model, "file": (filename, data), "prompt": DOMAIN_PROMPT}
        # gpt-transcribe 系は languages（配列）、それ以外は language（ISO 639-1）
        if self.model.startswith("gpt-transcribe"):
            kwargs["extra_body"] = {"languages": ["ja"]}
        else:
            kwargs["language"] = "ja"
        try:
            result = self.client.audio.transcriptions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - SDK例外を1つにまとめて上位で扱う
            logger.exception("transcription failed")
            raise TranscriptionError(str(exc)) from exc
        text = getattr(result, "text", None) or (result if isinstance(result, str) else "")
        return (text or "").strip()


_transcriber: BaseTranscriber | None = None


def get_transcriber() -> BaseTranscriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = FakeTranscriber() if settings.TRANSCRIPTION_FAKE else OpenAITranscriber()
    return _transcriber


def reset_transcriber():
    global _transcriber
    _transcriber = None
