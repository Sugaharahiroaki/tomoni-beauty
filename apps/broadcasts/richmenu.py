"""リッチメニュー画像の生成と LINE への公開。"""
from __future__ import annotations

import io
import logging
import os
from urllib.parse import parse_qs

from django.conf import settings
from django.utils import timezone

from apps.lineapp.client import LineApiError

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 2500, 843
BG = (250, 247, 242)
ACCENT = (184, 92, 74)
TEXT = (43, 38, 34)
LINE_GREEN = (6, 199, 85)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


def find_japanese_font() -> str | None:
    if settings.RICH_MENU_FONT_PATH and os.path.exists(settings.RICH_MENU_FONT_PATH):
        return settings.RICH_MENU_FONT_PATH
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def render_rich_menu_image(labels: list[str], sublabels: list[str] | None = None) -> bytes:
    """3分割のシンプルなメニュー画像（PNG）を生成する。"""
    from PIL import Image, ImageDraw, ImageFont

    sublabels = sublabels or ["ホットペッパーで予約", "LINEで相談", "空きが出たら連絡"]
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    font_path = find_japanese_font()
    try:
        font_main = ImageFont.truetype(font_path, 96) if font_path else ImageFont.load_default()
        font_sub = ImageFont.truetype(font_path, 48) if font_path else ImageFont.load_default()
    except OSError:
        font_main = font_sub = ImageFont.load_default()

    col = WIDTH // 3
    colors = [ACCENT, LINE_GREEN, (122, 113, 106)]
    for i, (label, sub) in enumerate(zip(labels, sublabels)):
        x0 = i * col
        # 区切り線
        if i > 0:
            draw.line([(x0, 60), (x0, HEIGHT - 60)], fill=(230, 221, 210), width=4)
        # アイコン風の丸
        cx, cy = x0 + col // 2, HEIGHT // 2 - 150
        draw.ellipse([cx - 110, cy - 110, cx + 110, cy + 110], fill=colors[i])
        glyph = ["📅", "💬", "🔔"][i]
        try:
            emoji_font = ImageFont.truetype(font_path, 110) if font_path else font_main
            draw.text((cx, cy), glyph, font=emoji_font, fill=(255, 255, 255), anchor="mm")
        except Exception:  # noqa: BLE001 - 絵文字が描けないフォントでは番号を描く
            draw.text((cx, cy), str(i + 1), font=font_main, fill=(255, 255, 255), anchor="mm")
        draw.text((cx, HEIGHT // 2 + 60), label, font=font_main, fill=TEXT, anchor="mm")
        draw.text((cx, HEIGHT // 2 + 170), sub, font=font_sub, fill=(122, 113, 106), anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_rich_menu_payload(rich_menu, reserve_url: str | None) -> dict:
    col = WIDTH // 3
    areas = []
    if reserve_url:
        areas.append({"bounds": {"x": 0, "y": 0, "width": col, "height": HEIGHT}, "action": {"type": "uri", "label": rich_menu.reserve_label[:20], "uri": reserve_url}})
    else:
        areas.append({"bounds": {"x": 0, "y": 0, "width": col, "height": HEIGHT}, "action": {"type": "message", "label": rich_menu.reserve_label[:20], "text": "予約したいです"}})
    areas.append({"bounds": {"x": col, "y": 0, "width": col, "height": HEIGHT}, "action": {"type": "message", "label": rich_menu.consult_label[:20], "text": rich_menu.consult_message[:300]}})
    areas.append(
        {
            "bounds": {"x": col * 2, "y": 0, "width": WIDTH - col * 2, "height": HEIGHT},
            "action": {"type": "postback", "label": rich_menu.waitlist_label[:20], "data": "action=waitlist", "displayText": "キャンセル待ちに登録します"},
        }
    )
    return {"size": {"width": WIDTH, "height": HEIGHT}, "selected": True, "name": f"tomoni-{rich_menu.stylist_id}", "chatBarText": rich_menu.chat_bar_text[:14] or "メニュー", "areas": areas}


def parse_postback(data: str) -> dict:
    parsed = parse_qs(data or "")
    return {k: v[0] for k, v in parsed.items() if v}


def publish_rich_menu(rich_menu):
    """画像生成（またはアップロード画像）→ 作成 → 画像登録 → 全員の既定メニューに設定。"""
    from apps.lineapp.models import TrackedLink
    from apps.lineapp.services import client_for

    stylist = rich_menu.stylist
    channel = getattr(stylist, "line_channel", None)
    if channel is None or not channel.is_verified:
        raise ValueError("LINEチャネルが接続確認されていません")
    client = client_for(channel)

    reserve_url = None
    if stylist.hotpepper_url:
        if rich_menu.tracked_link is None:
            rich_menu.tracked_link = TrackedLink.objects.create(stylist=stylist, target_url=stylist.hotpepper_url, kind="richmenu")
        reserve_url = rich_menu.tracked_link.url

    if rich_menu.image:
        with rich_menu.image.open("rb") as f:
            image_bytes = f.read()
        content_type = "image/jpeg" if rich_menu.image.name.lower().endswith((".jpg", ".jpeg")) else "image/png"
    else:
        image_bytes = render_rich_menu_image(rich_menu.labels)
        content_type = "image/png"

    old_id = rich_menu.line_rich_menu_id
    try:
        new_id = client.create_rich_menu(build_rich_menu_payload(rich_menu, reserve_url))
        client.upload_rich_menu_image(new_id, image_bytes, content_type)
        client.set_default_rich_menu(new_id)
        if old_id and old_id != new_id:
            try:
                client.delete_rich_menu(old_id)
            except LineApiError as exc:
                logger.info("old rich menu delete failed: %s", exc)
    except LineApiError as exc:
        rich_menu.status = rich_menu.Status.FAILED
        rich_menu.last_error = exc.message
        rich_menu.save()
        raise ValueError(f"LINEへの登録に失敗しました: {exc.message}") from exc

    rich_menu.line_rich_menu_id = new_id
    rich_menu.status = rich_menu.Status.PUBLISHED
    rich_menu.published_at = timezone.now()
    rich_menu.last_error = ""
    rich_menu.save()
    return rich_menu


def unpublish_rich_menu(rich_menu):
    from apps.lineapp.services import client_for

    channel = getattr(rich_menu.stylist, "line_channel", None)
    if channel and channel.is_verified:
        client = client_for(channel)
        try:
            client.cancel_default_rich_menu()
            if rich_menu.line_rich_menu_id:
                client.delete_rich_menu(rich_menu.line_rich_menu_id)
        except LineApiError as exc:
            raise ValueError(f"LINE側の削除に失敗しました: {exc.message}") from exc
    rich_menu.line_rich_menu_id = ""
    rich_menu.status = rich_menu.Status.DRAFT
    rich_menu.published_at = None
    rich_menu.save()
    return rich_menu
