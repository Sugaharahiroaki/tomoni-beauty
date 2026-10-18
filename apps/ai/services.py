"""プロンプト組み立て → Claude 呼び出し の薄い層。モデル（DB）には依存しない純粋関数群。"""
from __future__ import annotations

import json
from datetime import date

from . import prompts, schemas
from .claude_client import get_ai

EMOJI_LEVEL_LABEL = {0: "使わない", 1: "少し（1〜2個）", 2: "普通（3〜5個）", 3: "多め"}


def format_style(style: dict | None) -> str:
    """StylistProfile から取り出した文体設定 dict を、プロンプト用テキストに整える。"""
    style = style or {}
    lines = [
        f"- 一人称: {style.get('first_person') or '私'}",
        f"- 語尾・トーン: {style.get('tone') or 'やわらかい丁寧語（〜です・〜ます）。押しつけない'}",
        f"- 絵文字の量: {EMOJI_LEVEL_LABEL.get(int(style.get('emoji_level', 1)), '少し')}",
    ]
    if style.get("ng_words"):
        lines.append(f"- 使わない言葉: {style['ng_words']}")
    if style.get("style_summary"):
        lines.append(f"- 話し方の特徴: {style['style_summary']}")
    if style.get("sample_text"):
        lines.append(f"- 参考にする本人の文章:\n{style['sample_text'][:600]}")
    if style.get("signature"):
        lines.append(f"- 署名（LINE文末に付ける場合）: {style['signature']}")
    return "\n".join(lines)


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def extract_karte(transcript: str, stylist_name: str, visited_on: date, customer_context: str = "", menu_names: list[str] | None = None) -> dict:
    user = (
        f"【美容師】{stylist_name}\n【来店日】{visited_on.isoformat()}\n"
        f"【顧客の既知情報】{customer_context or 'なし'}\n"
        f"【この美容師のメニュー名（menu_items はなるべくこの呼び方にそろえる）】{' / '.join(menu_names or []) or 'なし'}\n\n"
        f"【文字起こし】\n{transcript.strip()}"
    )
    return get_ai().generate_json("karte", prompts.KARTE_SYSTEM, user, schemas.KARTE_SCHEMA)


def generate_line_drafts(karte: dict, style: dict | None, has_reservation_link: bool, next_visit_weeks: int | None, visited_on: date, menu_text: str = "") -> dict:
    karte_for_prompt = {k: v for k, v in karte.items() if k not in {"private_notes", "permission_mentions"}}
    user = (
        f"【文体設定】\n{format_style(style)}\n\n"
        f"【来店日】{visited_on.isoformat()}\n"
        f"【次回来店の目安】{f'{next_visit_weeks}週間後' if next_visit_weeks else '特に指定なし（6週間前後）'}\n"
        f"【予約リンク: {'あり' if has_reservation_link else 'なし'}】\n\n"
        f"【メニュー・料金表（料金に触れるときはこの金額だけを使う）】\n{menu_text or 'なし（料金は書かない）'}\n\n"
        f"【カルテ】\n{_dump(karte_for_prompt)}"
    )
    return get_ai().generate_json("drafts", prompts.DRAFTS_SYSTEM, user, schemas.DRAFTS_SCHEMA)


def generalize_story(concerns: list[str], results: str, treatment_summary: str) -> dict:
    """SNS用に悩み・結果を一般化。ここに渡すのは許可された3項目だけ（private_notes 等は呼び出し側で渡さない）。"""
    user = _dump({"concerns": concerns, "results": results, "treatment_summary": treatment_summary})
    return get_ai().generate_json("generalize", prompts.GENERALIZE_SYSTEM, user, schemas.GENERALIZE_SCHEMA)


def generate_sns(
    *,
    purpose: str,
    story_allowed: bool,
    generalized: dict | None,
    treatment_summary: str,
    design_details: str,
    episode: dict | None,
    style: dict | None,
    photo_count: int,
    area_tags: list[str],
    extra_notes: str = "",
) -> dict:
    payload = {
        "purpose": purpose,
        "story_allowed": story_allowed,
        "story": generalized if story_allowed else None,
        "treatment_summary": treatment_summary,
        "design_details": design_details,
        "episode": episode,
        "photo_count": photo_count,
        "area_tags": area_tags,
        "extra_notes": extra_notes,
    }
    user = f"【文体設定】\n{format_style(style)}\n\n【投稿の材料】\n{_dump(payload)}"
    return get_ai().generate_json("sns", prompts.SNS_SYSTEM, user, schemas.SNS_SCHEMA)


def llm_pii_check(text: str) -> dict:
    return get_ai().generate_json("pii_check", prompts.PII_CHECK_SYSTEM, f"【投稿文】\n{text}", schemas.PII_CHECK_SCHEMA, max_tokens=2000)


def build_episodes(qa_pairs: list[dict], stylist_name: str) -> dict:
    """qa_pairs: [{"order": 1, "question": "...", "answer": "..."}]"""
    body = "\n\n".join(f"Q{p['order']}. {p['question']}\nA. {p['answer'].strip() or '（未回答）'}" for p in qa_pairs)
    user = f"【美容師】{stylist_name}\n\n【インタビュー】\n{body}"
    return get_ai().generate_json("episodes", prompts.EPISODES_SYSTEM, user, schemas.EPISODES_SCHEMA, max_tokens=12000)


def draft_broadcast(kind: str, notes: str, style: dict | None, has_reservation_link: bool, slots_text: str = "", segment_summary: str = "", menu_text: str = "") -> dict:
    user = (
        f"【文体設定】\n{format_style(style)}\n\n【kind】{kind}\n【予約リンク: {'あり' if has_reservation_link else 'なし'}】\n"
        f"【絞り込み条件】{segment_summary or 'なし（全員）'}\n【空き枠】\n{slots_text or 'なし'}\n\n"
        f"【メニュー・料金表（料金に触れるときはこの金額だけを使う）】\n{menu_text or 'なし（料金は書かない）'}\n\n"
        f"【伝えたい内容（美容師のメモ）】\n{notes.strip() or '（指定なし）'}"
    )
    return get_ai().generate_json("broadcast", prompts.BROADCAST_SYSTEM, user, schemas.BROADCAST_SCHEMA, max_tokens=3000)


def ocr_receipt(data: bytes, media_type: str) -> dict:
    return get_ai().generate_json_with_document("ocr_receipt", prompts.RECEIPT_OCR_SYSTEM, "このレシートを読み取ってください。", schemas.RECEIPT_SCHEMA, data, media_type)


def ocr_statement(data: bytes, media_type: str) -> dict:
    return get_ai().generate_json_with_document("ocr_statement", prompts.STATEMENT_OCR_SYSTEM, "この報酬明細を読み取ってください。", schemas.STATEMENT_SCHEMA, data, media_type)


def parse_reservation_email(subject: str, body: str, received_at_iso: str) -> dict:
    user = f"【受信日時】{received_at_iso}\n【件名】{subject}\n\n【本文】\n{body[:6000]}"
    return get_ai().generate_json("reservation_email", prompts.RESERVATION_EMAIL_SYSTEM, user, schemas.RESERVATION_EMAIL_SCHEMA, max_tokens=2000)


def suggest_reply(inbound_text: str, style: dict | None, has_reservation_link: bool, customer_context: str, recent_history: list[dict], menu_text: str = "") -> dict:
    history = "\n".join(f"[{h['who']}] {h['text']}" for h in recent_history) or "なし"
    user = (
        f"【文体設定】\n{format_style(style)}\n\n"
        f"【予約リンク: {'あり' if has_reservation_link else 'なし'}】\n"
        f"【お客様の情報（施術履歴など）】\n{customer_context or 'なし'}\n\n"
        f"【メニュー・料金表（料金に触れるときはこの金額だけを使う）】\n{menu_text or 'なし（料金は書かない）'}\n\n"
        f"【直近のやりとり】\n{history}\n\n"
        f"【お客様からのメッセージ】\n{inbound_text.strip()}"
    )
    return get_ai().generate_json("reply", prompts.REPLY_SYSTEM, user, schemas.REPLY_SCHEMA, max_tokens=3000)
