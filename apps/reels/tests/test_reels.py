import io
from datetime import datetime
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.dates import today_local
from apps.core.media_access import allowed
from apps.karte.models import Karte, KartePhoto
from apps.reels import services
from apps.reels.ai import check_script, generate_script, mock_script
from apps.reels.engine.render import duck_envelope, fit_size, shot_visual, split_shots
from apps.reels.models import BgmTrack, ReelPost
from apps.reels.publishing import AI_NOTICE, best_time, caption_for
from apps.reels.recipes import TEMPLATES, choose_template, shot_list, theme_for


def _png(color=(200, 160, 140)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 500), color).save(buf, format="PNG")
    return buf.getvalue()


def _upload(name="a.png"):
    return SimpleUploadedFile(name, _png(), content_type="image/png")


@pytest.fixture
def karte(stylist, customer):
    k = Karte.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), treatment_summary="ブラウンにカラー", menu_items=["カラー"], concerns=["色落ちが早い"], results="赤みが出にくい配合に", private_notes="秘密")
    KartePhoto.objects.create(karte=k, image=SimpleUploadedFile("after.png", _png(), content_type="image/png"), sns_ok=True, face_visible=False)
    KartePhoto.objects.create(karte=k, image=SimpleUploadedFile("face.png", _png(), content_type="image/png"), sns_ok=True, face_visible=True)  # 顔出しNGなので取り込まれない
    KartePhoto.objects.create(karte=k, image=SimpleUploadedFile("ng.png", _png(), content_type="image/png"), sns_ok=False, face_visible=False)
    return k


# ------------------------------------------------------------------ 型


def test_choose_template_by_menu_and_purpose():
    assert choose_template(["カラー"], []) == "before_after"
    assert choose_template(["トリートメント"], []) == "process"
    assert choose_template([], [], purpose="first_timer") == "self_intro"
    assert choose_template([], [], purpose="repeat") == "care_tips"


def test_choose_template_rotation_avoids_three_in_a_row():
    key = choose_template([], ["daily", "daily"])
    assert key != "daily"
    assert choose_template([], ["before_after", "process", "care_tips", "daily"]) == "stylist_story"


def test_shot_list_sorted_by_work_and_theme():
    slots = shot_list("before_after")
    assert [s["work"] for s in slots] == sorted(s["work"] for s in slots)
    assert all({"key", "frame", "what", "how", "caption", "narration"} <= set(s) for s in slots)
    assert theme_for("before_after", ["カラー"]) == "カラーのビフォーアフター"
    assert set(TEMPLATES) == {"before_after", "process", "care_tips", "stylist_story", "daily", "self_intro", "color_catalog"}


# ------------------------------------------------------------------ 開始・素材


def test_start_post_imports_only_usable_photos(stylist, customer, karte):
    post = services.start_post(stylist, karte=karte, uses_story=True)
    assert post.post_type == "" and post.template_key == "" and post.stage == 0  # 型はあとで決める（素材から始める）
    assert post.customer == customer and post.face_allowed is False and post.uses_story is True
    assert post.assets.count() == 1  # 顔あり・掲載NGは取り込まない
    asset = post.assets.first()
    assert asset.source == "karte" and asset.kind == "photo" and asset.mime == "image/jpeg" and asset.role == "after"
    assert post.usable_assets().count() == 1


def test_start_post_without_karte_allows_face(stylist):
    post = services.start_post(stylist, template_key="daily")
    assert post.face_allowed is True and post.customer is None
    assert post.shot_list[0]["key"] == "open"


def test_save_asset_face_filter(stylist, customer, karte):
    post = services.start_post(stylist, karte=karte, import_photos=False)
    a = services.save_asset(post, _upload(), "a.png", "image/png", 1000, "photo", "before", face_visible=True)
    b = services.save_asset(post, _upload(), "b.png", "image/png", 1000, "photo", "after_back", face_visible=False)
    assert set(post.usable_assets().values_list("id", flat=True)) == {b.id}
    assert a.taken_at is not None and a.width == 300


# ------------------------------------------------------------------ 台本


def test_generate_script_mock_and_pii_check(stylist, customer, karte, settings):
    settings.AI_FAKE = True
    post = services.start_post(stylist, karte=karte, import_photos=True, template_key="before_after")
    services.save_asset(post, _upload(), "b.png", "image/png", 1000, "photo", "after_back")
    services.save_asset(post, _upload(), "c.png", "image/png", 1000, "photo", "bowl")
    script, notes = generate_script(post)
    post.refresh_from_db()
    assert post.status == "REVIEW"
    assert script["scenes"] and script["cta"]["background_asset_id"]
    assert post.pii_check["passed"] is True
    assert post.hashtags and all(not h.startswith("#") for h in post.hashtags)
    assert notes and "お試し" in notes[0]
    assert "山田" not in post.ig_caption


def test_check_script_detects_problems(stylist, customer, karte):
    post = services.start_post(stylist, karte=karte, import_photos=True, template_key="before_after")
    assets = list(post.usable_assets())
    script = mock_script(post, assets)
    assert check_script(script, assets, post) == []
    bad = {**script, "scenes": [{**script["scenes"][0], "caption": "山田さんのカラー", "shots": [{**script["scenes"][0]["shots"][0], "asset_id": "nope"}]}]}
    problems = check_script(bad, assets, post)
    assert any("素材ID" in p for p in problems)
    assert any("個人情報" in p for p in problems)


def test_edit_script_swaps_asset_and_text(stylist, customer, karte):
    post = services.start_post(stylist, karte=karte, import_photos=True, template_key="before_after")
    other = services.save_asset(post, _upload(), "b.png", "image/png", 1000, "photo", "extra")
    generate_script(post)
    post.refresh_from_db()
    services.edit_script(post, [{"scene": 0, "caption": "新しい文字", "narration": "新しいセリフ"}, {"scene": 0, "shot": 0, "asset_id": str(other.id)}, {"scene": -1, "cta_text": "予約はDMで"}])
    post.refresh_from_db()
    assert post.script["scenes"][0]["caption"] == "新しい文字"
    assert post.script["scenes"][0]["shots"][0]["asset_id"] == str(other.id)
    assert post.script["cta"]["text"] == "予約はDMで"
    with pytest.raises(ValueError):
        services.edit_script(post, [{"scene": 0, "shot": 0, "asset_id": "nope"}])


def test_pick_bgm_prefers_template_category(stylist, customer, karte, settings):
    settings.BGM_REQUIRE_LICENSE = False
    BgmTrack.objects.create(title="calm1", category="calm", file=SimpleUploadedFile("c.mp3", b"\x00" * 100))
    BgmTrack.objects.create(title="bright1", category="bright", file=SimpleUploadedFile("b.mp3", b"\x00" * 100))
    post = services.start_post(stylist, karte=karte, import_photos=True, template_key="before_after")
    generate_script(post)
    post.refresh_from_db()
    assert post.bgm.category == "bright"  # before_after → bright が先頭


# ------------------------------------------------------------------ 投稿文・時間


def test_caption_for_platforms(stylist):
    post = ReelPost(stylist=stylist, template_key="daily", ig_caption="本文", hashtags=["美容師", "カラー"], yt_description="説明", narration_mode="ai", ai_label=True)
    ig = caption_for(post, "instagram")
    assert ig.startswith("本文") and AI_NOTICE in ig and "#美容師 #カラー" in ig
    post.narration_mode = "none"
    assert AI_NOTICE not in caption_for(post, "instagram")
    post.narration_mode = "ai"
    post.ig_caption = "あ" * 600
    th = caption_for(post, "threads")
    assert len(th) <= 500 and AI_NOTICE in th and th.count("#") == 1
    assert caption_for(post, "youtube").startswith("説明")


def test_best_time(settings):
    settings.SOCIAL_BEST_HOURS = "12,19"
    tz = timezone.get_current_timezone()
    assert best_time(datetime(2026, 10, 20, 10, 0, tzinfo=tz)).hour == 12
    assert best_time(datetime(2026, 10, 20, 11, 50, tzinfo=tz)).hour == 19
    nxt = best_time(datetime(2026, 10, 20, 20, 0, tzinfo=tz))
    assert nxt.day == 21 and nxt.hour == 12


# ------------------------------------------------------------------ エンジン（純粋関数）


def test_split_shots_and_duck_envelope():
    plan = split_shots({"shots": [{"sec": 1.0}, {}, {}]}, 90)
    assert [n for _, n in plan] == [30, 30, 30]
    plan = split_shots({"shots": [{"sec": 1.0}, {"sec": 1.0}]}, 90)
    assert sum(n for _, n in plan) == 90
    env = duck_envelope([(1.0, 2.0), (2.5, 3.5), (10, 11)], {"merge_gap_sec": 0.8, "duck_attack_sec": 0.2, "duck_release_sec": 0.3, "level_base": 0.7, "level_duck": 0.45})
    assert env.startswith("0.7-0.250*min(1,") and env.count("clip(") == 4  # 近い2区間はまとまる
    assert fit_size("あいうえお", 92) == 92
    assert fit_size("あ" * 20, 92) == 44


# ------------------------------------------------------------------ メディアの閲覧権限


def test_media_access_rules(stylist, other_stylist):
    class Anon:
        is_authenticated = False
        is_staff = False

    assert allowed(Anon(), f"stylist_{stylist.id}/reels/renders/abc.mp4") is True
    assert allowed(Anon(), f"stylist_{stylist.id}/reels/xyz.jpg") is False
    assert allowed(stylist.user, f"stylist_{stylist.id}/photos/a.jpg") is True
    assert allowed(other_stylist.user, f"stylist_{stylist.id}/photos/a.jpg") is False
    assert allowed(Anon(), "bgm/x.mp3") is False and allowed(stylist.user, "bgm/x.mp3") is True
    assert allowed(stylist.user, "random/file") is False


def test_media_view_serves_owner_only(client_logged, stylist, other_stylist, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.MEDIA_ACCEL_REDIRECT = False
    (tmp_path / f"stylist_{stylist.id}" / "photos").mkdir(parents=True)
    (tmp_path / f"stylist_{stylist.id}" / "photos" / "a.jpg").write_bytes(b"x")
    assert client_logged.get(f"/media/stylist_{stylist.id}/photos/a.jpg").status_code == 200
    assert Client().get(f"/media/stylist_{stylist.id}/photos/a.jpg").status_code == 404
    other = Client()
    other.force_login(other_stylist.user)
    assert other.get(f"/media/stylist_{stylist.id}/photos/a.jpg").status_code == 404
    assert client_logged.get("/media/../settings.py").status_code == 404


# ------------------------------------------------------------------ 接続


def test_connect_requires_app_settings(client_logged):
    resp = client_logged.get(reverse("reels:connect_start", kwargs={"platform": "instagram"}))
    assert resp.status_code == 302 and resp.url == reverse("reels:settings")
    resp = client_logged.get(reverse("reels:connect_callback", kwargs={"platform": "instagram"}) + "?state=bad&code=x")
    assert resp.status_code == 302


def test_connect_start_redirects_to_provider(client_logged, settings):
    settings.INSTAGRAM_APP_ID = "123"
    settings.INSTAGRAM_APP_SECRET = "sec"
    resp = client_logged.get(reverse("reels:connect_start", kwargs={"platform": "instagram"}))
    assert resp.status_code == 302 and resp.url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "redirect_uri=" in resp.url and "state=" in resp.url


# ------------------------------------------------------------------ 画面


def test_reel_pages_and_flow(client_logged, stylist, customer, karte):
    """素材 → 型 → フック → 出来上がり（動画）の一連の流れ"""
    assert client_logged.get(reverse("reels:home")).status_code == 200
    assert client_logged.get(reverse("reels:start")).status_code == 302  # GET では作らない
    resp = client_logged.post(reverse("reels:start"), {"karte": karte.pk})
    assert resp.status_code == 302
    post = ReelPost.objects.get(stylist=stylist)
    url = reverse("reels:workspace", kwargs={"pk": post.pk})
    page = client_logged.get(url)
    assert page.status_code == 200 and "型を決める" in page.content.decode()
    # 素材（役割つき）
    up = client_logged.post(reverse("reels:asset_upload", kwargs={"pk": post.pk}), {"file": _upload("b.png"), "role": "after"}, HTTP_X_REQUESTED_WITH="fetch")
    assert up.status_code == 200 and up.json()["asset"]["usable"] is True and up.json()["asset"]["role"] == "after"
    aid = up.json()["asset"]["id"]
    r = client_logged.post(reverse("reels:asset_role", kwargs={"pk": post.pk, "asset_id": aid}), {"role": "before"}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200 and r.json()["asset"]["role"] == "before"
    # 型：おすすめと、素材が足りない型の表示
    body = client_logged.get(url + "?step=type").content.decode()
    assert "AIのおすすめ" in body and "足りない素材" in body
    assert post.recommendations.filter(reaction="pending").exists()
    client_logged.post(reverse("reels:choose_type", kwargs={"pk": post.pk}), {"post_type": "suggestion"})  # アフター2枚が必要 → 選べない
    post.refresh_from_db()
    assert post.post_type == ""
    resp = client_logged.post(reverse("reels:choose_type", kwargs={"pk": post.pk}), {"post_type": "before_after", "mode": "manual"})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.post_type == "before_after" and post.template_key == "before_after" and post.output_format == "reel"
    assert post.status == "DRAFT" and len(post.hooks) == 3 and post.stage == 2  # Fake は同期でフックができる
    assert post.recommendations.first().reaction in ("accepted", "changed")
    assert "このフックで作る" in client_logged.get(url).content.decode()
    # フックを選ぶ → 台本 → 動画作成の依頼（FFmpeg は呼ばない）
    with mock.patch("apps.reels.content.services.request_render") as rr, mock.patch("apps.reels.content.services.options", return_value={"ffmpeg_available": True}):
        resp = client_logged.post(reverse("reels:choose_hook", kwargs={"pk": post.pk}), {"hook": "0"})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.selected_hook["text"] == post.hooks[0]["text"]
    assert post.script and post.script["scenes"][0]["narration"] == post.selected_hook["text"]
    assert post.status == "REVIEW" and post.hype_check["passed"] is True and post.caption_check
    rr.assert_called_once()
    assert client_logged.get(url).status_code == 200
    # 台本の保存
    resp = client_logged.post(reverse("reels:script_edit", kwargs={"pk": post.pk}), {"caption_0": "新しい", "narration_0": "セリフ", "cta_text": "DMで", "ig_caption": "本文", "hashtags": "#a #b", "yt_title": "題", "yt_description": "説明", "narration_mode": "none", "bgm": "", "action": "save"})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.script["scenes"][0]["caption"] == "新しい" and post.hashtags == ["a", "b"] and post.narration_mode == "none"
    assert client_logged.get(reverse("reels:status", kwargs={"pk": post.pk})).json()["status"] == "REVIEW"
    assert client_logged.get(reverse("reels:history")).status_code == 200
    assert client_logged.get(reverse("reels:settings")).status_code == 200
    resp = client_logged.post(reverse("reels:settings"), {"focus_concerns_text": "色落ち\n根元の境目", "purpose": "weekday_daytime", "favorite_types": ["before_after"], "avoid_types": ["personality"], "posts_per_week": 3, "brand_name": "salon", "default_cta": "DM", "narration_mode": "none", "voice_name": "Sulafat", "speaker_gender": "女性", "speaker_age": "30代", "ai_label": "on", "post_to_instagram": "on"})
    assert resp.status_code == 302
    profile = services.profile_of(stylist)
    assert profile.focus_concerns == ["色落ち", "根元の境目"] and profile.purpose == "weekday_daytime" and profile.avoid_types == ["personality"] and profile.posts_per_week == 3
    # 削除
    assert client_logged.post(reverse("reels:delete", kwargs={"pk": post.pk})).status_code == 302
    assert not ReelPost.objects.filter(pk=post.pk).exists()

def test_tenant_isolation(client_logged, other_stylist):
    post = services.start_post(other_stylist, template_key="daily")
    assert client_logged.get(reverse("reels:workspace", kwargs={"pk": post.pk})).status_code == 404


def test_script_edit_blocks_render_on_pii(client_logged, stylist, customer, karte):
    post = services.start_post(stylist, karte=karte, import_photos=True, template_key="before_after")
    services.save_asset(post, _upload(), "b.png", "image/png", 1000, "photo", "after_back")
    generate_script(post)
    post.refresh_from_db()
    with mock.patch("apps.reels.services.request_render") as rr:
        resp = client_logged.post(reverse("reels:script_edit", kwargs={"pk": post.pk}), {"caption_0": "山田さんの仕上がり", "action": "render", "ig_caption": "x", "hashtags": "", "yt_title": "", "yt_description": "", "narration_mode": "none"})
    assert resp.status_code == 302
    rr.assert_not_called()
    post.refresh_from_db()
    assert post.pii_errors


# ------------------------------------------------------------------ 動画作成（FFmpeg があるときだけ）


def test_render_smoke(stylist, customer, karte, settings, tmp_path):
    from apps.reels.engine.audio import ffmpeg_available
    from apps.reels.engine.render import RenderError, font_path

    if not ffmpeg_available():
        pytest.skip("ffmpeg が無い環境")
    try:
        font_path()
    except RenderError:
        pytest.skip("日本語フォントが無い環境")
    settings.MEDIA_ROOT = tmp_path
    settings.RENDER_WORK_DIR = tmp_path / "work"
    from django.core.files.storage import FileSystemStorage, default_storage

    default_storage._wrapped = FileSystemStorage(location=str(tmp_path), base_url="/media/")
    post = services.start_post(stylist, template_key="daily")
    a = services.save_asset(post, _upload(), "a.png", "image/png", 1000, "photo", "open")
    b = services.save_asset(post, _upload("b.png"), "b.png", "image/png", 1000, "photo", "prep")
    post.narration_mode = "none"
    post.script = {
        "scenes": [
            {"role": "フック", "caption": "テスト", "narration": "", "shots": [{"asset_id": str(a.id), "motion": "zoom_in", "tight": 1.0, "focus_x": 0.5, "focus_y": 0.5, "sec": 1.0, "video_start": None}]},
            {"role": "中身", "caption": "二つ目", "narration": "", "shots": [{"asset_id": str(b.id), "motion": "pan_left", "tight": 1.0, "focus_x": 0.5, "focus_y": 0.5, "sec": 1.0, "video_start": None}]},
        ],
        "cta": {"title": "salon", "text": "フォロー", "narration": "", "background_asset_id": str(a.id)},
    }
    post.save()
    from apps.reels.render_service import render_post

    log = render_post(post)
    post.refresh_from_db()
    assert post.status == "READY" and post.video and post.thumbnail
    assert (tmp_path / post.video.name).exists() and post.duration_sec and post.duration_sec >= 3.5
    assert "OK" in log


def test_karte_photos_fill_story_slots_not_optional_salon(stylist, customer, karte):
    """カルテの写真（たいてい仕上がり）は、撮影順で先頭の「店内（任意）」ではなく台本の先頭の必須項目に入る"""
    post = services.start_post(stylist, template_key="before_after", karte=karte)
    asset = post.assets.get()
    assert asset.slot == "after_hero"
    assert asset.slot != "salon"


def test_video_start_shifts_back_so_long_cut_does_not_freeze(tmp_path):
    """ナレーションでカットが伸びたら、動画の開始位置を前にずらして最後まで動くようにする"""
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    _, _, pre, kind = shot_visual({"video": str(clip), "video_start": 3.0, "video_duration": 5.0}, 120)  # 4秒のカット
    assert kind == "video" and pre == ("-ss", "0.95")
    _, _, pre, _ = shot_visual({"video": str(clip), "video_start": 1.0, "video_duration": 5.0}, 60)  # 収まるならそのまま
    assert pre == ("-ss", "1.00")
    _, _, pre, _ = shot_visual({"video": str(clip), "video_start": 2.0, "video_duration": 3.0}, 150)  # クリップより長いカットは先頭から
    assert pre == ("-ss", "0.00")


# ------------------------------------------------------------------ 型の追加（自己紹介・作品集・1日）と見本


def test_face_default_follows_who_is_featured(stylist):
    assert services.start_post(stylist, template_key="self_intro").face_allowed is True  # 本人が主役
    assert services.start_post(stylist, template_key="daily").face_allowed is True
    assert services.start_post(stylist, template_key="color_catalog").face_allowed is False  # お客様の作品集
    assert services.start_post(stylist, template_key="before_after").face_allowed is False


def test_theme_for_new_templates():
    assert theme_for("self_intro") == "はじめまして（自己紹介）"
    assert theme_for("color_catalog") == "デザインカラーの作品集"
    assert theme_for("color_catalog", ["ブリーチ"]) == "ブリーチの作品集"
    assert theme_for("daily") == "スタイリストの1日"


def test_mock_script_fills_placeholders_and_uses_all_works(stylist):
    stylist.salon_name, stylist.salon_access = "SOYON なんば店", "なんば駅から徒歩1分"
    stylist.save()
    post = services.start_post(stylist, template_key="self_intro", menu_items=["ハイライト"])
    for slot in ("greeting", "works", "works", "works", "counsel"):
        services.save_asset(post, _upload(), "a.png", "image/png", 100, "photo", slot)
    script = mock_script(post, list(post.usable_assets()))
    hook = script["scenes"][0]
    assert hook["caption"] == "はじめまして\nSOYON なんば店の佐藤です"
    assert "{" not in "".join(s["caption"] + s["narration"] for s in script["scenes"])
    works = next(s for s in script["scenes"] if s["role"] == "得意")
    assert len(works["shots"]) == 3 and works["caption"] == "得意なのは\nハイライト"


def test_mock_script_daily_area_and_time_prefix(stylist):
    stylist.salon_access = "なんば駅から徒歩1分"
    stylist.save()
    post = services.start_post(stylist, template_key="daily")
    services.save_asset(post, _upload(), "a.png", "image/png", 100, "photo", "open")
    prep = services.save_asset(post, _upload(), "b.png", "image/png", 100, "photo", "prep")
    prep.taken_at = timezone.make_aware(datetime(2026, 10, 18, 8, 45))
    prep.save()
    script = mock_script(post, list(post.usable_assets()))
    assert script["scenes"][0]["caption"] == "なんばの美容師の1日"
    assert script["scenes"][1]["caption"] == "8:45 開店前の準備"


def test_samples_skip_when_assets_missing(stylist, tmp_path):
    from apps.reels.samples import SAMPLES, available, create_sample_posts

    assert {s["template"] for s in SAMPLES} == {"color_catalog", "self_intro", "stylist_story", "daily"}
    assert not available(SAMPLES[0], tmp_path, tmp_path)
    assert create_sample_posts(stylist, tmp_path, tmp_path) == []


def test_sample_catalog_post_from_photos(stylist, tmp_path):
    from apps.reels.samples import SAMPLES, create_sample_post

    catalog = next(s for s in SAMPLES if s["key"] == "catalog")
    for name in catalog["assets"]:
        (tmp_path / f"{name}.jpg").write_bytes(_png())
    stylist.salon_name, stylist.salon_access = "SOYON なんば店", "なんば駅から徒歩1分"
    stylist.save()
    post = create_sample_post(stylist, catalog, tmp_path, tmp_path)
    assert post.status == "REVIEW" and post.template_key == "color_catalog" and post.face_allowed is False
    assert post.usable_assets().count() == post.assets.count() - 2  # 顔ありの2枚は使えない
    assert post.script["cta"]["title"] == "SOYON なんば店"
    assert post.yt_title == "ブリーチで出せる色、6パターン【なんばの美容室】"
    assert post.pii_check["passed"] is True
