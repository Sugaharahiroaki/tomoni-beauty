from datetime import date

from apps.ledger.filings import add_months, blue_deduction_for, blue_return_application_deadline, filing_sheet, opening_notification_deadline, required_books
from apps.ledger.models import FilingProfile


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 2) == date(2027, 1, 30)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_opening_notification_deadline_bumps_weekend():
    # 2026-05-10 は日曜 → 翌月曜
    assert opening_notification_deadline(date(2026, 4, 10)) == date(2026, 5, 11)
    assert opening_notification_deadline(date(2026, 4, 8)) == date(2026, 5, 8)  # 金曜


def test_blue_return_deadline_rules():
    # 1/1〜1/15 開業 → その年の 3/15（2026-03-15 は日曜 → 3/16）
    assert blue_return_application_deadline(date(2026, 1, 10)) == date(2026, 3, 16)
    # 1/16 以降 → 開業から2か月
    assert blue_return_application_deadline(date(2026, 1, 16)) == date(2026, 3, 16)
    assert blue_return_application_deadline(date(2026, 7, 20)) == date(2026, 9, 21)  # 9/20 日曜
    assert blue_return_application_deadline(date(2026, 4, 1)) == date(2026, 6, 1)
    # 既に開業している人が翌年分から → 3/15
    assert blue_return_application_deadline(date(2025, 5, 1), apply_year=2026) == date(2026, 3, 16)


def test_required_books_and_deduction():
    assert "仕訳帳" in required_books("double") and "仕訳帳" not in required_books("simple")
    assert blue_deduction_for("double", True) == 650_000
    assert blue_deduction_for("double", False) == 550_000
    assert blue_deduction_for("simple", True) == 100_000


def test_filing_sheet(stylist):
    profile = FilingProfile.objects.create(stylist=stylist, full_name="佐藤 美咲", full_name_kana="サトウ ミサキ", address="東京都渋谷区1-1-1", opened_on=date(2026, 4, 10), bookkeeping="simple", books=["現金出納帳"])
    sheet = filing_sheet(profile)
    opening = {label: value for label, value, _ in sheet["opening"]}
    blue = {label: (value, hint) for label, value, hint in sheet["blue"]}
    assert opening["提出期限"] == "2026年05月11日"
    assert opening["職業"] == "美容業"
    assert blue["提出期限"][0] == "2026年06月10日"
    assert blue["簿記方式"][0] == "簡易簿記" and "100,000" in blue["簿記方式"][1]
