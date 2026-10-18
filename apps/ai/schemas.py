"""Claude の構造化出力（output_config.format）に渡す JSON Schema。

すべて additionalProperties: false / required 全指定にして、アプリ側のパースを単純に保つ。
"""


def _str_array():
    return {"type": "array", "items": {"type": "string"}}


KARTE_SCHEMA = {
    "type": "object",
    "properties": {
        "treatment_summary": {"type": "string", "description": "施術内容の要約（1〜2文）"},
        "menu_items": _str_array(),
        "design_details": {"type": "string", "description": "色味・長さ・質感など仕上がりの具体"},
        "concerns": _str_array(),
        "results": {"type": "string", "description": "悩みに対してどう対処・解決したか"},
        "products_used": _str_array(),
        "home_care_advice": _str_array(),
        "next_check_items": _str_array(),
        "next_visit_weeks": {"type": ["integer", "null"], "description": "次回来店目安（週）。言及が無ければ null"},
        "customer_requests": _str_array(),
        "permission_mentions": {
            "type": "object",
            "properties": {
                "photo_ok": {"type": ["boolean", "null"]},
                "face_ok": {"type": ["boolean", "null"]},
                "story_ok": {"type": ["boolean", "null"]},
            },
            "required": ["photo_ok", "face_ok", "story_ok"],
            "additionalProperties": False,
        },
        "private_notes": {"type": "string", "description": "公開不可の私的情報・会話メモ（SNSには絶対に使わない）"},
    },
    "required": [
        "treatment_summary",
        "menu_items",
        "design_details",
        "concerns",
        "results",
        "products_used",
        "home_care_advice",
        "next_check_items",
        "next_visit_weeks",
        "customer_requests",
        "permission_mentions",
        "private_notes",
    ],
    "additionalProperties": False,
}

DRAFTS_SCHEMA = {
    "type": "object",
    "properties": {
        "thanks_care": {"type": "string", "description": "お礼＋お手入れ案内のLINE本文。予約リンクは {予約リンク} というプレースホルダーで記述"},
        "next_visit": {"type": "string", "description": "次回来店を促す案内文。予約リンクは {予約リンク} というプレースホルダーで記述"},
    },
    "required": ["thanks_care", "next_visit"],
    "additionalProperties": False,
}

GENERALIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "concern": {"type": "string", "description": "個人が特定できない一般化した悩み（1文）"},
        "result": {"type": "string", "description": "施術でどう解決したか（1〜2文）"},
        "removed_items": _str_array(),
    },
    "required": ["concern", "result", "removed_items"],
    "additionalProperties": False,
}

SNS_SCHEMA = {
    "type": "object",
    "properties": {
        "feed_text": {"type": "string"},
        "story_text": {"type": "string"},
        "reel_script": {"type": "string"},
        "hashtags": _str_array(),
    },
    "required": ["feed_text", "story_text", "reel_script", "hashtags"],
    "additionalProperties": False,
}

PII_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "has_pii": {"type": "boolean"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["text", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["has_pii", "findings"],
    "additionalProperties": False,
}

EPISODES_SCHEMA = {
    "type": "object",
    "properties": {
        "episodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string", "description": "美容師本人の一人称で書いた150〜300字のエピソード"},
                    "themes": _str_array(),
                    "question_order": {"type": ["integer", "null"]},
                },
                "required": ["title", "body", "themes", "question_order"],
                "additionalProperties": False,
            },
        },
        "style_summary": {"type": "string", "description": "話し方・語尾・温度感の特徴（投稿文体の参考）"},
        "suggested_first_person": {"type": "string"},
    },
    "required": ["episodes", "style_summary", "suggested_first_person"],
    "additionalProperties": False,
}

BROADCAST_SCHEMA = {
    "type": "object",
    "properties": {
        "body": {"type": "string", "description": "配信本文。予約リンクは {予約リンク} プレースホルダー"},
        "free_alternatives": _str_array(),
    },
    "required": ["body", "free_alternatives"],
    "additionalProperties": False,
}

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "vendor": {"type": "string"},
        "total": {"type": ["integer", "null"], "description": "税込合計（円）"},
        "tax": {"type": ["integer", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "amount": {"type": ["integer", "null"]}},
                "required": ["name", "amount"],
                "additionalProperties": False,
            },
        },
        "suggested_category": {
            "type": "string",
            "enum": ["materials", "booth_rent", "supplies", "travel", "communication", "advertising", "entertainment", "training", "fees", "insurance", "repairs", "utilities", "taxes", "depreciation", "outsourcing", "misc", "unknown"],
        },
        "payment_hint": {"type": "string", "enum": ["cash", "card", "transfer", "unknown"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "notes": {"type": "string"},
    },
    "required": ["date", "vendor", "total", "tax", "items", "suggested_category", "payment_hint", "confidence", "notes"],
    "additionalProperties": False,
}

STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "period_year": {"type": ["integer", "null"]},
        "period_month": {"type": ["integer", "null"]},
        "salon_name": {"type": "string"},
        "gross_sales": {"type": ["integer", "null"], "description": "技術売上・総売上（円）"},
        "commission_rate_pct": {"type": ["number", "null"]},
        "commission_amount": {"type": ["integer", "null"], "description": "報酬額（歩合適用後・控除前）"},
        "deductions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "amount": {"type": ["integer", "null"]}},
                "required": ["label", "amount"],
                "additionalProperties": False,
            },
        },
        "withholding_tax": {"type": ["integer", "null"], "description": "源泉徴収税額。無ければ 0"},
        "net_paid": {"type": ["integer", "null"], "description": "差引支給額・振込額"},
        "paid_on": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "notes": {"type": "string"},
    },
    "required": ["period_year", "period_month", "salon_name", "gross_sales", "commission_rate_pct", "commission_amount", "deductions", "withholding_tax", "net_paid", "paid_on", "confidence", "notes"],
    "additionalProperties": False,
}

RESERVATION_EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["booked", "cancelled", "changed", "unknown"]},
        "customer_name": {"type": "string"},
        "customer_kana": {"type": "string"},
        "reserved_for": {"type": ["string", "null"], "description": "ISO 8601 (YYYY-MM-DDTHH:MM)"},
        "menu": {"type": "string"},
        "stylist_name": {"type": "string"},
        "reservation_id": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["kind", "customer_name", "customer_kana", "reserved_for", "menu", "stylist_name", "reservation_id", "confidence"],
    "additionalProperties": False,
}

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply_text": {"type": "string"},
        "intent": {"type": "string", "enum": ["reservation", "reschedule", "cancel", "question", "thanks", "complaint", "other"]},
        "needs_attention": {"type": "boolean", "description": "美容師が特に注意して確認すべき内容か（クレーム・体調・金銭など）"},
        "note_for_stylist": {"type": "string"},
    },
    "required": ["reply_text", "intent", "needs_attention", "note_for_stylist"],
    "additionalProperties": False,
}
