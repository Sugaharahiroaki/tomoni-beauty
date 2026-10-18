"""動画の台本づくり（Claude）。

APIキーが無いときは、型の見本どおりの台本を作る（お試しモード）。
AIの台本はプログラムでルール（素材ID・顔・個人情報・長さ）を確認し、違反があれば2回まで直させる。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from apps.ai import pii as pii_module
from apps.ai import services as ai_services
from apps.ai.claude_client import AIError, get_ai
from apps.profiles.models import Episode, EpisodeUsage

from .engine.audio import FFMPEG
from .models import BgmTrack, ReelPost, UsageLog
from .recipes import TEMPLATES, shot_list

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).with_name("prompts")
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "static"]
MAX_SHOT_SEC = 4.0
PRICE_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5": (5.0, 25.0)}

_num_or_null = {"anyOf": [{"type": "number"}, {"type": "null"}]}
SCRIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["theme_title", "hook_type", "scenes", "cta", "episode_ids", "bgm_category", "ig_caption", "hashtags", "yt_title", "yt_description", "notes_for_stylist"],
    "properties": {
        "theme_title": {"type": "string"},
        "hook_type": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "caption", "narration", "caption_pos", "shots"],
                "properties": {
                    "role": {"type": "string"},
                    "caption": {"type": "string"},
                    "narration": {"type": "string"},
                    "caption_pos": {"type": "string", "enum": ["auto", "top", "middle", "bottom"]},
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["asset_id", "motion", "tight", "focus_x", "focus_y", "sec", "video_start"],
                            "properties": {
                                "asset_id": {"type": "string"},
                                "motion": {"type": "string", "enum": MOTIONS},
                                "tight": {"type": "number"},
                                "focus_x": {"type": "number"},
                                "focus_y": {"type": "number"},
                                "sec": _num_or_null,
                                "video_start": _num_or_null,
                            },
                        },
                    },
                },
            },
        },
        "cta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "text", "narration", "background_asset_id"],
            "properties": {"title": {"type": "string"}, "text": {"type": "string"}, "narration": {"type": "string"}, "background_asset_id": {"type": "string"}},
        },
        "episode_ids": {"type": "array", "items": {"type": "string"}},
        "bgm_category": {"type": "string", "enum": BgmTrack.CATEGORIES},
        "ig_caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "yt_title": {"type": "string"},
        "yt_description": {"type": "string"},
        "notes_for_stylist": {"type": "string"},
    },
}


def system_prompt(post: ReelPost | None = None) -> str:
    names = ["script_rules.md", "reel_structure.md", "reel_templates.md"]
    if post is not None and post.post_type and (PROMPTS / "types" / f"{post.post_type}.md").exists():
        names.append(f"types/{post.post_type}.md")
    return "\n\n---\n\n".join((PROMPTS / name).read_text(encoding="utf-8") for name in names)


def wrap_hook(text: str, width: int = 9, lines: int = 2) -> str:
    """フックの文をテロップ用に 1行9文字×2行 に収める"""
    text = (text or "").replace("\n", "").strip()
    chunks = []
    while text and len(chunks) < lines:
        cut = width
        for i, ch in enumerate(text[:width]):
            if ch in "、。！？!?" and i >= 3:
                cut = i + 1
        chunks.append(text[:cut].rstrip("、"))
        text = text[cut:]
    if text:
        chunks[-1] = chunks[-1][: width - 1] + "…"
    return "\n".join(chunks)


# ------------------------------------------------------------------ 入力の組み立て


def asset_image_b64(asset, max_side=1024) -> str:
    from PIL import Image

    path = Path(asset.file.path)
    if asset.kind == "video":
        at = max((asset.duration_sec or 2) / 2, 0)
        r = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True)
        image = Image.open(io.BytesIO(r.stdout))
    else:
        image = Image.open(path)
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def forbidden_terms(post: ReelPost) -> set[str]:
    from apps.drafts.services import forbidden_terms_for

    return forbidden_terms_for(post.customer) if post.customer_id else set()


def story_for(post: ReelPost) -> dict | None:
    """お客様の悩みと結果（ストーリー掲載OKの顧客のみ・一般化済み）。名前が残っていれば置換。"""
    if not (post.uses_story and post.karte_id and post.customer_id and post.customer.story_ok):
        return None
    if post.generalized_story:
        return post.generalized_story
    safe = post.karte.sns_safe_fields()
    if not (safe["concerns"] or safe["results"]):
        return None
    generalized = ai_services.generalize_story(safe["concerns"], safe["results"], safe["treatment_summary"])
    terms = forbidden_terms(post)
    for key in ("concern", "result"):
        for hit in pii_module.find_forbidden_terms(generalized.get(key, ""), terms):
            generalized[key] = generalized[key].replace(hit, "お客様")
    post.generalized_story = generalized
    post.save(update_fields=["generalized_story", "updated_at"])
    return generalized


def build_context(post: ReelPost) -> dict:
    from apps.drafts.services import style_for

    stylist = post.stylist
    profile = getattr(stylist, "reel_profile", None)
    template = TEMPLATES[post.template_key]
    episodes = list(Episode.objects.filter(stylist=stylist, is_active=True).order_by("created_at")[:12])
    recent = list(ReelPost.objects.filter(stylist=stylist).exclude(pk=post.pk).exclude(script__isnull=True).order_by("-created_at")[:6])
    safe = post.karte.sns_safe_fields() if post.karte_id else {}
    return {
        "美容師": {
            "名前": stylist.display_name,
            "動画に出す名前": profile.display_name() if profile else stylist.salon_name or stylist.display_name,
            "サロン": stylist.salon_name,
            "サロンの場所": stylist.salon_access,
            "いつもの呼びかけ": getattr(profile, "default_cta", "") or "ご相談はDMかプロフィールから",
            "文体設定": style_for(stylist),
        },
        "話し手": {"性別": getattr(profile, "speaker_gender", "女性"), "年代": getattr(profile, "speaker_age", "")},
        "型": {"キー": post.template_key, "名前": template["label"], "ゴール": template["goal"], "長さの目安（秒）": list(template["seconds"]), "CTA": template["cta"]},
        "企画": plan_context(post),
        "今日の施術": post.menu_items,
        "施術内容（カルテから・個人情報なし）": {"要約": safe.get("treatment_summary", ""), "仕上がり": safe.get("design_details", "")} if safe else None,
        "お客様の悩みと結果（一般化済み・掲載許可あり）": story_for(post),
        "face_allowed": post.face_allowed,
        "撮影リスト": [{"項目": s["key"], "役割": s["role"], "撮るもの": s["what"]} for s in post.shot_list],
        "人柄エピソード": [{"id": str(e.id), "タイトル": e.title, "本文": e.body, "テーマ": e.themes, "使った回数": e.usages.count()} for e in episodes],
        "直近の投稿（同じフックを繰り返さない）": [{"型": p.template_key, "フック": (p.script or {}).get("scenes", [{}])[0].get("narration", "")} for p in recent],
        "今日の日付": str(timezone.localdate()),
    }


def plan_context(post: ReelPost) -> dict | None:
    """投稿の企画（型・テーマ・目的・選んだフック・料金）。型を決めていない旧データでは None"""
    if not post.post_type:
        return None
    from .context import lasting_for, price_lines_for
    from .post_types import PURPOSE_LABELS, TYPE_LABELS

    profile = getattr(post.stylist, "reel_profile", None)
    return {
        "型": TYPE_LABELS.get(post.post_type, post.post_type),
        "テーマ（得意な悩み・必ずこれに寄せる）": post.theme or "（未設定）",
        "目的": PURPOSE_LABELS.get(getattr(profile, "purpose", "general"), ""),
        "選んだフック（最初のシーンのテロップとセリフはこれを使う）": post.selected_hook or None,
        "料金・所要時間（料金に触れるときはこの表の金額だけ）": price_lines_for(post) or "登録なし（料金は書かない）",
        "持ちの目安": lasting_for(post) or "不明（書かない）",
        "キャプションに入れる6要素": ["誰向けか", "何が解決するか", "所要時間", "料金の目安（表にあるときだけ）", "持ちの期間（分かるときだけ）", "予約方法"],
    }


def build_messages(post: ReelPost, assets, feedback=None) -> list[dict]:
    today = timezone.localdate()
    content = [{"type": "text", "text": "## 今回の情報\n" + json.dumps(build_context(post), ensure_ascii=False, indent=1)}, {"type": "text", "text": "## 素材（写真・動画）"}]
    for a in assets:
        taken = a.taken_at or a.created_at
        meta = {"asset_id": str(a.id), "種類": a.kind, "撮影リストの項目": a.slot or "未指定", "役割": a.role_label, "ネットの素材（雰囲気の補助にだけ使う）": a.is_stock, "face_visible": a.face_visible, "taken_today": bool(taken and timezone.localtime(taken).date() == today), "撮影時刻": timezone.localtime(a.taken_at).strftime("%H:%M") if a.taken_at else None, "長さ（秒）": a.duration_sec}
        content.append({"type": "text", "text": json.dumps(meta, ensure_ascii=False)})
        try:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": asset_image_b64(a)}})
        except Exception:  # noqa: BLE001
            log.warning("素材を画像にできませんでした: %s", a.id)
    ask = "上の素材で、型に沿った台本をJSONで作ってください。"
    if (post.selected_hook or {}).get("text"):
        ask += f"\n最初のシーンのテロップとセリフは、選んだフック「{post.selected_hook['text']}」を使ってください（テロップは1行9文字×2行までに整える）。"
    if feedback:
        ask += "\n\n前回の台本には次の問題がありました。直してください：\n- " + "\n- ".join(feedback)
    content.append({"type": "text", "text": ask})
    return [{"role": "user", "content": content}]


# ------------------------------------------------------------------ ルールの確認


def script_texts(script: dict) -> list[tuple[str, str]]:
    out = []
    for i, scene in enumerate(script.get("scenes", []), 1):
        out.append((f"{i}番目のテロップ", scene.get("caption", "")))
        out.append((f"{i}番目のセリフ", scene.get("narration", "")))
    cta = script.get("cta") or {}
    out += [("CTAの文字", cta.get("text", "")), ("CTAのセリフ", cta.get("narration", "")), ("Instagramの文章", script.get("ig_caption", "")), ("YouTubeの題名", script.get("yt_title", "")), ("YouTubeの説明", script.get("yt_description", "")), ("ハッシュタグ", " ".join(script.get("hashtags", [])))]
    return out


def pii_problems(script: dict, terms: set[str]) -> list[str]:
    problems = []
    for label, text in script_texts(script):
        result = pii_module.check_text(text, terms)
        for f in result.errors:
            problems.append(f"{label}にお客様の個人情報の可能性（{f.text}）があります。削ってください")
    return problems


def check_script(script: dict, assets, post: ReelPost) -> list[str]:
    problems = []
    ids = {str(a.id) for a in assets}
    today = timezone.localdate()
    today_ids = {str(a.id) for a in assets if (a.taken_at or a.created_at) and timezone.localtime(a.taken_at or a.created_at).date() == today}
    if not script.get("scenes"):
        return ["シーンが1つもありません"]
    for i, scene in enumerate(script["scenes"], 1):
        if not scene.get("shots"):
            problems.append(f"{i}番目のシーンに映像がありません")
        for shot in scene.get("shots", []):
            if shot.get("asset_id") not in ids:
                problems.append(f"{i}番目のシーンに使えない素材ID（{shot.get('asset_id')}）があります")
            if shot.get("sec") and shot["sec"] > MAX_SHOT_SEC + (0.5 if post.template_key in ("stylist_story", "self_intro") else 0):
                problems.append(f"{i}番目のシーンのショットが長すぎます（{shot['sec']}秒）")
        text = scene.get("narration", "") + scene.get("caption", "")
        if any(w in text for w in ["今日", "今朝"]) and not all(s.get("asset_id") in today_ids for s in scene.get("shots", [])):
            problems.append(f"{i}番目のシーンは「今日」と言っていますが、今日撮った素材ではありません")
    hook = script["scenes"][0].get("caption", "")
    if any(len(line) > 9 for line in hook.split("\n")) or hook.count("\n") > 1:
        problems.append("フックのテロップが長すぎます（1行7文字前後×2行まで）")
    if script.get("cta", {}).get("background_asset_id") not in ids:
        problems.append("CTAの背景に使えない素材IDが指定されています")
    valid_eps = {str(e) for e in Episode.objects.filter(stylist=post.stylist, is_active=True).values_list("id", flat=True)}
    for eid in script.get("episode_ids", []):
        if eid not in valid_eps:
            problems.append(f"使えないエピソードID（{eid}）が指定されています")
    problems += pii_problems(script, forbidden_terms(post))
    return problems


def clamp_script(script: dict) -> dict:
    for scene in script.get("scenes", []):
        if scene.get("caption_pos") not in ("auto", "top", "middle", "bottom"):
            scene["caption_pos"] = "auto"
        for shot in scene.get("shots", []):
            shot["tight"] = min(max(float(shot.get("tight") or 1.0), 1.0), 2.2)
            shot["focus_x"] = min(max(float(shot.get("focus_x") if shot.get("focus_x") is not None else 0.5), 0.0), 1.0)
            shot["focus_y"] = min(max(float(shot.get("focus_y") if shot.get("focus_y") is not None else 0.5), 0.0), 1.0)
            if shot.get("motion") not in MOTIONS:
                shot["motion"] = "zoom_in"
    return script


# ------------------------------------------------------------------ 生成


def generate_script(post: ReelPost) -> tuple[dict, list[str]]:
    assets = list(post.usable_assets())
    if not assets:
        raise ValueError("使える写真か動画を1つ以上追加してください（顔が写っている素材は顔出しOKのときだけ使えます）。")
    if settings.AI_FAKE:
        script = mock_script(post, assets)
        notes = ["お試し：AIを使わず、型の見本どおりの台本を作りました。"]
    else:
        script, notes = ai_script(post, assets)
    apply_script(post, script, notes)
    return script, notes


def ai_script(post: ReelPost, assets) -> tuple[dict, list[str]]:
    feedback = None
    notes = []
    for attempt in range(3):
        try:
            script = get_ai().generate_json_messages("reel_script", system_prompt(post), build_messages(post, assets, feedback), SCRIPT_SCHEMA, max_tokens=16000)
        except AIError as exc:
            raise RuntimeError(str(exc)) from exc
        if script is None:
            return mock_script(post, assets), ["AIが使えないため、型の見本どおりの台本にしました。"]
        log_usage(post)
        script = clamp_script(script)
        problems = check_script(script, assets, post)
        if not problems:
            return script, notes
        feedback = problems
        notes.append(f"{attempt + 1}回目の台本を直させました：" + "／".join(problems))
    notes.append("AIの台本がルールを守れなかったため、型の見本どおりの台本に切り替えました。")
    return mock_script(post, assets), notes


def log_usage(post: ReelPost) -> None:
    price_in, price_out = PRICE_PER_MTOK.get(settings.CLAUDE_MODEL, (4.0, 20.0))
    # トークン数はクライアント層のログに出る。ここでは1回あたりの概算を記録する
    UsageLog.objects.create(stylist=post.stylist, post=post, provider="anthropic", model=settings.CLAUDE_MODEL, operation="reel_script", input_tokens=12000, output_tokens=2500, cost_usd=12000 * price_in / 1e6 + 2500 * price_out / 1e6)


def fill_slot_text(text: str, post: ReelPost) -> str:
    """撮影リストの見本の言葉の {サロン} {名前} {エリア} {得意} を、この美容師の情報で埋める"""
    stylist = post.stylist
    profile = getattr(stylist, "reel_profile", None)
    salon = stylist.salon_name or (profile.display_name() if profile else "") or "サロン"
    name = (stylist.display_name or "").split()[0] if stylist.display_name else ""
    access = stylist.salon_access or ""
    area = access.split("駅")[0].strip() if "駅" in access else salon
    good = "・".join(post.menu_items) if post.menu_items else "カラー"
    return (text or "").replace("{サロン}", salon).replace("{名前}", name).replace("{エリア}", area).replace("{得意}", good)


def mock_script(post: ReelPost, assets) -> dict:
    """AIを使わない台本：撮影リストの項目と素材を対応づけ、型の見本の言葉を使う"""
    from .post_types import ROLE_SLOTS

    slots = shot_list(post.template_key)
    keys = {s["key"] for s in slots}
    by_slot = {}
    for a in assets:
        by_slot.setdefault(a.slot, []).append(a)
    rest = [a for a in assets if a.slot not in keys]
    # 項目に素材が無いとき、同じ役割の素材を使い回すための対応表（項目 → 役割）
    roles_for_slot = {}
    for role, slot_keys in ROLE_SLOTS.get(post.template_key, {}).items():
        for k in slot_keys:
            roles_for_slot.setdefault(k, []).append(role)
    by_role = {}
    for a in assets:
        by_role.setdefault(a.role or "other", []).append(a)
    ordered = sorted(slots, key=lambda s: (s["role"] != "フック", s["work"]))
    scenes = []
    for slot in ordered:
        group = (by_slot.get(slot["key"]) or ([rest.pop(0)] if rest else []))[:4]
        if not group and not slot.get("optional"):
            for role in roles_for_slot.get(slot["key"], []):
                if by_role.get(role):
                    group = [by_role[role][-1]]  # 必須の項目は同じ役割の素材を使い回す
                    break
        if not group or not slot.get("narration"):
            continue
        asset = group[0]
        shot = {"asset_id": str(asset.id), "motion": "zoom_in", "tight": 1.0, "focus_x": 0.5, "focus_y": 0.5, "sec": None, "video_start": asset.best_start}
        if len(group) > 1:  # 作品写真など、1つの項目に複数枚あるときは順に見せる
            shots = [dict(shot, asset_id=str(a.id), video_start=a.best_start) for a in group]
        elif slot["role"] == "フック":
            shots = [dict(shot, sec=1.1), dict(shot, tight=1.6, video_start=None if asset.kind == "photo" else (asset.best_start or 0) + 1.1)]
        else:
            shots = [shot]
        caption = fill_slot_text(slot["caption"], post)
        if post.template_key == "daily" and slot["role"] not in ("フック", "締め") and asset.taken_at:
            taken = timezone.localtime(asset.taken_at)
            caption = f"{taken.hour}:{taken.minute:02d} {caption}"
        scenes.append({"role": slot["role"], "caption": caption, "narration": fill_slot_text(slot["narration"], post), "caption_pos": "auto", "shots": shots})
    if not scenes:
        a = assets[0]
        scenes.append({"role": "フック", "caption": "今日の仕上がり", "narration": "今日の仕上がり、見てください。", "caption_pos": "auto", "shots": [{"asset_id": str(a.id), "motion": "zoom_in", "tight": 1.0, "focus_x": 0.5, "focus_y": 0.5, "sec": None, "video_start": a.best_start}]})
    motions = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
    for i, scene in enumerate(scenes[1:], 1):
        for shot in scene["shots"]:
            shot["motion"] = motions[i % len(motions)]
    hook_text = (post.selected_hook or {}).get("text", "")
    if hook_text:
        scenes[0]["caption"] = wrap_hook(hook_text)
        scenes[0]["narration"] = hook_text
    hook_asset = scenes[0]["shots"][0]["asset_id"]
    template = TEMPLATES[post.template_key]
    profile = getattr(post.stylist, "reel_profile", None)
    brand = profile.display_name() if profile else (post.stylist.salon_name or post.stylist.display_name)
    cta_text = {"予約": getattr(profile, "default_cta", "") or "ご相談はDMかプロフィールから", "フォロー": "フォローで次の投稿も", "保存": "保存して見返してください"}[template["cta"]]
    menu = "・".join(post.menu_items) if post.menu_items else "施術"
    return {
        "theme_title": post.theme_title or template["label"],
        "hook_type": "見本",
        "scenes": scenes,
        "cta": {"title": brand, "text": cta_text, "narration": "", "background_asset_id": hook_asset},
        "episode_ids": [],
        "bgm_category": template["bgm_categories"][0],
        "ig_caption": _mock_caption(post, menu, template),
        "hashtags": [m.replace(" ", "") for m in (post.menu_items or [])][:3] + ["ヘアカラー", "美容師", "フリーランス美容師", "髪質改善", "ヘアスタイル"],
        "yt_title": post.theme_title or template["label"],
        "yt_description": f"{brand}の{template['label']}です。",
        "notes_for_stylist": "",
    }


def _mock_caption(post: ReelPost, menu: str, template: dict) -> str:
    if post.post_type:
        from .content import mock_caption

        return mock_caption(post, "仕上がりだけでなく、3週間後もきれいでいられるように配合しています。")
    return f"{post.theme_title or template['label']}\n\n{menu}の記録です。同じお悩みの方は、DMかプロフィールからご相談ください。"


def apply_script(post: ReelPost, script: dict, notes: list[str] | None = None) -> None:
    post.script = script
    post.theme_title = script.get("theme_title") or post.theme_title
    post.episode_ids = [str(e) for e in script.get("episode_ids", [])]
    post.ig_caption = script.get("ig_caption", "")
    post.hashtags = [h.lstrip("#＃") for h in script.get("hashtags", []) if h.strip("#＃ ")]
    post.yt_title = script.get("yt_title", "")[:95]
    post.yt_description = script.get("yt_description", "")
    post.bgm = pick_bgm(post, script.get("bgm_category"))
    post.notes = [n for n in (notes or []) if n] + ([script["notes_for_stylist"]] if script.get("notes_for_stylist") else [])
    post.pii_check = pii_summary(script, forbidden_terms(post))
    post.status = "REVIEW"
    post.save()
    if post.episode_ids:
        for ep in Episode.objects.filter(stylist=post.stylist, id__in=[int(e) for e in post.episode_ids if e.isdigit()]):
            EpisodeUsage.objects.create(episode=ep)


def pii_summary(script: dict, terms: set[str]) -> dict:
    findings = []
    for label, text in script_texts(script):
        result = pii_module.check_text(text, terms)
        for f in result.findings:
            findings.append({"kind": f.kind, "text": f.text, "severity": f.severity, "field": label})
    return {"passed": not any(f["severity"] == "error" for f in findings), "findings": findings}


def pick_bgm(post: ReelPost, category: str | None):
    categories = [category] if category else []
    categories += [c for c in TEMPLATES[post.template_key]["bgm_categories"] if c not in categories]
    for cat in categories:
        track = BgmTrack.usable().filter(category=cat).order_by(F("last_used_at").asc(nulls_first=True), "used_count").first()
        if track:
            return track
    return BgmTrack.usable().order_by(F("last_used_at").asc(nulls_first=True)).first()
