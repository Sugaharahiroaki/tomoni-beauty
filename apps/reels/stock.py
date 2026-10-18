"""ネットの素材（Pexels）を探して取り込む。`PEXELS_API_KEY` が無ければ使えない。

ストック素材は雰囲気の補助（道具・水・光・街並みなど）にだけ使う。
自分の施術・サロン・お客様として見せない（役割は「その他」か「施術中」まで。ビフォー／アフター／本人には使えない）。
Pexels のライセンスは商用利用可・クレジット不要（表示は推奨）。取り込んだ素材には撮影者とページを記録する。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.files import File

API = "https://api.pexels.com"
TIMEOUT = 20
ALLOWED_ROLES = ("other", "process")


class StockError(RuntimeError):
    pass


def available() -> bool:
    return bool(getattr(settings, "PEXELS_API_KEY", ""))


def _headers() -> dict:
    return {"Authorization": settings.PEXELS_API_KEY}


def search(query: str, kind: str = "video", per_page: int = 12) -> list[dict]:
    """縦向きの動画か写真を探し、画面で選びやすい形に整える"""
    if not available():
        raise StockError("ネットの素材を使うには PEXELS_API_KEY の設定が必要です。")
    query = (query or "").strip()
    if not query:
        return []
    try:
        if kind == "video":
            r = requests.get(f"{API}/videos/search", params={"query": query, "per_page": per_page, "orientation": "portrait"}, headers=_headers(), timeout=TIMEOUT)
            r.raise_for_status()
            return [item for item in (_video_item(v) for v in r.json().get("videos", [])) if item]
        r = requests.get(f"{API}/v1/search", params={"query": query, "per_page": per_page, "orientation": "portrait"}, headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return [_photo_item(p) for p in r.json().get("photos", [])]
    except requests.RequestException as exc:
        raise StockError(f"素材サイトに接続できませんでした（{exc}）") from exc


def _video_item(v: dict) -> dict | None:
    files = [f for f in v.get("video_files", []) if (f.get("file_type") or "").startswith("video/mp4") and f.get("width") and f.get("height")]
    if not files:
        return None
    best = min(files, key=lambda f: abs(min(f["width"], f["height"]) - 1080))
    return {"id": str(v.get("id")), "kind": "video", "thumb": v.get("image", ""), "url": best.get("link", ""), "duration": v.get("duration"), "credit": (v.get("user") or {}).get("name", ""), "page": v.get("url", "")}


def _photo_item(p: dict) -> dict:
    src = p.get("src") or {}
    return {"id": str(p.get("id")), "kind": "photo", "thumb": src.get("medium", ""), "url": src.get("large2x") or src.get("portrait") or src.get("original", ""), "duration": None, "credit": p.get("photographer", ""), "page": p.get("url", "")}


def add_to_post(post, item: dict, role: str = "other"):
    """素材をダウンロードして投稿に足す（役割は other / process のみ）"""
    from . import services

    if not available():
        raise StockError("ネットの素材を使うには PEXELS_API_KEY の設定が必要です。")
    if role not in ALLOWED_ROLES:
        role = "other"
    url = item.get("url") or ""
    if not url.startswith("https://"):
        raise StockError("素材のURLが正しくありません。")
    kind = "video" if item.get("kind") == "video" else "photo"
    suffix = ".mp4" if kind == "video" else ".jpg"
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    tmp.write(chunk)
                path = Path(tmp.name)
    except requests.RequestException as exc:
        raise StockError(f"素材をダウンロードできませんでした（{exc}）") from exc
    try:
        with path.open("rb") as f:
            asset = services.save_asset(post, File(f, name=f"stock_{item.get('id', 'x')}{suffix}"), path.name, "video/mp4" if kind == "video" else "image/jpeg", path.stat().st_size, kind, "", face_visible=False, role=role, source="stock")
    finally:
        path.unlink(missing_ok=True)
    asset.analysis = {**(asset.analysis or {}), "stock": "pexels", "credit": item.get("credit", ""), "page": item.get("page", "")}
    asset.save(update_fields=["analysis", "updated_at"])
    return asset
