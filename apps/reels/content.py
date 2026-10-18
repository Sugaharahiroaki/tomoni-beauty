"""選んだフックで本文を作る（2段階目）。

- 動画（reel）  : 既存の台本づくり（ai.generate_script）→ 問題がなければそのまま動画作成へ
- フィード      : 1枚目〜最後の枚の文字 ＋ キャプション ＋ ハッシュタグ ＋ 表紙の文字
- ストーリーズ  : 短文2〜4枚 ＋ スタンプ案 ＋ 短いキャプション
生成後に 個人情報 / 誇大表現 / キャプションの6要素 を確認する。
"""
from __future__ import annotations

import json
import logging
import re

from django.conf import settings

from apps.ai import pii as pii_module
from apps.ai.claude_client import AIError, get_ai

from . import services
from .checks import caption_elements, hype_findings, hype_summary, post_texts
from .context import area_for, build_sns_context, lasting_for, price_lines_for, system_prompt_for
from .post_types import POST_TYPES

log = logging.getLogger(__name__)

_slide = {"type": "object", "additionalProperties": False, "required": ["title", "text"], "properties": {"title": {"type": "string"}, "text": {"type": "string"}}}
FEED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slides", "caption", "hashtags", "cover_text"],
    "properties": {"slides": {"type": "array", "items": _slide}, "caption": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}}, "cover_text": {"type": "string"}},
}
STICKERS = ["question", "poll", "quiz", "slider", "link", "none"]
STICKER_LABELS = {"question": "質問", "poll": "アンケート", "quiz": "クイズ", "slider": "スライダー", "link": "リンク", "none": "なし"}
STORIES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stories", "caption", "hashtags"],
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "sticker"],
                "properties": {"text": {"type": "string"}, "sticker": {"type": "object", "additionalProperties": False, "required": ["type", "text"], "properties": {"type": {"type": "string", "enum": STICKERS}, "text": {"type": "string"}}}},
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
}


# ------------------------------------------------------------------ 入口


def generate_content(post) -> None:
    """選んだフックで本文（または動画）を作る。呼び出し元（tasks）で例外を処理する"""
    if post.output_format == "reel":
        generate_reel(post)
    elif post.output_format == "feed":
        generate_feed(post)
    else:
        generate_stories(post)


def finalize_checks(post) -> None:
    """誇大表現・6要素・（文章だけの投稿の）個人情報"""
    from .ai import forbidden_terms

    post.hype_check = hype_summary(post_texts(post))
    post.caption_check = caption_elements(post.ig_caption)
    if not post.script:
        terms = forbidden_terms(post)
        findings = []
        for label, text in post_texts(post):
            for f in pii_module.check_text(text, terms).findings:
                findings.append({"kind": f.kind, "text": f.text, "severity": f.severity, "field": label})
        post.pii_check = {"passed": not any(f["severity"] == "error" for f in findings), "findings": findings}


# ------------------------------------------------------------------ 動画


def generate_reel(post) -> None:
    from .ai import generate_script

    services.assign_slots(post)
    generate_script(post)  # status → REVIEW
    post.refresh_from_db()
    finalize_checks(post)
    notes = list(post.notes or [])
    blocked = []
    if post.pii_errors:
        blocked.append("お客様の個人情報の可能性がある箇所があります")
    if post.hype_errors:
        blocked.append("誇大表現（" + "・".join(sorted({f['text'] for f in post.hype_errors})) + "）があります")
    if blocked:
        notes.append("直してから動画を作ってください：" + "／".join(blocked))
        post.notes = notes
        post.save(update_fields=["hype_check", "caption_check", "notes", "updated_at"])
        return
    post.save(update_fields=["hype_check", "caption_check", "updated_at"])
    if services.options(post.stylist)["ffmpeg_available"]:
        services.request_render(post)
    else:
        post.notes = notes + ["このサーバーに FFmpeg が無いため、台本までで止めています。"]
        post.save(update_fields=["notes", "updated_at"])


# ------------------------------------------------------------------ フィード・ストーリーズ


def _ai_json(post, task: str, part: str, schema: dict, ask: str) -> dict | None:
    context = build_sns_context(post)
    user = "## 今回の情報\n" + json.dumps(context, ensure_ascii=False, indent=1) + "\n\n## 作るもの\n" + ask
    system = system_prompt_for(post, part)
    try:
        result = get_ai().generate_json(task, system, user, schema, max_tokens=6000)
        texts = _texts_of(result)
        bad = hype_findings(texts)
        if bad:
            words = "・".join(sorted({f["text"] for f in bad}))
            result = get_ai().generate_json(task, system, user + f"\n\n前回の案に使えない表現（{words}）がありました。誇大表現・効果の保証を使わずに作り直してください。", schema, max_tokens=6000)
        return result
    except AIError as exc:
        log.warning("%s の生成に失敗（見本に切り替え）: %s", task, exc)
        return None


def _texts_of(result: dict) -> list[tuple[str, str]]:
    out = [("caption", result.get("caption", "")), ("cover", result.get("cover_text", ""))]
    out += [(f"slide{i}", f"{s.get('title', '')} {s.get('text', '')}") for i, s in enumerate(result.get("slides", []), 1)]
    out += [(f"story{i}", s.get("text", "")) for i, s in enumerate(result.get("stories", []), 1)]
    return out


def _clean_tags(tags) -> list[str]:
    out = []
    for t in tags or []:
        t = re.sub(r"[^\w一-龥ぁ-んァ-ヶー]", "", str(t).strip().lstrip("#＃"))
        if t and t not in out:
            out.append(t)
    return out[:15]


def generate_feed(post) -> None:
    result = None if settings.AI_FAKE else _ai_json(post, "sns_feed", "feed", FEED_SCHEMA, "フィード（複数枚）の各枚の文字・キャプション・ハッシュタグ・表紙の文字をJSONで。")
    if result is None:
        result = mock_feed(post)
    post.carousel = [{"title": (s.get("title") or "").strip()[:40], "text": (s.get("text") or "").strip()[:200]} for s in result.get("slides", [])][:10]
    post.cover_text = (result.get("cover_text") or (post.carousel[0]["title"] if post.carousel else "")).strip()[:60]
    post.ig_caption = (result.get("caption") or "").strip()
    post.hashtags = _clean_tags(result.get("hashtags"))
    post.status = "READY"
    finalize_checks(post)
    post.save()


def generate_stories(post) -> None:
    result = None if settings.AI_FAKE else _ai_json(post, "sns_stories", "stories", STORIES_SCHEMA, "ストーリーズ2〜4枚の短文とスタンプ案、短いキャプション、ハッシュタグをJSONで。")
    if result is None:
        result = mock_stories(post)
    stories = []
    for s in result.get("stories", [])[:4]:
        sticker = s.get("sticker") or {}
        stype = sticker.get("type") if sticker.get("type") in STICKERS else "none"
        stories.append({"text": (s.get("text") or "").strip()[:120], "sticker": {"type": stype, "label": STICKER_LABELS[stype], "text": (sticker.get("text") or "").strip()[:60]}})
    post.stories = stories
    post.cover_text = (post.selected_hook or {}).get("text", "")[:60]
    post.ig_caption = (result.get("caption") or "").strip()
    post.hashtags = _clean_tags(result.get("hashtags"))
    post.status = "READY"
    services.ensure_tracked_link(post)
    finalize_checks(post)
    post.save()


# ------------------------------------------------------------------ 見本（AIなし）


def _price_block(post) -> str:
    lines = price_lines_for(post)
    parts = []
    if lines:
        parts.append("料金の目安：" + lines[0])
    lasting = lasting_for(post)
    if lasting:
        parts.append(f"持ち：{lasting}")
    return "\n".join(parts)


def _booking_line(post) -> str:
    return "ご予約はプロフィールのリンクから。相談だけでもDMへどうぞ。" if post.stylist.has_hotpepper else "ご予約・ご相談はDMへどうぞ。"


def mock_caption(post, body: str) -> str:
    hook = (post.selected_hook or {}).get("text", "")
    theme = post.theme or "髪のお悩み"
    minutes = next((m.minutes for m in post.stylist.menus.filter(is_active=True) if m.minutes), None)
    lines = [hook, "", f"{theme}でお悩みの方へ。{body}"]
    if minutes:
        lines.append(f"所要時間は約{minutes}分です。")
    block = _price_block(post)
    if block:
        lines += ["", block]
    lines += ["", _booking_line(post)]
    return "\n".join(ln for ln in lines if ln is not None).strip()


def mock_feed(post) -> dict:
    hook = (post.selected_hook or {}).get("text", "") or "今日の仕上がり"
    theme = post.theme or "髪のお悩み"
    type_key = post.post_type
    slides = [{"title": hook, "text": f"{theme}が気になる方へ"}]
    if type_key == "tips":
        slides += [
            {"title": "① ぬるめのお湯で洗う", "text": "38度くらい。熱いお湯は色落ちと乾燥のもと"},
            {"title": "② 根元から乾かす", "text": "毛先は最後に。乾かし残しが広がりの原因"},
            {"title": "③ 乾かす前にひと塗り", "text": "アウトバストリートメントを毛先だけに"},
        ]
        body = "毎日の3つで、仕上がりの持ちが変わります。"
    else:
        n = max(post.usable_assets().filter(role="after").count(), 2)
        slides += [{"title": f"仕上がり {i}", "text": "後ろ姿と毛先の質感を見てください"} for i in range(1, min(n, 6) + 1)]
        body = "仕上がりだけでなく、伸びてきたときの扱いやすさまで考えて作っています。"
    last = ["料金・所要時間・ご予約"]
    block = _price_block(post)
    slides.append({"title": last[0], "text": (block + "\n" if block else "") + _booking_line(post)})
    return {"slides": slides, "caption": mock_caption(post, body), "hashtags": _mock_tags(post), "cover_text": hook}


def mock_stories(post) -> dict:
    hook = (post.selected_hook or {}).get("text", "") or "今日のひとこと"
    theme = post.theme or "髪のお悩み"
    stories = [
        {"text": hook, "sticker": {"type": "question", "text": f"{theme}、いま気になることは？"}},
        {"text": f"{theme}は、最初のカウンセリングでいちばん時間をかけるところです。", "sticker": {"type": "poll", "text": "相談してみたい？ はい／まだ"}},
        {"text": _booking_line(post), "sticker": {"type": "link" if post.stylist.has_hotpepper else "none", "text": "予約はこちら" if post.stylist.has_hotpepper else ""}},
    ]
    return {"stories": stories, "caption": mock_caption(post, "カウンセリングで一緒に決めましょう。"), "hashtags": _mock_tags(post)}


def _mock_tags(post) -> list[str]:
    from apps.drafts.services import area_tags_for

    area = [t.lstrip("#") for t in area_tags_for(post.stylist)]
    theme = [post.theme.replace("・", "")[:12]] if post.theme else []
    base = [m.replace(" ", "") for m in (post.menu_items or [])][:3]
    extra = ["美容師", "フリーランス美容師", "ヘアスタイル"] + ([area_for(post.stylist) + "美容室"] if area_for(post.stylist) else [])
    return _clean_tags(theme + base + area + extra)
