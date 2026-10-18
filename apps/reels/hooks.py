"""フック（最初の2秒の一言）を3案作る。種類は型ごとに決まった3つ（呼びかけ／結果先出し／悩みの映像／意外性／地域）。

誇大表現（絶対・誰でも・必ず…）が入った案は、AIに1回だけ直させる。それでも残れば印を付けて表示する。
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

from apps.ai.claude_client import AIError, get_ai

from .checks import hype_findings
from .context import area_for, build_sns_context, system_prompt_for
from .post_types import HOOK_TYPES, HOOK_TYPE_LABELS, POST_TYPES

log = logging.getLogger(__name__)
HOOK_KEYS = [k for k, _, _ in HOOK_TYPES]
HOOKS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hooks"],
    "properties": {
        "hooks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "text", "visual"],
                "properties": {"type": {"type": "string", "enum": HOOK_KEYS}, "text": {"type": "string"}, "visual": {"type": "string"}},
            },
        }
    },
}


def hook_types_for(post_type: str) -> list[str]:
    return list(POST_TYPES.get(post_type, {}).get("hook_types") or HOOK_KEYS[:3])


def generate_hooks(post) -> list[dict]:
    hooks = mock_hooks(post) if settings.AI_FAKE else ai_hooks(post)
    return annotate(hooks)


def annotate(hooks: list[dict]) -> list[dict]:
    out = []
    for h in hooks[:3]:
        findings = hype_findings([("フック", h.get("text", ""))])
        out.append({"type": h.get("type", "call"), "label": HOOK_TYPE_LABELS.get(h.get("type", ""), ""), "text": (h.get("text") or "").strip()[:60], "visual": (h.get("visual") or "").strip()[:80], "hype": [f["text"] for f in findings]})
    return out


def mock_hooks(post) -> list[dict]:
    """AIなしの見本。テーマと地域を入れた定型文"""
    theme = post.theme or ("・".join(post.menu_items) if post.menu_items else "髪の悩み")
    area = area_for(post.stylist) or "近く"
    templates = {
        "call": (f"{theme}で悩んでいる人へ", "仕上がりの毛先のアップ"),
        "result": (f"{theme}、3週間後もこのまま", "仕上がりの後ろ姿"),
        "scene": (f"朝、鏡の前で{theme}にため息", "施術前の後ろ姿か毛先"),
        "surprise": (f"{theme}、実は原因は別のところ", "カウンセリングの手元"),
        "local": (f"{area}で{theme}に困ったら", "店内と仕上がり"),
    }
    return [{"type": t, "text": templates[t][0], "visual": templates[t][1]} for t in hook_types_for(post.post_type)]


def ai_hooks(post) -> list[dict]:
    types = hook_types_for(post.post_type)
    context = build_sns_context(post)
    user = "## 今回の情報\n" + json.dumps(context, ensure_ascii=False, indent=1) + f"\n\n## 作るもの\nフックを3案。種類は順に {', '.join(HOOK_TYPE_LABELS[t] for t in types)}（type は {', '.join(types)}）。"
    system = system_prompt_for(post, "hooks")
    try:
        result = get_ai().generate_json("sns_hooks", system, user, HOOKS_SCHEMA, max_tokens=2000)
        hooks = _normalize(result, types)
        bad = [h for h in hooks if hype_findings([("", h["text"])])]
        if bad:
            words = sorted({f["text"] for h in bad for f in hype_findings([("", h["text"])])})
            result = get_ai().generate_json("sns_hooks", system, user + f"\n\n前回の案に使えない表現（{'・'.join(words)}）がありました。誇大表現・効果の保証を使わずに作り直してください。", HOOKS_SCHEMA, max_tokens=2000)
            hooks = _normalize(result, types)
        return hooks
    except AIError as exc:
        log.warning("フックの生成に失敗（見本に切り替え）: %s", exc)
        return mock_hooks(post)


def _normalize(result: dict, types: list[str]) -> list[dict]:
    hooks = [h for h in (result or {}).get("hooks", []) if h.get("text")]
    seen = set()
    out = []
    for i, h in enumerate(hooks):
        t = h.get("type") if h.get("type") in HOOK_KEYS else types[min(i, len(types) - 1)]
        if h["text"] in seen:
            continue
        seen.add(h["text"])
        out.append({"type": t, "text": h["text"], "visual": h.get("visual", "")})
    if len(out) < 3:
        raise AIError("フックが3案そろいませんでした")
    return out[:3]
