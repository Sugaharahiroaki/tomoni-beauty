"""SNS生成に渡す情報の絞り込みと、生成後の個人情報チェック。"""
import json
from unittest import mock

import pytest

from apps.ai.claude_client import FakeAIClient
from apps.core.dates import today_local
from apps.drafts.models import SnsPost
from apps.drafts.services import build_sns_inputs, generate_sns_post, recheck_pii
from apps.karte.models import Karte
from apps.profiles.models import Episode, EpisodeUsage

SECRET = "離婚して引っ越したばかり"


@pytest.fixture
def karte(stylist, customer):
    return Karte.objects.create(
        stylist=stylist,
        customer=customer,
        visited_on=today_local(),
        treatment_summary="落ち着いたブラウンにカラー",
        design_details="マット寄りの補色",
        menu_items=["カラー"],
        concerns=["色落ちが早い"],
        results="赤みが出にくい配合に",
        customer_requests=["次回はリタッチ"],
        private_notes=SECRET,
    )


def _post(stylist, customer, karte, uses_story=True, episode=None):
    return SnsPost.objects.create(stylist=stylist, customer=customer, karte=karte, purpose="nomination", uses_story=uses_story, episode=episode)


def test_inputs_exclude_private_notes_and_customer_identity(stylist, customer, karte):
    post = _post(stylist, customer, karte)
    inputs = build_sns_inputs(post)
    dumped = json.dumps(inputs, ensure_ascii=False, default=str)
    assert SECRET not in dumped
    assert "山田" not in dumped and "花子" not in dumped and "はなこ" not in dumped
    assert "リタッチ" not in dumped  # customer_requests も渡さない
    assert inputs["story_allowed"] is True
    assert inputs["generalized"]["concern"]


def test_story_not_used_without_consent(stylist, customer, karte):
    customer.story_ok = False
    customer.save()
    post = _post(stylist, customer, karte, uses_story=True)
    inputs = build_sns_inputs(post)
    assert inputs["story_allowed"] is False
    assert inputs["generalized"] is None
    assert inputs["treatment_summary"] == "落ち着いたブラウンにカラー"


def test_story_not_used_when_stylist_opts_out(stylist, customer, karte):
    post = _post(stylist, customer, karte, uses_story=False)
    assert build_sns_inputs(post)["story_allowed"] is False


def test_generalized_story_strips_customer_name(stylist, customer, karte):
    post = _post(stylist, customer, karte)
    leaky = {"concern": "山田さんは色落ちが早い", "result": "花子に合わせた配合", "removed_items": []}
    with mock.patch("apps.ai.services.generalize_story", return_value=leaky):
        inputs = build_sns_inputs(post)
    assert "山田" not in inputs["generalized"]["concern"]
    assert "花子" not in inputs["generalized"]["result"]


def test_generate_sns_post_passes_pii_check_and_records_episode_usage(stylist, customer, karte):
    ep = Episode.objects.create(stylist=stylist, title="きっかけ", body="母の髪を切った話", themes=["きっかけ"])
    post = _post(stylist, customer, karte, episode=ep)
    generate_sns_post(post.id)
    post.refresh_from_db()
    assert post.status == SnsPost.Status.DRAFT
    assert post.feed_text and post.story_text and post.reel_script and post.hashtags
    assert all(t.startswith("#") for t in post.hashtags)
    assert post.pii_passed is True
    assert EpisodeUsage.objects.filter(episode=ep, sns_post=post).exists()


def test_generate_sns_post_flags_customer_name_in_output(stylist, customer, karte):
    post = _post(stylist, customer, karte)
    leaky = {"feed_text": "今日は山田さんが来てくれました。32歳の会社員の方です。", "story_text": "花子さんありがとう", "reel_script": "[0-3秒] テロップ", "hashtags": ["#ブラウン", "#はなこ"]}
    with mock.patch.object(FakeAIClient, "_task_sns", return_value=leaky):
        generate_sns_post(post.id)
    post.refresh_from_db()
    assert post.status == SnsPost.Status.DRAFT
    assert post.pii_passed is False
    kinds = {f["kind"] for f in post.pii_errors}
    assert "customer_name" in kinds and "age" in kinds
    fields = {f["field"] for f in post.pii_errors}
    assert {"feed_text", "story_text", "hashtags"} <= fields


def test_recheck_after_edit_clears_errors(stylist, customer, karte):
    post = _post(stylist, customer, karte)
    post.feed_text = "山田さんの髪"
    post.save()
    assert recheck_pii(post)["passed"] is False
    post.feed_text = "お客様の髪"
    post.save()
    assert recheck_pii(post)["passed"] is True


def test_mark_posted_blocked_while_pii_errors(client_logged, stylist, customer, karte):
    from django.urls import reverse

    post = _post(stylist, customer, karte)
    post.feed_text = "山田さん"
    post.status = SnsPost.Status.DRAFT
    post.save()
    recheck_pii(post)
    resp = client_logged.post(reverse("drafts:sns_mark_posted", kwargs={"pk": post.pk}))
    post.refresh_from_db()
    assert resp.status_code == 302
    assert post.status == SnsPost.Status.DRAFT
