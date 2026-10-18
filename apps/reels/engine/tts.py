"""Gemini TTS でナレーションを1セリフずつ作る。同じ文章・声・指示なら作った音声を使い回す（cache_dir）。"""

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .audio import trim_and_normalize

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

VOICES = [
    {"name": "Sulafat", "gender": "女性", "feature": "あたたかい・落ち着いた"},
    {"name": "Vindemiatrix", "gender": "女性", "feature": "やさしい"},
    {"name": "Achernar", "gender": "女性", "feature": "やわらかい"},
    {"name": "Schedar", "gender": "男性", "feature": "落ち着いた・親しみやすい"},
    {"name": "Umbriel", "gender": "男性", "feature": "やさしく語りかける"},
    {"name": "Algieba", "gender": "男性", "feature": "低く落ち着いた"},
    {"name": "Achird", "gender": "男性", "feature": "はっきり・明るめ"},
]


class TTSError(RuntimeError):
    pass


class GeminiTTS:
    def __init__(self, api_key, model, voice, style, hook, lufs, cache_dir):
        if not api_key:
            raise TTSError("GEMINI_API_KEY が設定されていません")
        self.key = api_key
        self.model = model
        self.voice = voice
        self.style = style.strip()
        self.hook = hook.strip()
        self.lufs = lufs
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.audio_seconds = 0.0

    def prompt(self, text, hook, speaker=None):
        notes = "\n\n".join(n for n in (self.style, speaker, self.hook if hook else None) if n)
        return f"### DIRECTOR'S NOTES\n{notes}\n\n#### TRANSCRIPT\n{text}"

    def synthesize(self, text, hook=False, speaker=None):
        prompt = self.prompt(text, hook, speaker)
        digest = hashlib.sha1(f"{self.model}|{self.voice}|{self.lufs}|{prompt}".encode()).hexdigest()[:16]
        out = self.cache / f"{digest}.wav"
        if out.exists():
            return out, True
        pcm, rate = self._request(prompt)
        raw = self.cache / f"{digest}.raw.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        self.audio_seconds += len(pcm) / 2 / rate
        trim_and_normalize(raw, out, self.lufs)
        raw.unlink()
        return out, False

    def _request(self, prompt, retries=3):
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}}},
            }
        ).encode()
        req = urllib.request.Request(API.format(model=self.model), data=body, method="POST", headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        for attempt in range(retries):
            try:
                data = json.load(urllib.request.urlopen(req, timeout=120))
                part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
                rate = int(re.search(r"rate=(\d+)", part["mimeType"]).group(1))
                return base64.b64decode(part["data"]), rate
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise TTSError(f"Gemini TTS エラー {e.code}: {detail}")
            except (KeyError, IndexError) as e:
                if attempt < retries - 1:
                    time.sleep(3)
                    continue
                raise TTSError(f"Gemini TTS の応答に音声がありません: {e}")
