"""AIに渡す情報（ホワイトリスト）。フック・フィード・ストーリーズ・動画の台本で共通。

渡さないもの：顧客名・呼び名・非公開メモ・要望・来店日時・カルテ本体・写真のメモ。
"""
from __future__ import annotations

from pathlib import Path

from .post_types import FORMAT_LABELS, POST_TYPES, PURPOSE_LABELS, ROLE_LABELS
from .recommend import asset_counts

PROMPTS = Path(__file__).with_name("prompts")


def area_for(stylist) -> str:
    access = stylist.salon_access or ""
    if "駅" in access:
        return access.split("駅")[0].strip()
    return stylist.salon_name or ""


# 型ごとに、料金表から先に拾うメニューの種類（今日の施術メニューが無いとき）
PREFERRED_CATEGORIES = {"before_after": ["set", "color", "bleach"], "suggestion": ["bleach", "color", "set"], "process_reel": ["set", "cut", "color"], "tips": ["treatment", "set", "color"], "personality": []}


def matched_menus(post, limit: int = 6) -> list:
    """今日の施術に近いメニュー。無ければ型に合う種類のメニュー、それも無ければ上位のメニュー"""
    menus = list(post.stylist.menus.filter(is_active=True))
    if not menus:
        return []
    tokens = [t for m in (post.menu_items or []) for t in (m.replace("＋", "+").split("+")) if t.strip()]
    hits = [m for m in menus if any(t.strip() in m.name for t in tokens)] if tokens else []
    if not hits:
        for cat in PREFERRED_CATEGORIES.get(post.post_type, []):
            hits = [m for m in menus if m.category == cat]
            if hits:
                break
    return (hits or menus)[:limit]


def price_lines_for(post) -> list[str]:
    return [m.label() for m in matched_menus(post)]


def lasting_for(post) -> str:
    for m in matched_menus(post):
        if m.duration_weeks:
            return f"約{m.duration_weeks}週間"
    if post.karte_id and post.karte.next_visit_weeks:
        return f"約{post.karte.next_visit_weeks}週間（次回の目安）"
    return ""


def episode_for(post) -> dict | None:
    from apps.profiles.services import select_episode

    from .services import profile_of

    keywords = list(post.menu_items or []) + ([post.theme] if post.theme else [])
    if post.karte_id:
        safe = post.karte.sns_safe_fields()
        keywords += list(safe.get("concerns") or [])
    episode = select_episode(post.stylist, keywords, purpose=profile_of(post.stylist).purpose)
    return episode.as_prompt_dict() if episode else None


def build_sns_context(post) -> dict:
    from apps.drafts.services import style_for

    from .ai import story_for
    from .models import ReelPost
    from .services import profile_of

    stylist = post.stylist
    profile = profile_of(stylist)
    type_def = POST_TYPES.get(post.post_type, {})
    safe = post.karte.sns_safe_fields() if post.karte_id else {}
    counts = asset_counts(post.usable_assets())
    recent = ReelPost.objects.filter(stylist=stylist).exclude(pk=post.pk).exclude(selected_hook={}).order_by("-created_at")[:6]
    return {
        "型": {"キー": post.post_type, "名前": type_def.get("label", ""), "狙い": type_def.get("goal", ""), "説明": type_def.get("description", "")},
        "出来上がる形": FORMAT_LABELS.get(post.output_format, post.output_format),
        "テーマ（得意な悩み・必ずこれに寄せる）": post.theme or "（未設定。施術内容から）",
        "目的": PURPOSE_LABELS.get(profile.purpose, profile.purpose),
        "選んだフック": post.selected_hook or None,
        "美容師": {
            "動画・投稿に出す名前": profile.display_name(),
            "サロン": stylist.salon_name,
            "サロンの場所": stylist.salon_access,
            "地域": area_for(stylist),
            "いつもの呼びかけ": profile.default_cta or "ご相談はDMかプロフィールから",
            "文体設定": style_for(stylist),
        },
        "施術内容（個人情報なし）": {"要約": safe.get("treatment_summary", ""), "仕上がり": safe.get("design_details", ""), "メニュー": post.menu_items} if safe else {"メニュー": post.menu_items},
        "お客様の悩みと結果（一般化済み・掲載許可あり）": story_for(post),
        "素材": {"役割ごとの数": {ROLE_LABELS.get(k, k): v for k, v in counts.items() if k in ROLE_LABELS and v}, "写真": counts["photo"], "動画": counts["video"]},
        "人柄エピソード（1つ・丸写しせず1〜3文で）": episode_for(post),
        "料金・所要時間（料金に触れるときはこの表の金額だけ）": price_lines_for(post) or "登録なし（料金は書かない）",
        "持ちの目安": lasting_for(post) or "不明（書かない）",
        "予約リンク": "あり（『プロフィールのリンクから』と案内）" if stylist.has_hotpepper else "なし（『DMから』と案内）",
        "直近の投稿のフック（同じ言い回しを避ける）": [(p.selected_hook or {}).get("text", "") for p in recent],
    }


def system_prompt_for(post, part: str) -> str:
    """共通ルール ＋ 型ごとのルール ＋ 作る部分（hooks / feed / stories）のルール"""
    names = ["sns_common.md"]
    if post.post_type:
        names.append(f"types/{post.post_type}.md")
    names.append(f"parts/{part}.md")
    texts = []
    for name in names:
        path = PROMPTS / name
        if path.exists():
            texts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(texts)
