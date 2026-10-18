"""テロップの置き場所を決める（顔・髪・被写体と重ならない帯を選ぶ）。

PIL だけで動く簡易版：9:16 に切り抜いた画面を「上・中央・下」の3つの帯に分け、
細かい模様の多さ（輪郭の量）と肌色の割合が少ない帯にテロップを置く。
Instagram のリール画面で UI が重なる上端（ヘッダー）と下端（キャプション・ボタン）は候補から外す。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

W, H = 1080, 1920
BAND = 0.14  # テロップの高さのめやす（画面の高さに対する割合）
CANDIDATES = {"top": 0.22, "middle": 0.50, "bottom": 0.70}  # 画面の高さに対する中心位置
POSITIONS = ["auto", "top", "middle", "bottom"]
POSITION_LABELS = {"auto": "自動（顔や髪を避ける）", "top": "上", "middle": "中央", "bottom": "下"}
SKIN_WEIGHT = 1.5  # 肌色（顔）は強く避ける
KEEP_MARGIN = 0.05  # 好みの位置が最良と大差なければ、好みの位置のままにする


def cover_crop(image: Image.Image, fx: float = 0.5, fy: float = 0.5, tight: float = 1.0) -> Image.Image:
    """動画の最初の画面と同じ切り抜き（engine.render.cover と同じ考え方。寸法は解析用に小さく）"""
    w, h = image.size
    tw, th = 270, 480
    scale = max(tw / w, th / h) * max(tight, 1.0)
    nw, nh = max(int(w * scale), tw), max(int(h * scale), th)
    resized = image.resize((nw, nh))
    left = int((nw - tw) * min(max(fx, 0.0), 1.0))
    top = int((nh - th) * min(max(fy, 0.0), 1.0))
    return resized.crop((left, top, left + tw, top + th))


def _skin_fraction(band: Image.Image) -> float:
    ycc = band.convert("YCbCr")
    _, cb, cr = ycc.split()
    cbs, crs = cb.tobytes(), cr.tobytes()
    hits = sum(1 for b, r in zip(cbs, crs) if 77 <= b <= 127 and 133 <= r <= 173)
    return hits / max(len(cbs), 1)


def band_scores(image: Image.Image) -> dict[str, float]:
    """候補ごとの「邪魔さ」。小さいほどテロップを置きやすい"""
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    h = image.size[1]
    scores = {}
    for name, y in CANDIDATES.items():
        top = int(max(y - BAND / 2, 0) * h)
        bottom = int(min(y + BAND / 2, 1) * h)
        box = (0, top, image.size[0], bottom)
        edge = ImageStat.Stat(edges.crop(box)).mean[0] / 255
        skin = _skin_fraction(image.crop(box))
        scores[name] = round(edge + SKIN_WEIGHT * skin, 4)
    return scores


def choose_position(scores: dict[str, float], prefer: str = "top") -> str:
    best = min(scores, key=lambda k: (scores[k], list(CANDIDATES).index(k)))
    if prefer in scores and scores[prefer] <= scores[best] + KEEP_MARGIN:
        return prefer
    return best


def caption_position(path: str | Path, fx: float = 0.5, fy: float = 0.5, tight: float = 1.0, prefer: str = "top") -> tuple[str, float]:
    """写真（動画はポスター画像）から、テロップを置く帯とその中心位置（0〜1）を返す。読めなければ好みの位置"""
    try:
        with Image.open(path) as im:
            cropped = cover_crop(im.convert("RGB"), fx, fy, tight)
    except (OSError, ValueError):
        return prefer, CANDIDATES.get(prefer, CANDIDATES["top"])
    name = choose_position(band_scores(cropped), prefer)
    return name, CANDIDATES[name]
