"""ナレーションの用意の仕方（AIの声 / 本人の録音）。render_reel に渡す。"""

import hashlib
from pathlib import Path

from .audio import trim_and_normalize


class TTSNarrator:
    """AIの声（Gemini TTS）"""

    def __init__(self, tts):
        self.tts = tts

    def synthesize(self, text, hook=False, speaker=None, index=0):
        return self.tts.synthesize(text, hook=hook, speaker=speaker)


class OwnVoiceNarrator:
    """本人が録音した声。録音がないセリフは、AIの声で補う（fallback が無ければ声なし）"""

    def __init__(self, takes, lufs, cache_dir, fallback=None):
        self.takes = {int(k): Path(v) for k, v in takes.items()}
        self.lufs = lufs
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.fallback = fallback

    def synthesize(self, text, hook=False, speaker=None, index=0):
        take = self.takes.get(index)
        if take and take.exists():
            digest = hashlib.sha1(f"{take}|{take.stat().st_mtime}|{self.lufs}".encode()).hexdigest()[:16]
            out = self.cache / f"take_{digest}.wav"
            if out.exists():
                return out, True
            trim_and_normalize(take, out, self.lufs)
            return out, False
        if self.fallback:
            return self.fallback.synthesize(text, hook=hook, speaker=speaker, index=index)
        raise FileNotFoundError(f"{index + 1}番目のセリフの録音がありません")


class SilentNarrator:
    """声なし（TTSキーが無く、録音も無いとき）。カットの長さは台本の既定値のまま"""

    def synthesize(self, text, hook=False, speaker=None, index=0):
        raise FileNotFoundError("ナレーション無し")
