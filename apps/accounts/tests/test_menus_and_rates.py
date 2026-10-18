"""メニュー・料金表、指名歩合・諸経費（SOYON なんば店の条件で確認）"""
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse

from apps.accounts.menus import add_menus_from_text, parse_menu_line, parse_menu_text
from apps.accounts.models import MenuItem
from apps.ai import services as ai_services


# ------------------------------------------------------------------ 歩合


def test_take_rate_uses_nominated_rate_minus_expenses(stylist):
    stylist.commission_rate = Decimal("55")
    stylist.nominated_commission_rate = Decimal("65")
    stylist.expense_rate = Decimal("15")
    assert stylist.take_rate(nominated=True) == Decimal("55.25")  # 65% × 0.85
    assert stylist.take_rate(nominated=False) == Decimal("46.75")  # 55% × 0.85
    assert stylist.take_rate_note() == "指名65% − 諸経費15%"


def test_take_rate_without_optional_fields(stylist):
    stylist.commission_rate = Decimal("50")
    assert stylist.take_rate() == Decimal("50")
    assert stylist.take_rate_note() == "歩合50%"
    stylist.commission_rate = None
    assert stylist.take_rate() is None


def test_availability_income_uses_take_rate(stylist, client_logged):
    stylist.commission_rate, stylist.nominated_commission_rate, stylist.expense_rate = 55, 65, 15
    stylist.avg_price, stylist.avg_service_minutes = 9500, 90
    stylist.save()
    from apps.broadcasts.services import potential_monthly_income

    assert potential_monthly_income(6, 9500, stylist.take_rate(), 90) == potential_monthly_income(6, 9500, Decimal("55.25"), 90)
    res = client_logged.get(reverse("broadcasts:availability"))
    assert res.status_code == 200


# ------------------------------------------------------------------ 貼り付け読み取り


@pytest.mark.parametrize(
    "line,expected",
    [
        ("【似合わせで垢抜け】ドライカット ¥2,800", {"name": "【似合わせで垢抜け】ドライカット", "price": 2800, "price_from": False, "target": "all", "category": "cut"}),
        ("[再来の方はこちら★]似合わせカット＋ナチュラルカラー ¥5,900", {"name": "似合わせカット＋ナチュラルカラー", "price": 5900, "target": "repeat", "category": "set"}),
        ("【新規】カット+ブリーチカラー+バイカルテTR 13900", {"name": "カット+ブリーチカラー+バイカルテTR", "price": 13900, "target": "new", "category": "set"}),
        ("ブリーチカラー 7,000円〜", {"name": "ブリーチカラー", "price": 7000, "price_from": True, "category": "bleach"}),
        ("バレイヤージュ　１８０００円～", {"name": "バレイヤージュ", "price": 18000, "price_from": True, "category": "bleach"}),
        ("ヘッドスパ（料金は要相談）", {"name": "ヘッドスパ（料金は要相談）", "price": None, "category": "spa"}),
        ("似合わせカット＋縮毛矯正 ¥11,400", {"category": "set"}),
        ("縮毛矯正 ¥9,000", {"category": "straight"}),
    ],
)
def test_parse_menu_line(line, expected):
    item = parse_menu_line(line)
    for key, value in expected.items():
        assert item[key] == value, (key, item)


def test_parse_menu_text_skips_blank_lines():
    assert len(parse_menu_text("カット 4500\n\n  \n・カラー 5000")) == 2
    assert parse_menu_text("") == []


def test_add_menus_from_text_appends_in_order(stylist):
    MenuItem.objects.create(stylist=stylist, name="既存", price=1000, order=5)
    created = add_menus_from_text(stylist, "カット 4500\nカラー 5,000円〜")
    assert [m.order for m in created] == [6, 7]
    assert created[1].label() == "カラー 5,000円〜"


def test_menu_label_and_prompt_text(stylist):
    MenuItem.objects.create(stylist=stylist, name="似合わせカット+ナチュラルカラー", price=5900, target="repeat", order=1)
    MenuItem.objects.create(stylist=stylist, name="深夜料金", price=1000, price_from=True, note="21時以降", order=2)
    MenuItem.objects.create(stylist=stylist, name="使わない", price=1, is_active=False, order=3)
    text = stylist.menu_prompt_text()
    assert "- 似合わせカット+ナチュラルカラー 5,900円（再来）" in text
    assert "- 深夜料金 1,000円〜／21時以降" in text
    assert "使わない" not in text


# ------------------------------------------------------------------ 画面


def test_menu_views_crud(stylist, client_logged):
    res = client_logged.get(reverse("accounts:menu_list"))
    assert res.status_code == 200 and "まだ登録がありません" in res.content.decode()
    res = client_logged.post(reverse("accounts:menu_bulk"), {"text": "【新規】カット+透明感カラー ¥6,500\nヘッドスパ"}, follow=True)
    assert "2件追加しました" in res.content.decode() and "1件は料金を読み取れません" in res.content.decode()
    item = stylist.menus.get(name="カット+透明感カラー")
    assert item.target == "new" and item.price == 6500
    res = client_logged.post(reverse("accounts:menu_edit", args=[item.pk]), {"category": "set", "name": "カット+透明感カラー", "price": 7000, "target": "new", "order": 1, "is_active": "on"})
    assert res.status_code == 302
    item.refresh_from_db()
    assert item.price == 7000
    res = client_logged.post(reverse("accounts:menu_add"), {"category": "cut", "name": "前髪カット", "price": 1000, "target": "all", "order": 9, "is_active": "on"})
    assert res.status_code == 302 and stylist.menus.filter(name="前髪カット").exists()
    client_logged.post(reverse("accounts:menu_delete", args=[item.pk]))
    assert not stylist.menus.filter(pk=item.pk).exists()


def test_menu_views_are_tenant_scoped(stylist, other_stylist, client_logged):
    other = MenuItem.objects.create(stylist=other_stylist, name="他人のメニュー", price=1000)
    assert client_logged.get(reverse("accounts:menu_edit", args=[other.pk])).status_code == 404
    assert client_logged.post(reverse("accounts:menu_delete", args=[other.pk])).status_code == 404
    assert MenuItem.objects.filter(pk=other.pk).exists()


def test_settings_form_saves_rates_and_access(stylist, client_logged):
    data = {
        "display_name": "佐藤 美咲", "salon_name": "SOYON なんば店", "salon_access": "なんば駅から徒歩1分", "hotpepper_url": "",
        "commission_rate": "55", "nominated_commission_rate": "65", "expense_rate": "15", "avg_price": "9500", "weekly_slot_hours": "",
        "avg_service_minutes": "90", "default_cycle_weeks": "6", "follow_up_lead_days": "7", "max_broadcasts_per_month": "1", "broadcast_min_interval_days": "14",
    }
    res = client_logged.post(reverse("accounts:stylist_settings"), data)
    assert res.status_code == 302
    stylist.refresh_from_db()
    assert stylist.nominated_commission_rate == 65 and stylist.expense_rate == 15 and stylist.salon_access == "なんば駅から徒歩1分"


# ------------------------------------------------------------------ AIに渡す料金表


def _capture_user_prompt(fn, *args, **kwargs):
    fake = mock.Mock()
    fake.generate_json.return_value = {}
    with mock.patch.object(ai_services, "get_ai", return_value=fake):
        fn(*args, **kwargs)
    return fake.generate_json.call_args[0][2]


def test_menu_text_is_passed_to_line_drafts_reply_and_broadcast():
    from datetime import date

    menu = "- 似合わせカット+ナチュラルカラー 5,900円（再来）"
    prompt = _capture_user_prompt(ai_services.generate_line_drafts, {"menu_items": ["カラー"]}, {}, True, 6, date(2026, 10, 18), menu)
    assert "【メニュー・料金表" in prompt and menu in prompt
    assert menu in _capture_user_prompt(ai_services.suggest_reply, "カラーいくらですか？", {}, True, "", [], menu)
    assert menu in _capture_user_prompt(ai_services.draft_broadcast, "availability", "", {}, True, "", "", menu)
    assert "なし（料金は書かない）" in _capture_user_prompt(ai_services.suggest_reply, "こんにちは", {}, True, "", [])


def test_price_rules_in_system_prompts():
    from apps.ai import prompts

    for system in (prompts.DRAFTS_SYSTEM, prompts.BROADCAST_SYSTEM, prompts.REPLY_SYSTEM):
        assert "【メニュー・料金表】" in system


def test_karte_extraction_gets_menu_names():
    from datetime import date

    prompt = _capture_user_prompt(ai_services.extract_karte, "ハイライト入れました", "佐藤", date(2026, 10, 18), "", ["ハイライト", "カラー"])
    assert "ハイライト / カラー" in prompt


def test_take_rate_note_has_no_trailing_zeros_after_db_roundtrip(stylist):
    stylist.commission_rate, stylist.nominated_commission_rate, stylist.expense_rate = 55, 65, Decimal("12.5")
    stylist.save()
    stylist.refresh_from_db()  # DB からは 65.00 のように小数2桁で戻る
    assert stylist.take_rate_note() == "指名65% − 諸経費12.5%"
    assert str(stylist.take_rate()) == "56.88"
