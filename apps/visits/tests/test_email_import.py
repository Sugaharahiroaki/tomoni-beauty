import json
from datetime import date, timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.lineapp.models import Message
from apps.visits.email_import import import_reservation_email, match_customer
from apps.visits.email_parser import name_key, parse_datetime, regex_parse
from apps.visits.models import Reservation, ReservationEmail

SAMPLE = """【ご予約】新しい予約を受け付けました
お客様名：山田 花子 様
フリガナ：ヤマダ ハナコ
来店日時：2026年10月25日（土） 13:00
メニュー：カット＋カラー
スタイリスト：佐藤 美咲
予約番号：AB12345
"""


def test_regex_parse_extracts_fields():
    parsed = regex_parse("【ご予約】新しい予約", SAMPLE, reference=date(2026, 10, 18))
    assert parsed["kind"] == "booked"
    assert parsed["customer_name"] == "山田 花子"
    assert parsed["customer_kana"] == "ヤマダ ハナコ"
    assert parsed["reserved_for"] == "2026-10-25T13:00"
    assert parsed["menu"] == "カット+カラー"
    assert parsed["stylist_name"] == "佐藤 美咲"
    assert parsed["reservation_id"] == "AB12345"


def test_regex_parse_cancel_and_missing():
    parsed = regex_parse("【キャンセル】ご予約がキャンセルされました", "お客様名：山田 花子\n来店日時：10/25 13:00", reference=date(2026, 10, 18))
    assert parsed["kind"] == "cancelled"
    assert parsed["reserved_for"] == "2026-10-25T13:00"
    assert regex_parse("こんにちは", "本文に予約情報なし") is None


def test_parse_datetime_year_inference():
    assert parse_datetime("10/25(土) 13:00", reference=date(2026, 10, 18)).isoformat() == "2026-10-25T13:00:00"
    assert parse_datetime("1/5 10:00", reference=date(2026, 12, 20)).isoformat() == "2027-01-05T10:00:00"
    assert parse_datetime("2026年3月1日 9時", reference=date(2026, 10, 18)).isoformat() == "2026-03-01T09:00:00"
    assert parse_datetime("日時不明") is None


def test_name_key_normalizes_kana_and_width():
    assert name_key("ヤマダ　ハナコ") == name_key("やまだ はなこ")
    assert name_key("ＹＡＭＡＤＡ") == "yamada"


def test_match_customer(stylist, customer):
    found, candidates = match_customer(stylist, "山田 花子", "")
    assert found == customer
    found, candidates = match_customer(stylist, "", "ヤマダ ハナコ")
    assert found == customer
    found, candidates = match_customer(stylist, "鈴木 一郎", "")
    assert found is None and candidates == []


def test_import_creates_reservation_with_attribution(stylist, customer):
    Message.objects.create(stylist=stylist, customer=customer, kind=Message.Kind.NEXT_VISIT, route=Message.Route.COPY, body="案内", sent_at=timezone.now() - timedelta(days=3))
    email = import_reservation_email(stylist, "【ご予約】", SAMPLE, timezone.now())
    assert email.status == ReservationEmail.Status.APPLIED
    assert email.parse_method == "regex"
    r = email.reservation
    assert r.customer == customer and r.source == Reservation.Source.EMAIL
    assert timezone.localtime(r.reserved_for).strftime("%Y-%m-%d %H:%M") == "2026-10-25 13:00"
    assert r.attributed_message is not None
    # 同じメールを再度取り込んでも予約は増えない
    again = import_reservation_email(stylist, "【ご予約】", SAMPLE, timezone.now())
    assert again.reservation == r and Reservation.objects.filter(stylist=stylist).count() == 1


def test_import_unknown_customer_needs_review(stylist):
    body = SAMPLE.replace("山田 花子", "鈴木 一郎").replace("ヤマダ ハナコ", "スズキ イチロウ")
    email = import_reservation_email(stylist, "【ご予約】", body, timezone.now())
    assert email.status == ReservationEmail.Status.NEEDS_REVIEW
    assert email.reservation.customer is None and email.reservation.customer_name_raw == "鈴木 一郎"


def test_import_cancellation_cancels_existing(stylist, customer):
    import_reservation_email(stylist, "【ご予約】", SAMPLE, timezone.now())
    cancel = "【キャンセル】ご予約がキャンセルされました\nお客様名：山田 花子 様\n来店日時：2026年10月25日 13:00"
    email = import_reservation_email(stylist, "【キャンセル】", cancel, timezone.now())
    assert email.status == ReservationEmail.Status.APPLIED
    assert email.reservation.status == Reservation.Status.CANCELLED


def test_import_unparsable(stylist):
    email = import_reservation_email(stylist, "お知らせ", "本日は晴天なり", timezone.now())
    assert email.status == ReservationEmail.Status.UNPARSED


def test_internal_endpoint(stylist, customer, settings):
    key = stylist.ensure_email_import_key()
    url = reverse("visits:internal_reservation_email")
    payload = {"stylist_key": key, "subject": "【ご予約】", "body": SAMPLE, "received_at": "2026-10-18T09:00:00+09:00", "from": "noreply@example.com"}
    assert Client().post(url, json.dumps(payload), content_type="application/json").status_code == 403
    resp = Client().post(url, json.dumps(payload), content_type="application/json", HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"
    bad = Client().post(url, json.dumps({**payload, "stylist_key": "nope"}), content_type="application/json", HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)
    assert bad.status_code == 404


def test_paste_view(client_logged, stylist, customer):
    resp = client_logged.post(reverse("visits:reservation_emails"), {"subject": "", "body": SAMPLE})
    assert resp.status_code == 302
    assert Reservation.objects.filter(stylist=stylist, customer=customer).exists()
    page = client_logged.get(reverse("visits:reservation_emails"))
    stylist.refresh_from_db()
    assert page.status_code == 200 and stylist.email_import_key
    assert stylist.email_import_key in page.content.decode()
