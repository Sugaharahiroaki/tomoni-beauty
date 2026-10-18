"""開業届・青色申告承認申請書の作成補助（期限計算・記入項目）。"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

OPENING_FORM_NAME = "個人事業の開業・廃業等届出書"
BLUE_FORM_NAME = "所得税の青色申告承認申請書"


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def next_business_day(d: date) -> date:
    """土日なら翌月曜へ（祝日は考慮しないので表示で注記する）。"""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def opening_notification_deadline(opened_on: date) -> date:
    """開業届: 事業開始の日から1か月以内。"""
    return next_business_day(add_months(opened_on, 1))


def blue_return_application_deadline(opened_on: date, apply_year: int | None = None) -> date:
    """青色申告承認申請書の提出期限。

    - 承認を受けたい年の 3/15（既に事業を行っている人、または 1/1〜1/15 に開業した人）
    - その年の 1/16 以降に開業した場合は、開業日から2か月以内
    """
    year = apply_year or opened_on.year
    if opened_on.year < year:
        return next_business_day(date(year, 3, 15))
    if opened_on <= date(year, 1, 15):
        return next_business_day(date(year, 3, 15))
    return next_business_day(add_months(opened_on, 2))


def required_books(bookkeeping: str) -> list[str]:
    if bookkeeping == "double":
        return ["仕訳帳", "総勘定元帳", "現金出納帳", "売掛帳", "買掛帳", "経費帳", "固定資産台帳"]
    return ["現金出納帳", "売掛帳", "買掛帳", "経費帳", "固定資産台帳"]


def blue_deduction_for(bookkeeping: str, uses_etax: bool) -> int:
    if bookkeeping == "double":
        return 650_000 if uses_etax else 550_000
    return 100_000


def filing_sheet(profile) -> dict:
    """記入用シート（国税庁の様式に転記するための項目一覧）。"""
    opened = profile.opened_on
    common = [
        ("納税地", profile.address, "住所地（自宅）を納税地にするのが一般的"),
        ("氏名・フリガナ", f"{profile.full_name} / {profile.full_name_kana}", ""),
        ("生年月日", profile.birth_date.strftime("%Y年%m月%d日") if profile.birth_date else "", ""),
        ("電話番号", profile.phone, ""),
        ("職業", profile.business_type or "美容業", ""),
        ("屋号", profile.business_name or "（なし）", "無くても提出できる"),
        ("提出先", f"{profile.tax_office or '（納税地の所轄）'}税務署", "国税庁サイトの「税務署の所在地」で確認"),
    ]
    opening = common + [
        ("届出の区分", "開業", ""),
        ("所得の種類", profile.income_type or "事業所得", "業務委託の美容師は事業所得が一般的（最終判断は税理士へ）"),
        ("開業日", opened.strftime("%Y年%m月%d日") if opened else "", ""),
        ("事業の概要", profile.business_description or "業務委託契約に基づく美容施術", ""),
        ("青色申告承認申請書の提出", "有（同時提出）" if profile.submit_blue_with_opening else "無", ""),
        ("給与等の支払の状況", "従業員なし" if not profile.has_employees else "従業員あり", ""),
        ("提出期限", opening_notification_deadline(opened).strftime("%Y年%m月%d日") if opened else "", "開業日から1か月以内（土日祝なら翌営業日）"),
    ]
    blue = common + [
        ("青色申告を開始したい年", f"{profile.start_blue_year or (opened.year if opened else '')}年分", ""),
        ("所得の種類", profile.income_type or "事業所得", ""),
        ("業務開始日", opened.strftime("%Y年%m月%d日") if opened else "", "本年1月16日以後に開業した場合に記入"),
        ("簿記方式", "複式簿記" if profile.bookkeeping == "double" else "簡易簿記", f"→ 青色申告特別控除 {blue_deduction_for(profile.bookkeeping, profile.uses_etax):,}円の見込み"),
        ("備付帳簿名", "、".join(profile.books or required_books(profile.bookkeeping)), ""),
        ("提出期限", blue_return_application_deadline(opened, profile.start_blue_year).strftime("%Y年%m月%d日") if opened else "", "3/15 または開業から2か月以内（土日祝なら翌営業日）"),
    ]
    return {"opening": opening, "blue": blue}
