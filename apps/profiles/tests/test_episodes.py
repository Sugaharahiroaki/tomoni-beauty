from datetime import timedelta

from django.utils import timezone

from apps.profiles.models import Episode, EpisodeUsage, InterviewAnswer, InterviewQuestion
from apps.profiles.services import build_episodes_from_interview, select_episode


def test_select_episode_prefers_theme_match(stylist):
    color = Episode.objects.create(stylist=stylist, title="色落ちの話", body="b", themes=["カラー", "色落ち"])
    Episode.objects.create(stylist=stylist, title="休日", body="b", themes=["休日"])
    assert select_episode(stylist, ["カラー", "色落ちが早い"]) == color


def test_select_episode_avoids_recently_used(stylist):
    a = Episode.objects.create(stylist=stylist, title="A", body="b", themes=["カラー"])
    b = Episode.objects.create(stylist=stylist, title="B", body="b", themes=["カラー"])
    EpisodeUsage.objects.create(episode=a)
    assert select_episode(stylist, ["カラー"]) == b
    # 使用が古ければ候補に戻る
    EpisodeUsage.objects.filter(episode=a).update(used_at=timezone.now() - timedelta(days=30))
    EpisodeUsage.objects.create(episode=b)
    assert select_episode(stylist, ["カラー"]) == a


def test_select_episode_respects_purpose(stylist):
    Episode.objects.create(stylist=stylist, title="色", body="b", themes=["カラー"])
    first = Episode.objects.create(stylist=stylist, title="初めて", body="b", themes=["初めての方", "カウンセリング"])
    assert select_episode(stylist, [], purpose="first_timer") == first


def test_select_episode_ignores_inactive_and_handles_empty(stylist):
    assert select_episode(stylist, ["カラー"]) is None
    Episode.objects.create(stylist=stylist, title="off", body="b", themes=["カラー"], is_active=False)
    assert select_episode(stylist, ["カラー"]) is None


def test_select_episode_is_tenant_scoped(stylist, other_stylist):
    Episode.objects.create(stylist=other_stylist, title="他人", body="b", themes=["カラー"])
    assert select_episode(stylist, ["カラー"]) is None


def test_build_episodes_from_interview(stylist):
    q1, q2 = InterviewQuestion.objects.filter(is_active=True).order_by("order")[:2]
    InterviewAnswer.objects.create(stylist=stylist, question=q1, transcript="母の髪を切ったのがきっかけです", status=InterviewAnswer.Status.DONE)
    InterviewAnswer.objects.create(stylist=stylist, question=q2, transcript="色落ちで悩む人を見てきました", status=InterviewAnswer.Status.DONE)
    created = build_episodes_from_interview(stylist)
    assert created >= 1
    assert Episode.objects.filter(stylist=stylist, source=Episode.Source.AI).count() == created
    stylist.refresh_from_db()
    assert stylist.interview_completed is True
    assert stylist.profile.style_summary


def test_build_episodes_without_answers_returns_zero(stylist):
    assert build_episodes_from_interview(stylist) == 0
