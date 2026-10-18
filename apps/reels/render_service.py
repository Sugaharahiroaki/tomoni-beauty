"""投稿の台本から、エンジン用の台本を組み立てて動画を作る（バックグラウンドタスクから呼ばれる）。"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from .engine.narrators import OwnVoiceNarrator, SilentNarrator, TTSNarrator
from .engine.render import load_settings, render_reel
from .engine.tts import GeminiTTS
from .models import NarrationTake, ReelPost, UsageLog

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).with_name("prompts")
TTS_USD_PER_SEC = 20.0 / 1e6 * 25

SITUATIONS = {
    "before_after": "a customer just asked how the color will hold up, and the stylist is answering while gently checking the hair, a little proud of the result.",
    "process": "someone off camera asked what the stylist always does before coloring, and they are explaining calmly while working.",
    "care_tips": "a regular customer asked how to keep the color at home, and the stylist is kindly explaining like a friendly expert.",
    "stylist_story": "someone quietly asked why they became a hairstylist. They answer in their own words, remembering, sincere and slightly nostalgic, never dramatic.",
    "daily": "the stylist is casually talking to a coworker while preparing the salon, relaxed and natural.",
}


def speaker_notes(post: ReelPost) -> str:
    profile = getattr(post.stylist, "reel_profile", None)
    gender = "woman" if (profile and profile.speaker_gender == "女性") else "man"
    age = (profile.speaker_age if profile else "") or "30s"
    return "\n\n".join([f"The speaker is a {age} Japanese {gender} who works as a freelance hairstylist.", "Situation: " + SITUATIONS.get(post.template_key, SITUATIONS["daily"])])


def engine_script(post: ReelPost) -> dict:
    script = post.script or {}
    assets = {str(a.id): a for a in post.assets.all()}

    def shot_for(s):
        asset = assets.get(s.get("asset_id"))
        if asset is None:
            raise ValueError("台本の素材が見つかりません。台本を作り直してください。")
        shot = {k: s.get(k) for k in ("motion", "tight", "focus_x", "focus_y", "sec")}
        shot["tight"] = shot["tight"] or 1.0
        shot["focus_x"] = 0.5 if shot["focus_x"] is None else shot["focus_x"]
        shot["focus_y"] = 0.5 if shot["focus_y"] is None else shot["focus_y"]
        if asset.kind == "video":
            shot["video"] = asset.file.path
            shot["video_start"] = s.get("video_start") if s.get("video_start") is not None else (asset.best_start or 0)
            shot["photo"] = asset.poster_path or asset.file.path
        else:
            shot["photo"] = asset.file.path
        return shot

    scenes = []
    for i, scene in enumerate(script.get("scenes", [])):
        scenes.append({"caption": scene.get("caption", ""), "caption_style": "hook" if i == 0 else "normal", "narration": scene.get("narration", "") if post.narration_mode != "none" else "", "duration": 2.0, "shots": [shot_for(s) for s in scene.get("shots", [])]})
    cta = script.get("cta") or {}
    bg = assets.get(cta.get("background_asset_id")) or next(iter(assets.values()))
    bg_path = bg.poster_path if bg.kind == "video" else bg.file.path
    profile = getattr(post.stylist, "reel_profile", None)
    result = {
        "speaker_notes": speaker_notes(post),
        "scenes": scenes,
        "cta": {"photo": bg_path or bg.file.path, "title": cta.get("title") or (profile.display_name() if profile else post.stylist.display_name), "text": cta.get("text", ""), "narration": cta.get("narration", "") if post.narration_mode != "none" else "", "duration": 2.0},
    }
    if post.bgm and post.bgm.file:
        result["bgm"] = {"file": post.bgm.file.path, "start": 0, "category": post.bgm.category, "level_duck": post.bgm.level_duck, "level_base": post.bgm.level_base}
    return result


def narrator_for(post: ReelPost, engine_settings: dict):
    cache = Path(settings.MEDIA_ROOT) / f"stylist_{post.stylist_id}" / "reels" / "cache" / "tts"
    tts = None
    if settings.GEMINI_API_KEY and post.narration_mode != "none":
        profile = getattr(post.stylist, "reel_profile", None)
        tts = TTSNarrator(GeminiTTS(settings.GEMINI_API_KEY, engine_settings["tts"]["model"], getattr(profile, "voice_name", "") or engine_settings["tts"]["voice"], (PROMPTS / "tts_style.md").read_text(encoding="utf-8"), (PROMPTS / "tts_hook.md").read_text(encoding="utf-8"), engine_settings["narration"]["loudness_lufs"], cache))
    if post.narration_mode == "own":
        takes = {t.scene_index: t.file.path for t in NarrationTake.objects.filter(post=post)}
        return OwnVoiceNarrator(takes, engine_settings["narration"]["loudness_lufs"], cache / "own", fallback=tts)
    return tts or SilentNarrator()


def render_post(post: ReelPost) -> str:
    """動画を作って投稿に保存する。戻り値はログの文字列"""
    engine_settings = load_settings()
    script = engine_script(post)
    narrator = narrator_for(post, engine_settings)
    post.render_count += 1
    base = Path(settings.MEDIA_ROOT) / f"stylist_{post.stylist_id}" / "reels" / "renders"
    out = base / f"{post.id.hex}_{post.render_count}.mp4"
    thumb = out.with_suffix(".jpg")
    work = Path(settings.RENDER_WORK_DIR) / post.id.hex
    try:
        result = render_reel(script, out, work, narrator=narrator, settings=engine_settings, thumbnail_path=thumb)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    previous = {post.video.name, post.thumbnail.name} - {""}
    post.video.name = out.relative_to(settings.MEDIA_ROOT).as_posix()
    post.thumbnail.name = thumb.relative_to(settings.MEDIA_ROOT).as_posix()
    post.duration_sec = round(result["total"], 2)
    post.status = "READY"
    post.error = ""
    post.save()
    storage = post.video.storage
    for name in previous - {post.video.name, post.thumbnail.name}:
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001
            pass
    if post.bgm_id:
        type(post.bgm).objects.filter(pk=post.bgm_id).update(used_count=F("used_count") + 1, last_used_at=timezone.now())

    tts = getattr(narrator, "tts", None) or getattr(getattr(narrator, "fallback", None), "tts", None)
    if tts and getattr(tts, "audio_seconds", 0):
        UsageLog.objects.create(stylist=post.stylist, post=post, provider="google", model=engine_settings["tts"]["model"], operation="tts", audio_seconds=tts.audio_seconds, cost_usd=tts.audio_seconds * TTS_USD_PER_SEC)
    return "\n".join(result["notes"]) + "\n" + result["log"]
