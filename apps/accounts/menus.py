"""メニュー・料金表の貼り付け読み取り。

ホットペッパーのクーポン一覧などを1行1メニューで貼り付けると、料金・対象（新規/再来）・種類を推定して登録する。
料金はAIの文面で使う唯一の根拠になるので、読み取れない行は料金なし（要相談）として扱い、推測で埋めない。
"""
from __future__ import annotations

import re

from .models import MenuItem

PRICE_RE = re.compile(r"[¥￥]?\s*([0-9０-９][0-9０-９,，]{2,})\s*円?\s*(〜|~|～)?\s*(\(税込\)|（税込）)?\s*$")
TARGET_MARK_RE = re.compile(r"[【\[［(（]\s*(新規|初回|再来|リピート)[^】\]］)）]{0,12}[】\]］)）]")
ZEN2HAN = str.maketrans("０１２３４５６７８９，", "0123456789,")

CATEGORY_KEYWORDS = [
    (MenuItem.Category.STRAIGHT, ("縮毛", "ストレート", "矯正")),
    (MenuItem.Category.BLEACH, ("ブリーチ", "ハイライト", "インナー", "イヤリング", "バレイヤージュ", "グラデーション", "ダブルカラー", "Wカラー")),
    (MenuItem.Category.PERM, ("パーマ", "デジパ")),
    (MenuItem.Category.SPA, ("スパ",)),
    (MenuItem.Category.COLOR, ("カラー", "白髪染め", "黒染め")),
    (MenuItem.Category.TREATMENT, ("トリートメント", "髪質改善", "TR")),
    (MenuItem.Category.CUT, ("カット",)),
]


def guess_category(name: str) -> str:
    hits = [cat for cat, words in CATEGORY_KEYWORDS if any(w in name for w in words)]
    if len(hits) >= 2 and ("+" in name or "＋" in name):
        return MenuItem.Category.SET
    return hits[0] if hits else MenuItem.Category.OTHER


def parse_menu_line(line: str) -> dict | None:
    text = line.strip().lstrip("・-*•").strip()
    if not text:
        return None
    target = MenuItem.Target.ALL
    mark = TARGET_MARK_RE.search(text)
    if mark:
        target = MenuItem.Target.NEW if mark.group(1) in ("新規", "初回") else MenuItem.Target.REPEAT
        text = (text[: mark.start()] + text[mark.end() :]).strip()
    price, price_from = None, False
    m = PRICE_RE.search(text)
    if m:
        price = int(m.group(1).translate(ZEN2HAN).replace(",", ""))
        price_from = bool(m.group(2))
        text = text[: m.start()].strip(" 　:：/／-–")
    name = text.strip()
    if not name:
        return None
    return {"name": name[:120], "price": price, "price_from": price_from, "target": target, "category": guess_category(name)}


def parse_menu_text(text: str) -> list[dict]:
    return [item for item in (parse_menu_line(line) for line in (text or "").splitlines()) if item]


def add_menus_from_text(stylist, text: str) -> list[MenuItem]:
    start = (stylist.menus.order_by("-order").values_list("order", flat=True).first() or 0) + 1
    created = []
    for i, item in enumerate(parse_menu_text(text)):
        created.append(MenuItem.objects.create(stylist=stylist, order=start + i, **item))
    return created
