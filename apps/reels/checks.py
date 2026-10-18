"""投稿文のチェック：誇大表現（禁止ワード）と、キャプションの6要素。

個人情報のチェックは apps/ai/pii.py（既存）。ここは「予約狙いの投稿として適切か」を見る。
"""
from __future__ import annotations

import re

# 誇大表現・釣り表現（関係ない人まで集める／効果の保証）。error 扱い
HYPE_WORDS = ["絶対", "誰でも", "必ず", "100%", "１００％", "100％", "劇的", "激変", "魔法", "一瞬で", "最強", "日本一", "No.1", "NO.1", "No1", "ナンバーワン", "確実に", "永久に", "二度と", "完全に治", "保証"]

# キャプションに入れる6要素（警告のみ）
CAPTION_ELEMENTS = [
    ("audience", "誰向けか", re.compile(r"(方へ|方に|方は|方も|人へ|人に|人は|人も|さんへ|向け|お悩み|悩み|悩んで|気になる|困って)")),
    ("outcome", "何が解決するか", re.compile(r"(解決|改善|まとま|きれい|キレイ|綺麗|抑え|なくな|軽く|自然|落ち着|長持ち|持ちが|持ちも|透明感|ツヤ|艶|ふんわり|扱いやす|おさま|収ま|変わ|なれ)")),
    ("duration", "所要時間", re.compile(r"(\d+\s*(分|時間)|[０-９]+\s*(分|時間)|所要)")),
    ("price", "料金の目安", re.compile(r"(\d[\d,，]*\s*円|[¥￥]\s*\d|料金)")),
    ("lasting", "持ちの期間", re.compile(r"(週間|か月|ヶ月|カ月|ヵ月|持ち|もち|色落ち|次回)")),
    ("booking", "予約方法", re.compile(r"(予約|プロフィール|DM|ＤＭ|リンク|ホットペッパー|LINE)")),
]


def hype_findings(texts: list[tuple[str, str]]) -> list[dict]:
    """[(欄の名前, 文章)] から禁止ワードを探す"""
    findings = []
    for field, text in texts:
        if not text:
            continue
        for word in HYPE_WORDS:
            if word.lower() in text.lower():
                findings.append({"field": field, "text": word, "severity": "error"})
    return findings


def hype_summary(texts: list[tuple[str, str]]) -> dict:
    findings = hype_findings(texts)
    return {"passed": not findings, "findings": findings}


def caption_elements(caption: str) -> dict:
    """6要素のうち入っているもの・抜けているもの"""
    present, missing = [], []
    for key, label, pattern in CAPTION_ELEMENTS:
        (present if pattern.search(caption or "") else missing).append({"key": key, "label": label})
    return {"passed": not missing, "present": present, "missing": missing}


def post_texts(post) -> list[tuple[str, str]]:
    """投稿のすべての文章（チェック対象）"""
    out: list[tuple[str, str]] = []
    hook = post.selected_hook or {}
    if hook.get("text"):
        out.append(("フック", hook["text"]))
    if post.script:
        from .ai import script_texts

        out += script_texts(post.script)
    else:
        out += [("キャプション", post.ig_caption or ""), ("ハッシュタグ", " ".join(post.hashtags or []))]
    for i, slide in enumerate(post.carousel or [], 1):
        out.append((f"{i}枚目", f"{slide.get('title', '')} {slide.get('text', '')}"))
    for i, s in enumerate(post.stories or [], 1):
        out.append((f"ストーリーズ{i}", s.get("text", "")))
    if post.cover_text:
        out.append(("表紙", post.cover_text))
    return out
