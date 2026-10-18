"""アップロードされた写真・動画の下ごしらえ（HEIC→JPEG、撮影日時、動画の良い2秒、静止画）。"""

import io
import json
import subprocess
from datetime import datetime
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from .engine.audio import FFMPEG, FFPROBE

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # HEIC を使わない環境
    pass

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}
VIDEO_EXTS = {"mp4", "mov", "m4v", "webm", "3gp"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CLIP_SEC = 2.0


class MediaError(ValueError):
    pass


def kind_of(filename, content_type):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in VIDEO_EXTS or (content_type or "").startswith("video/"):
        return "video"
    if ext in IMAGE_EXTS or (content_type or "").startswith("image/"):
        return "photo"
    raise MediaError("写真（JPEG・PNG・HEIC）か動画（MP4・MOV）を選んでください。")


def prepare_photo(upload):
    """写真を向きを直した JPEG にし、(ファイル, 幅, 高さ, 撮影日時) を返す"""
    try:
        image = Image.open(upload)
        exif = image.getexif()
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise MediaError("写真を読み込めませんでした。別の写真で試してください。") from e
    taken = None
    raw = exif.get(36867) or exif.get(306)
    if raw:
        try:
            taken = timezone.make_aware(datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S"))
        except ValueError:
            taken = None
    if max(image.size) > 2400:
        image.thumbnail((2400, 2400))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    name = Path(getattr(upload, "name", "photo") or "photo").stem + ".jpg"
    return ContentFile(buf.getvalue(), name=name), image.width, image.height, taken


def to_mp4(path):
    src = Path(path)
    out = src.with_name(src.stem + "_mp4.mp4")
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.exists():
        raise MediaError("動画を読み込めませんでした。もう一度撮ってください。")
    return out


def probe_video(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise MediaError("動画を読み込めませんでした。別の動画で試してください。")
    info = json.loads(r.stdout)
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise MediaError("動画を読み込めませんでした。")
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    rotation = abs(int(stream.get("tags", {}).get("rotate", 0) or 0))
    for side in stream.get("side_data_list", []):
        rotation = abs(int(side.get("rotation", rotation) or 0))
    if rotation in (90, 270):
        width, height = height, width
    duration = float(info.get("format", {}).get("duration") or stream.get("duration") or 0)
    created = info.get("format", {}).get("tags", {}).get("creation_time")
    taken = None
    if created:
        try:
            taken = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            taken = None
    return width, height, duration, taken


def video_frames(path, fps=4, width=160):
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={width}:-2,format=gray", "-f", "image2pipe", "-vcodec", "pgm", "-"], capture_output=True)
    data, frames = r.stdout, []
    while data:
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception:  # noqa: BLE001
            break
        frames.append(image.copy())
        header_end = data.find(b"\n", data.find(b"\n", data.find(b"\n") + 1) + 1) + 1
        data = data[header_end + image.width * image.height :]
    return frames


def best_start(path, duration, clip=CLIP_SEC, fps=4):
    """ピントの鋭さと、ほどよい動きがある2秒の区間の開始位置を選ぶ"""
    if not duration or duration <= clip + 0.3:
        return 0.0
    frames = video_frames(path, fps=fps)
    if len(frames) < 3:
        return max((duration - clip) / 2, 0)
    sharp = [ImageStat.Stat(f.filter(ImageFilter.FIND_EDGES)).mean[0] for f in frames]
    motion = [0.0] + [ImageStat.Stat(ImageChops.difference(a, b)).mean[0] for a, b in zip(frames, frames[1:])]
    s_max, m_max = max(sharp) or 1, max(motion) or 1
    window = max(int(clip * fps), 1)
    best, best_score = 0, -1.0
    for i in range(0, len(frames) - window + 1):
        s = sum(sharp[i : i + window]) / window / s_max
        m = sum(motion[i : i + window]) / window / m_max
        shake = max(motion[i : i + window]) / m_max
        score = s * 0.6 + m * 0.4 - max(shake - 0.85, 0)
        if score > best_score:
            best, best_score = i, score
    return round(min(best / fps, duration - clip), 2)


def poster_frame(path, at):
    r = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{max(at, 0):.2f}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True)
    return r.stdout or None
