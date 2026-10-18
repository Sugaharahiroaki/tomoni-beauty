"""音声まわりの共通処理（長さ・ラウドネスの測定、無音の除去と音量合わせ）"""

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")


def _ffmpeg(args):
    return subprocess.run([FFMPEG, "-hide_banner", "-nostats", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def ffmpeg_available() -> bool:
    try:
        return subprocess.run([FFMPEG, "-version"], capture_output=True).returncode == 0
    except OSError:
        return False


@lru_cache(maxsize=None)
def measure_lufs(path, start=0.0, length=None):
    """統合ラウドネス（LUFS）。測れない場合は None"""
    span = ["-ss", str(start)] + (["-t", str(length)] if length else [])
    r = _ffmpeg([*span, "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(found[-1]) if found else None


def duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def trim_and_normalize(src, dst, lufs):
    """前後の無音を削り、ラウドネスを lufs にそろえる"""
    trimmed = Path(dst).with_suffix(".trim.wav")
    trim = "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
    r = _ffmpeg(["-y", "-i", str(src), "-af", trim, str(trimmed)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    measured = measure_lufs(str(trimmed))
    gain = (lufs - measured) if measured is not None else 0.0
    r = _ffmpeg(["-y", "-i", str(trimmed), "-af", f"volume={gain:.2f}dB", str(dst)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    trimmed.unlink()
    return Path(dst)
