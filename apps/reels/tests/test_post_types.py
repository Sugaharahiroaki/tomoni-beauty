"""SNS投稿の「型」：おすすめの採点、フック、型ごとの出力、チェック、記録"""
import io
import json
from datetime import date, time, timedelta
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.dates import today_local
from apps.karte.models import Karte, KartePhoto
from apps.reels import services
from apps.reels.checks import caption_elements, hype_findings, hype_summary
from apps.reels.content import generate_content, mock_feed, mock_stories
from apps.reels.context import build_sns_context
from apps.reels.hooks import annotate, generate_hooks, hook_types_for, mock_hooks
from apps.reels.models import ReelPost, TypeRecommendation
from apps.reels.post_types import POST_TYPES, composition_for, decide_format, missing_for
from apps.reels.recommend import Recommendation, build_reason, choose_theme, rank, recommend_for, score_types, week_count, weekly_plan


def _png(color=(200, 160, 140)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 500), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def karte(stylist, customer):
    k = Karte.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), treatment_summary="ブラウンにカラー", menu_items=["カラー"], concerns=["色落ちが早い"], results="赤みが出にくい配合に", private_notes="秘密")
    KartePhoto.objects.create(karte=k, image=SimpleUploadedFile("after.png", _png(), content_type="image/png"), sns_ok=True, face_visible=False, role="after")
    return k


def _photo(post, role="after", name="a.png"):
    return services.save_asset(post, SimpleUploadedFile(name, _png(), content_type="image/png"), name, "image/png", 100, "photo", "", role=role)


W = {"purpose": 3.0, "bias": 4.0, "streak": 3.0, "availability": 2.0, "results": 2.0, "favorite": 1.0, "accept": 1.0, "skip": 1.5}
FULL = {"before": 1, "after": 3, "process": 1, "self": 1, "other": 0, "video": 1, "photo": 4}


# ------------------------------------------------------------------ 型と出来上がる形


def test_format_follows_materials():
    assert decide_format("tips", {"video": 0, "photo": 1}) == "feed"
    assert decide_format("tips", {"video": 1, "photo": 0}) == "reel"  # 動画が1本でもあれば動画
    assert decide_format("before_after", {"video": 0, "photo": 2}) == "reel"  # 写真だけでも動画
    assert decide_format("personality", {"video": 0, "photo": 0}) == "stories"
    assert decide_format("suggestion", {"video": 0, "photo": 3}) == "feed"


def test_missing_materials_messages():
    assert missing_for("before_after", {"after": 1, "before": 0, "video": 0}) == ["ビフォーの写真か、施術中の動画を1つ"]
    assert missing_for("before_after", {"after": 1, "before": 0, "video": 1}) == []
    assert missing_for("process_reel", {"video": 0}) == ["施術中の動画を1本（カット・シャンプー・塗布など）"]
    assert missing_for("suggestion", {"after": 1}) == ["アフター（仕上がり）の写真を2枚以上"]
    assert missing_for("tips", {}) == [] and missing_for("personality", {}) == []


def test_composition_for_personality():
    assert composition_for("personality", {"self": 1}, has_intro=False) == "self_intro"
    assert composition_for("personality", {"self": 1}, has_intro=True) == "stylist_story"
    assert composition_for("personality", {"self": 3}, has_intro=True) == "daily"
    assert composition_for("suggestion", {}) == "color_catalog"


# ------------------------------------------------------------------ おすすめの採点（ルールベース）


def test_bias_and_streak_lower_recent_types():
    scores, _ = score_types(counts=FULL, purpose="general", recent_types=["tips", "tips", "before_after"], w=W)
    assert scores["tips"]["parts"]["bias"] == pytest.approx(-4.0 * 2 / 3, abs=0.001)
    assert scores["tips"]["parts"]["streak"] == -3.0
    assert scores["before_after"]["parts"]["streak"] == 0.0
    assert rank(scores)[0] != "tips"


def test_missing_materials_exclude_type_and_say_what_to_add():
    scores, missing = score_types(counts={"after": 1, "before": 0, "video": 0, "photo": 1}, purpose="nomination", w=W)
    assert scores["before_after"]["excluded"] == "素材が足りない" and missing["before_after"]
    assert scores["process_reel"]["excluded"] and scores["suggestion"]["excluded"]
    assert "before_after" not in rank(scores)
    assert rank(scores)[0] in ("tips", "personality")


def test_no_materials_known_skips_exclusion():
    scores, missing = score_types(counts=None, purpose="nomination", w=W)
    assert not missing and all(not s["excluded"] for s in scores.values())
    assert rank(scores)[0] == "before_after"


def test_purpose_fit_and_availability():
    s1, _ = score_types(counts=FULL, purpose="repeat", w=W)
    assert rank(s1)[0] == "tips"
    s2, _ = score_types(counts=FULL, purpose="general", open_ratio=1.0, w=W)
    assert s2["before_after"]["parts"]["availability"] == 2.0 and s2["tips"]["parts"]["availability"] == pytest.approx(0.6)
    s3, _ = score_types(counts=FULL, purpose="general", open_ratio=None, w=W)
    assert all(s["parts"]["availability"] == 0.0 for s in s3.values())


def test_preferences_and_reactions():
    scores, _ = score_types(counts=FULL, purpose="general", favorites=["suggestion"], avoid=["before_after"], w=W)
    assert scores["suggestion"]["parts"]["favorite"] == 1.0 and scores["before_after"]["excluded"] == "避けたい型"
    reactions = {"tips": {"n": 4, "accepted": 4, "skipped": 0}, "personality": {"n": 4, "accepted": 0, "skipped": 4}}
    scores, _ = score_types(counts=FULL, purpose="general", reactions_by_type=reactions, w=W)
    assert scores["tips"]["parts"]["accept"] > 0 and scores["personality"]["parts"]["skip"] < 0


def test_results_have_small_effect_with_little_data():
    few = {"tips": {"n": 1, "avg": 20.0}, "before_after": {"n": 1, "avg": 5.0}}
    many = {"tips": {"n": 9, "avg": 20.0}, "before_after": {"n": 9, "avg": 5.0}}
    s_few, _ = score_types(counts=FULL, purpose="general", results_by_type=few, w=W)
    s_many, _ = score_types(counts=FULL, purpose="general", results_by_type=many, w=W)
    assert 0 < s_few["tips"]["parts"]["results"] < s_many["tips"]["parts"]["results"]
    assert s_few["tips"]["parts"]["results"] == pytest.approx(2.0 * 0.25 * min(20 / 12.5 - 1, 1), abs=0.01)


def test_rank_falls_back_when_everything_is_excluded():
    scores, _ = score_types(counts={"after": 0, "video": 0, "photo": 0}, purpose="general", avoid=["tips", "personality"], w=W)
    assert rank(scores)  # 全部除外でも何かは返す


def test_reason_mentions_biggest_factors():
    scores, _ = score_types(counts=FULL, purpose="nomination", recent_types=["tips", "tips"], open_ratio=1.0, w=W)
    reason = build_reason("before_after", scores, "nomination", ["tips", "tips"], 1.0)
    assert reason.startswith("ビフォーアフターがおすすめです。") and ("指名" in reason or "空き枠" in reason)


# ------------------------------------------------------------------ おすすめ（DB込み）・今週のおすすめ・テーマ


def test_recommend_for_records_and_weekly_plan(stylist):
    profile = services.profile_of(stylist)
    profile.posts_per_week = 2
    profile.purpose = "nomination"
    profile.save()
    plan = weekly_plan(stylist)
    assert len(plan) == 2 and plan[0].post_type != plan[1].post_type  # 1本目を直近に加えて2本目を計算
    post = services.start_post(stylist, post_type="before_after", template_key="before_after")
    assert week_count(stylist) == 1 and len(weekly_plan(stylist)) == 1
    rec = recommend_for(stylist, post, counts={"after": 2, "before": 1, "video": 0, "photo": 3})
    assert isinstance(rec, Recommendation) and rec.post_type and rec.reason
    assert rec.post_type == "before_after"  # 目的「指名」に一番合う型（直近は今の投稿を除くので連続の減点なし）
    assert TypeRecommendation.objects.filter(stylist=stylist, post=post).exists() is False  # recommend_for は記録しない（画面側で record する）


def test_choose_theme_matches_karte_then_rotates(stylist, karte):
    profile = services.profile_of(stylist)
    profile.focus_concerns = ["ブリーチ後の色落ち", "くせ・広がり"]
    profile.save()
    post = services.start_post(stylist, karte=karte, import_photos=False)
    assert choose_theme(stylist, post) == "ブリーチ後の色落ち"  # カルテの悩み「色落ちが早い」に近い
    p2 = services.start_post(stylist)
    p2.theme = "ブリーチ後の色落ち"
    p2.post_type = "tips"
    p2.save()
    p3 = services.start_post(stylist)
    assert choose_theme(stylist, p3) == "くせ・広がり"  # 最近使っていない方


# ------------------------------------------------------------------ 素材の役割・型の決定


def test_role_guess_and_slots(stylist):
    post = services.start_post(stylist)
    a = _photo(post, role="", name="first.png")
    assert a.role == "after"  # 1枚目は仕上がり扱い
    b = _photo(post, role="", name="second.png")
    assert b.role in ("before", "after")
    services.choose_type(post, "before_after", "manual", start_hooks=False)
    post.refresh_from_db()
    assert post.template_key == "before_after" and post.output_format == "reel"
    slots = {str(x.id): x.slot for x in post.assets.all()}
    assert set(slots.values()) <= {"after_hero", "after_back", "before"}


def test_choose_type_personality_uses_self_video_and_records_reaction(stylist):
    post = services.start_post(stylist)
    rec = TypeRecommendation.objects.create(stylist=stylist, post=post, post_type="tips", alternatives=["personality"], reason="x")
    services.choose_type(post, "personality", "manual", recommendation=rec, start_hooks=False)
    rec.refresh_from_db()
    assert rec.reaction == "changed" and rec.changed_to == "personality"
    post.refresh_from_db()
    assert post.output_format == "stories" and post.template_key == "stylist_story" and post.face_allowed is True


# ------------------------------------------------------------------ フック


def test_hook_types_and_mock_hooks(stylist):
    post = services.start_post(stylist, post_type="before_after", template_key="before_after")
    post.theme = "色落ち"
    post.save()
    hooks = annotate(mock_hooks(post))
    assert [h["type"] for h in hooks] == hook_types_for("before_after") == ["call", "result", "scene"]
    assert all("色落ち" in h["text"] for h in hooks) and all(h["hype"] == [] for h in hooks)


def test_hooks_flag_hype_and_choose_hook_refuses_them(stylist, settings):
    settings.AI_FAKE = True
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.hooks = annotate([{"type": "call", "text": "誰でも絶対うまくいく", "visual": ""}, {"type": "result", "text": "3週間後もきれい", "visual": ""}, {"type": "surprise", "text": "実は原因は別", "visual": ""}])
    post.save()
    assert post.hooks[0]["hype"] == ["絶対", "誰でも"] or set(post.hooks[0]["hype"]) == {"絶対", "誰でも"}
    with pytest.raises(ValueError):
        services.choose_hook(post, index=0)
    with pytest.raises(ValueError):
        services.choose_hook(post, text="必ず変わります")
    services.choose_hook(post, index=1)
    post.refresh_from_db()
    assert post.selected_hook["text"] == "3週間後もきれい"


def test_hook_regeneration_limit(stylist):
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.hooks = [{"type": "call", "text": "a", "visual": "", "hype": []}]
    post.hook_regenerations = services.MAX_HOOK_REGENERATIONS
    post.save()
    with pytest.raises(ValueError):
        services.request_hooks(post, regenerate=True)


# ------------------------------------------------------------------ 型ごとの出力（AIなし）とチェック


def test_feed_and_stories_mock_outputs(stylist, settings):
    settings.AI_FAKE = True
    from apps.accounts.models import MenuItem

    MenuItem.objects.create(stylist=stylist, name="カット+透明感カラー", price=6500, minutes=120, duration_weeks=6, order=1)
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.theme = "ブリーチ後の色落ち"
    post.selected_hook = {"type": "call", "label": "呼びかけ", "text": "色落ちが早い人へ", "visual": "", "hype": []}
    post.save()
    feed = mock_feed(post)
    assert feed["slides"][0]["title"] == "色落ちが早い人へ" and feed["slides"][-1]["title"].startswith("料金")
    assert "6,500円" in feed["slides"][-1]["text"] and "プロフィールのリンク" in feed["slides"][-1]["text"]
    generate_content(post)
    post.refresh_from_db()
    assert post.status == "READY" and post.output_format == "feed" and len(post.carousel) >= 3
    assert post.caption_check["passed"] is True, post.caption_check  # 6要素がそろう
    assert post.hype_check["passed"] is True and post.pii_check["passed"] is True
    assert post.cover_text == "色落ちが早い人へ" and post.hashtags

    story = services.start_post(stylist, post_type="personality", template_key="stylist_story")
    story.selected_hook = {"type": "surprise", "label": "意外性", "text": "最初は美容師になるつもりなかった", "visual": "", "hype": []}
    story.save()
    data = mock_stories(story)
    assert 2 <= len(data["stories"]) <= 4 and data["stories"][-1]["sticker"]["type"] == "link"  # 予約リンクあり
    generate_content(story)
    story.refresh_from_db()
    assert story.status == "READY" and story.output_format == "stories" and story.tracked_link_id
    assert services.tracked_link_url(story).endswith(f"/r/{story.tracked_link.code}/")


def test_checks():
    assert [f["text"] for f in hype_findings([("x", "絶対に必ず変わる")])] == ["絶対", "必ず"]
    assert hype_summary([("x", "きれいになります")])["passed"] is True
    c = caption_elements("色落ちが早い方へ。3週間後もきれい。所要時間 約120分、料金 6,500円、持ち 約6週間。ご予約はプロフィールのリンクから。")
    assert c["passed"] is True
    c = caption_elements("今日のお客様")
    assert not c["passed"] and len(c["missing"]) >= 4


def test_mark_posted_blocked_by_hype_and_skip_records_reaction(stylist):
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.ig_caption = "誰でも必ずきれいになります"
    post.status = "READY"
    post.save()
    services.update_text_content(post, {"ig_caption": post.ig_caption})
    assert post.hype_errors
    with pytest.raises(ValueError):
        services.mark_posted(post)
    services.update_text_content(post, {"ig_caption": "色落ちが気になる方へ。ご予約はDMから"})
    services.mark_posted(post)
    assert post.status == "PUBLISHED" and post.publish_result["manual"] is True
    other = services.start_post(stylist, post_type="tips", template_key="care_tips")
    rec = TypeRecommendation.objects.create(stylist=stylist, post=other, post_type="tips", reason="x")
    services.skip_post(other)
    rec.refresh_from_db()
    assert other.status == "SKIPPED" and rec.reaction == "skipped"


def test_update_metrics_and_history_by_type(stylist, client_logged):
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.status = "PUBLISHED"
    post.save()
    services.update_metrics(post, {"m_saves": "10", "m_profile_visits": "4", "m_link_clicks": "2", "m_dms": "1", "m_new_customers": "", "metrics_note": "初日"})
    assert post.manual_result_score == 10 * 0.5 + 4 + 2 * 3 + 1 * 3
    with pytest.raises(ValueError):
        services.update_metrics(post, {"m_saves": "abc"})
    page = client_logged.get(reverse("reels:history"))
    assert page.status_code == 200 and "お役立ち" in page.content.decode()
    resp = client_logged.post(reverse("reels:metrics_update", kwargs={"pk": post.pk}), {"m_saves": "12", "next": reverse("reels:history")})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.m_saves == 12 and post.m_dms is None


# ------------------------------------------------------------------ AIに渡す情報に個人情報が入らない


def test_sns_context_has_no_customer_pii(stylist, customer, karte):
    customer.story_ok = True
    customer.save()
    post = services.start_post(stylist, karte=karte, post_type="before_after", template_key="before_after", uses_story=True)
    post.theme = "色落ち"
    post.save()
    dumped = json.dumps(build_sns_context(post), ensure_ascii=False)
    assert "山田" not in dumped and "はなこ" not in dumped and "秘密" not in dumped
    assert str(karte.visited_on) not in dumped
    assert "色落ち" in dumped and "料金" in dumped


def test_generate_hooks_fake_never_calls_ai(stylist, settings):
    settings.AI_FAKE = True
    post = services.start_post(stylist, post_type="suggestion", template_key="color_catalog")
    with mock.patch("apps.reels.hooks.get_ai") as g:
        hooks = generate_hooks(post)
    g.assert_not_called()
    assert len(hooks) == 3


# ------------------------------------------------------------------ 画面：フィードの一連の流れ・カルテから・古い画面


def test_feed_flow_via_views(client_logged, stylist, settings):
    settings.AI_FAKE = True
    client_logged.post(reverse("reels:start"))
    post = ReelPost.objects.get(stylist=stylist)
    for n in ("a.png", "b.png"):
        client_logged.post(reverse("reels:asset_upload", kwargs={"pk": post.pk}), {"file": SimpleUploadedFile(n, _png(), content_type="image/png"), "role": "after"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client_logged.post(reverse("reels:choose_type", kwargs={"pk": post.pk}), {"post_type": "suggestion"})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.output_format == "feed" and len(post.hooks) == 3
    resp = client_logged.post(reverse("reels:choose_hook", kwargs={"pk": post.pk}), {"custom_text": "伸びても自然な色がいい人へ"})
    post.refresh_from_db()
    assert post.status == "READY" and post.selected_hook["type"] == "custom" and post.carousel
    url = reverse("reels:workspace", kwargs={"pk": post.pk})
    body = client_logged.get(url).content.decode()
    assert "各枚の文字" in body and "投稿済みにする" in body and "伸びても自然な色がいい人へ" in body
    resp = client_logged.post(reverse("reels:content_update", kwargs={"pk": post.pk}), {"ig_caption": "色落ちが気になる方へ。ご予約はDMから", "hashtags": "#なんば美容室 #色落ち", "cover_text": "表紙", "slide_title_0": "1枚目", "slide_text_0": "本文", "slide_title_1": "2枚目", "slide_text_1": ""})
    post.refresh_from_db()
    assert post.carousel[0]["title"] == "1枚目" and post.hashtags == ["なんば美容室", "色落ち"] and post.cover_text == "表紙"
    assert client_logged.post(reverse("reels:mark_posted", kwargs={"pk": post.pk})).status_code == 302
    post.refresh_from_db()
    assert post.status == "PUBLISHED"


def test_start_from_karte_imports_roles_and_weekly_plan_card(client_logged, stylist, customer, karte):
    KartePhoto.objects.create(karte=karte, image=SimpleUploadedFile("before.png", _png(), content_type="image/png"), sns_ok=True, face_visible=False, role="before")
    resp = client_logged.post(reverse("reels:start"), {"karte": karte.pk, "post_type": "before_after", "reason": "今週のおすすめ"})
    assert resp.status_code == 302 and "want=before_after" in resp.url
    post = ReelPost.objects.get(stylist=stylist)
    roles = sorted(post.assets.values_list("role", flat=True))
    assert roles == ["after", "before"] and post.recommendations.filter(post_type="before_after", reaction="pending").exists()
    body = client_logged.get(resp.url).content.decode()
    assert "今週のおすすめ：ビフォーアフター" in body and "必要な素材はそろっています" in body
    home = client_logged.get(reverse("reels:home")).content.decode()
    assert "投稿をつくる" in home
    today = client_logged.get(reverse("core:today"))
    assert today.status_code == 200


def test_tenant_isolation_for_new_views(client_logged, other_stylist):
    post = services.start_post(other_stylist, post_type="tips", template_key="care_tips")
    for name in ("choose_type", "choose_hook", "mark_posted", "skip", "metrics_update", "content_update"):
        assert client_logged.post(reverse(f"reels:{name}", kwargs={"pk": post.pk})).status_code == 404


def test_availability_ratio_uses_open_slots(stylist):
    stylist.work_days = []  # 手で登録した枠だけを数えるテストなので、自動の空き枠は出さない
    stylist.save()
    from apps.broadcasts.models import AvailabilitySlot
    from apps.reels.recommend import open_ratio_for

    assert open_ratio_for(stylist) is None  # 空き枠を使っていない
    today = today_local()
    AvailabilitySlot.objects.create(stylist=stylist, date=today + timedelta(days=1), start_time=time(10, 0), end_time=time(15, 0))
    stylist.weekly_slot_hours = 10
    assert open_ratio_for(stylist, today) == pytest.approx(0.5)
    AvailabilitySlot.objects.create(stylist=stylist, date=today + timedelta(days=30), start_time=time(10, 0), end_time=time(15, 0))  # 14日より先は数えない
    assert open_ratio_for(stylist, today) == pytest.approx(0.5)


def test_feed_post_can_be_converted_to_reel(client_logged, stylist, settings):
    settings.AI_FAKE = True
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    _photo(post, role="after", name="a.png")
    post.selected_hook = {"type": "call", "label": "呼びかけ", "text": "色落ちが早い人へ", "visual": "", "hype": []}
    post.save()
    generate_content(post)
    post.refresh_from_db()
    assert post.output_format == "feed" and post.status == "READY" and not post.script
    body = client_logged.get(post.get_workspace_url()).content.decode()
    assert ("この内容で動画にする" in body) == services.options(stylist)["ffmpeg_available"]
    with mock.patch("apps.reels.content.services.request_render") as rr, mock.patch("apps.reels.content.services.options", return_value={"ffmpeg_available": True}):
        resp = client_logged.post(reverse("reels:content_to_reel", kwargs={"pk": post.pk}))
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.output_format == "reel" and post.script and post.script["scenes"][0]["narration"] == "色落ちが早い人へ"
    rr.assert_called_once()
    empty = services.start_post(stylist, post_type="tips", template_key="care_tips")
    empty.selected_hook = post.selected_hook
    empty.save()
    with pytest.raises(ValueError):
        services.convert_to_reel(empty)


def test_two_photos_make_full_before_after_script(stylist):
    """ビフォー1枚＋アフター1枚でも、フック・施術前・仕上がりの場面がそろう（必須の項目は同じ役割の写真を使い回す）"""
    from apps.reels.ai import mock_script

    post = services.start_post(stylist)
    before = _photo(post, role="before", name="before.png")
    after = _photo(post, role="after", name="after.png")
    services.choose_type(post, "before_after", "manual", start_hooks=False)
    post.selected_hook = {"type": "call", "label": "呼びかけ", "text": "色落ちが早い人へ", "visual": "", "hype": []}
    post.save()
    script = mock_script(post, list(post.usable_assets()))
    roles = [sc["role"] for sc in script["scenes"]]
    assert roles == ["フック", "悩み", "仕上がり"]
    assert script["scenes"][1]["shots"][0]["asset_id"] == str(before.id)
    assert script["scenes"][2]["shots"][0]["asset_id"] == str(after.id)  # after_back に after の写真を使い回す
    assert "bowl" not in [sh.get("asset_id") for sc in script["scenes"] for sh in sc["shots"]]


def test_request_render_keeps_ready_when_job_runs_inline(stylist):
    """同期実行（開発環境）では enqueue の中で動画ができる。終わった後に「作成中」へ戻さない"""
    post = services.start_post(stylist, post_type="tips", template_key="care_tips")
    post.script = {"scenes": [], "cta": {}}
    post.save()

    def fake_enqueue(name, job_id):
        ReelPost.objects.filter(pk=post.pk).update(status="READY")

    with mock.patch("apps.reels.services.enqueue", side_effect=fake_enqueue):
        services.request_render(post)
    post.refresh_from_db()
    assert post.status == "READY"


def test_caption_avoids_busy_and_skin_bands(tmp_path):
    """テロップは、模様が多い帯・肌色の帯を避けて置く"""
    from PIL import Image, ImageDraw

    from apps.reels.engine.layout import CANDIDATES, band_scores, caption_position, choose_position

    img = Image.new("RGB", (540, 960), (235, 235, 235))
    d = ImageDraw.Draw(img)
    for yy in range(0, 300, 6):  # 上の帯に細かい模様（髪のつもり）
        d.line([(0, yy), (540, yy + 3)], fill=(40, 30, 20), width=2)
    path = tmp_path / "top_busy.jpg"
    img.save(path)
    name, y = caption_position(path, prefer="top")
    assert name != "top" and y == CANDIDATES[name]

    face = Image.new("RGB", (540, 960), (235, 235, 235))
    ImageDraw.Draw(face).ellipse([170, 120, 370, 330], fill=(224, 172, 140))  # 上の帯に肌色（顔のつもり）
    scores = band_scores(face)
    assert scores["top"] > scores["bottom"]
    assert choose_position({"top": 0.30, "middle": 0.10, "bottom": 0.12}, prefer="top") == "middle"
    assert choose_position({"top": 0.14, "middle": 0.10, "bottom": 0.12}, prefer="top") == "top"  # 大差なければ好みの位置
    assert caption_position(tmp_path / "missing.jpg", prefer="middle") == ("middle", CANDIDATES["middle"])


def test_engine_script_uses_caption_position(stylist):
    from apps.reels.ai import mock_script
    from apps.reels.render_service import engine_script

    post = services.start_post(stylist)
    _photo(post, role="after", name="a.png")
    services.choose_type(post, "tips", "manual", start_hooks=False)
    post.selected_hook = {"type": "call", "label": "呼びかけ", "text": "色落ちが早い人へ", "visual": "", "hype": []}
    post.save()
    post.script = mock_script(post, list(post.usable_assets()))
    post.script["scenes"][0]["caption_pos"] = "bottom"
    post.save()
    es = engine_script(post)
    assert es["scenes"][0]["caption_pos"] == "bottom" and es["scenes"][0]["caption_y"] == 0.70
    assert all(s["caption_pos"] in ("top", "middle", "bottom") and 0 < s["caption_y"] < 1 for s in es["scenes"])
    services.edit_script(post, [{"scene": 0, "caption_pos": "nonsense"}])
    post.refresh_from_db()
    assert post.script["scenes"][0]["caption_pos"] == "auto"


def test_library_reuses_own_assets_but_not_customer_photos(stylist, client_logged):
    first = services.start_post(stylist, post_type="personality", template_key="stylist_story")
    _photo(first, role="self", name="me.png")
    _photo(first, role="process", name="hands.png")
    _photo(first, role="after", name="customer.png")
    second = services.start_post(stylist)
    lib = services.library_assets(stylist, exclude_post=second)
    assert sorted(a.role for a in lib) == ["process", "self"]  # お客様のアフターは入らない
    resp = client_logged.post(reverse("reels:library_add", kwargs={"pk": second.pk}), {"asset_id": lib[0].id}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200 and resp.json()["asset"]["role"] == lib[0].role
    added = second.assets.get()
    assert added.source == "library" and added.file.name != lib[0].file.name
    with pytest.raises(ValueError):
        services.add_from_library(second, first.assets.get(role="after"))
    body = client_logged.get(second.get_workspace_url()).content.decode()
    assert "前に撮ったものから足す" in body


def test_stock_search_and_add(stylist, client_logged, settings):
    from apps.reels import stock

    post = services.start_post(stylist)
    assert client_logged.get(reverse("reels:stock_search", kwargs={"pk": post.pk}) + "?q=salon").status_code == 400  # キー未設定
    settings.PEXELS_API_KEY = "test-key"

    class R:
        def __init__(self, payload=None, content=b""):
            self._payload, self.content = payload, content

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

        def iter_content(self, chunk_size=1):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    photos = {"photos": [{"id": 1, "photographer": "Taro", "url": "https://www.pexels.com/photo/1/", "src": {"medium": "https://img/m.jpg", "large2x": "https://img/l.jpg"}}]}
    with mock.patch("apps.reels.stock.requests.get", return_value=R(photos)) as g:
        items = stock.search("scissors", "photo")
    assert items[0]["credit"] == "Taro" and items[0]["url"] == "https://img/l.jpg" and g.call_args.kwargs["headers"]["Authorization"] == "test-key"
    with mock.patch("apps.reels.stock.requests.get", return_value=R(content=_png())):
        resp = client_logged.post(reverse("reels:stock_add", kwargs={"pk": post.pk}), {**items[0], "duration": "", "role": "after"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    asset = post.assets.get()
    assert asset.source == "stock" and asset.role == "other" and asset.credit == "Taro"  # ビフォー／アフターには使えない
    with pytest.raises(ValueError):
        services.set_role(asset, "before")
    services.set_role(asset, "process")
    assert services.library_assets(stylist, exclude_post=None)[0].is_stock


def test_recover_stuck_posts_and_bulk_delete(stylist, client_logged):
    from datetime import timedelta

    from django.utils import timezone

    from apps.reels.models import RenderJob

    done = services.start_post(stylist, post_type="tips", template_key="care_tips")
    done.status, done.video = "RENDERING", "stylist_1/reels/renders/x.mp4"
    done.save()
    RenderJob.objects.create(post=done, status="done")
    stale = services.start_post(stylist, post_type="tips", template_key="care_tips")
    stale.status = "RENDERING"
    stale.save()
    RenderJob.objects.create(post=stale, status="running")
    RenderJob.objects.filter(post=stale).update(updated_at=timezone.now() - timedelta(minutes=30))
    fresh = services.start_post(stylist, post_type="tips", template_key="care_tips")
    fresh.status = "HOOKING"
    fresh.save()
    assert services.recover_stuck_posts(stylist) == 2
    done.refresh_from_db(); stale.refresh_from_db(); fresh.refresh_from_db()
    assert done.status == "READY" and stale.status == "FAILED" and "止まりました" in stale.error and fresh.status == "HOOKING"
    published = services.start_post(stylist, post_type="tips", template_key="care_tips")
    published.status = "PUBLISHED"
    published.save()
    body = client_logged.get(reverse("reels:home")).content.decode()
    assert "選んだ <span" in body and 'name="ids"' in body
    resp = client_logged.post(reverse("reels:bulk_delete"), {"ids": [str(done.pk), str(stale.pk), str(published.pk)]})
    assert resp.status_code == 302
    assert not ReelPost.objects.filter(pk__in=[done.pk, stale.pk]).exists() and ReelPost.objects.filter(pk=published.pk).exists()


def test_bulk_delete_is_tenant_scoped(client_logged, other_stylist):
    post = services.start_post(other_stylist, post_type="tips", template_key="care_tips")
    client_logged.post(reverse("reels:bulk_delete"), {"ids": [str(post.pk)]})
    assert ReelPost.objects.filter(pk=post.pk).exists()

