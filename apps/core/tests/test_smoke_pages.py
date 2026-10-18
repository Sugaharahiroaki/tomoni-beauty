"""主要画面がテンプレートエラー無く描画できることを一通り確認する。"""
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.dates import today_local
from apps.drafts.models import Draft, SnsPost
from apps.drafts.services import generate_sns_post
from apps.karte.models import VoiceMemo
from apps.karte.services import process_voice_memo
from apps.lineapp.models import InboundMessage
from apps.lineapp.services import suggest_reply_for_inbound
from apps.profiles.models import Episode, InterviewQuestion
from apps.visits.models import Reservation


@pytest.fixture
def world(stylist, customer, channel):
    memo = VoiceMemo.objects.create(stylist=stylist, customer=customer, visited_on=today_local(), text_input="今日はブラウンにカラー。色落ちが気になるとのこと。次回は6週間後。写真はSNS掲載OK、顔出しNG")
    process_voice_memo(memo.id)
    memo.refresh_from_db()
    karte = memo.karte
    Episode.objects.create(stylist=stylist, title="母の髪", body="きっかけの話", themes=["きっかけ", "カラー"])
    post = SnsPost.objects.create(stylist=stylist, customer=customer, karte=karte, purpose="nomination", uses_story=True)
    generate_sns_post(post.id)
    inbound = InboundMessage.objects.create(stylist=stylist, customer=customer, text="来週予約できますか？", reply_token="rt", received_at=timezone.now(), line_message_id="m1")
    suggest_reply_for_inbound(inbound.id)
    reservation = Reservation.objects.create(stylist=stylist, customer=customer, reserved_for=timezone.now(), menu="カラー")
    return {"memo": memo, "karte": karte, "post": post, "inbound": inbound, "reservation": reservation, "draft": Draft.objects.filter(karte=karte).first()}


def test_pages_render(client_logged, customer, world):
    urls = [
        reverse("core:today"),
        reverse("core:stats"),
        reverse("core:settings_menu"),
        reverse("core:offline"),
        reverse("accounts:stylist_settings"),
        reverse("accounts:account_delete"),
        reverse("accounts:onboarding_basic"),
        reverse("accounts:onboarding_line"),
        reverse("accounts:onboarding_interview"),
        reverse("profiles:interview"),
        reverse("profiles:interview_question", kwargs={"order": InterviewQuestion.objects.first().order}),
        reverse("profiles:style_settings"),
        reverse("profiles:episode_list"),
        reverse("profiles:episode_create"),
        reverse("customers:list"),
        reverse("customers:list") + "?q=山田",
        reverse("customers:create"),
        reverse("customers:detail", kwargs={"pk": customer.pk}),
        reverse("customers:edit", kwargs={"pk": customer.pk}),
        reverse("customers:search_json") + "?q=山",
        reverse("visits:reservation_list"),
        reverse("visits:reservation_create") + f"?customer={customer.pk}",
        reverse("visits:reservation_edit", kwargs={"pk": world["reservation"].pk}),
        reverse("visits:visit_create"),
        reverse("visits:followup_list"),
        reverse("karte:memo_new"),
        reverse("karte:memo_new") + f"?customer={customer.pk}",
        reverse("karte:list"),
        reverse("karte:detail", kwargs={"pk": world["karte"].pk}),
        reverse("karte:edit", kwargs={"pk": world["karte"].pk}),
        reverse("karte:memo_status", kwargs={"pk": world["memo"].pk}),
        reverse("drafts:list"),
        reverse("drafts:detail", kwargs={"pk": world["draft"].pk}),
        reverse("drafts:sns_detail", kwargs={"pk": world["post"].pk}),
        reverse("drafts:sns_status", kwargs={"pk": world["post"].pk}),
        reverse("lineapp:settings"),
        reverse("lineapp:inbox"),
        reverse("lineapp:inbound_detail", kwargs={"pk": world["inbound"].pk}),
        reverse("lineapp:inbound_status", kwargs={"pk": world["inbound"].pk}),
        reverse("accounts:export_data"),
        reverse("visits:reservation_emails"),
        reverse("broadcasts:list"),
        reverse("ledger:dashboard"),
        reverse("core:terms"),
        reverse("core:privacy"),
    ]
    for url in urls:
        resp = client_logged.get(url)
        assert resp.status_code == 200, f"{url} -> {resp.status_code}"


def test_memo_detail_redirects_to_karte_when_done(client_logged, world):
    resp = client_logged.get(reverse("karte:memo_detail", kwargs={"pk": world["memo"].pk}))
    assert resp.status_code == 302
    assert resp.url == reverse("karte:detail", kwargs={"pk": world["karte"].pk})


def test_old_sns_pages_redirect_to_new_flow(client_logged, world):
    assert client_logged.get(reverse("drafts:sns_list")).status_code == 302
    resp = client_logged.get(reverse("drafts:sns_new") + f"?karte={world['karte'].pk}")
    assert resp.status_code == 302 and resp.url == reverse("reels:home")

