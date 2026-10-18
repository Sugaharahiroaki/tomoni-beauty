from datetime import date

import pytest

from apps.ledger import books, exports, journal
from apps.ledger.models import Expense, IncomeStatement, OpeningBalance, OtherIncome
from apps.ledger.services import confirm_statement, forecast, unconfirm_statement


@pytest.fixture
def ledger_world(stylist):
    OpeningBalance.objects.create(stylist=stylist, year=2026, cash=50_000, bank=100_000, receivable=0)
    statement = IncomeStatement.objects.create(
        stylist=stylist, year=2026, month=9, salon_name="salon TOMONI", gross_sales=420_000, commission_rate_pct=50,
        commission_amount=210_000, deductions=[{"label": "材料費", "amount": 21_000}, {"label": "振込手数料", "amount": 440}],
        withholding_tax=0, net_paid=188_560, paid_on=date(2026, 10, 10),
    )
    confirm_statement(statement)
    Expense.objects.create(stylist=stylist, date=date(2026, 9, 5), amount=3_000, category="supplies", vendor="100均", payment_method=Expense.Payment.CASH, status=Expense.Status.CONFIRMED)
    Expense.objects.create(stylist=stylist, date=date(2026, 9, 20), amount=10_000, category="communication", vendor="携帯", business_ratio=50, payment_method=Expense.Payment.PRIVATE, status=Expense.Status.CONFIRMED)
    Expense.objects.create(stylist=stylist, date=date(2026, 9, 21), amount=99_999, category="misc", status=Expense.Status.DRAFT)  # 未確定は集計外
    OtherIncome.objects.create(stylist=stylist, date=date(2026, 9, 28), amount=20_000, description="商品販売", received_to=OtherIncome.ReceivedTo.BANK)
    return statement


def test_statement_confirm_creates_deduction_expenses(ledger_world):
    deductions = Expense.objects.filter(statement=ledger_world).order_by("amount")
    assert [(e.category, e.amount) for e in deductions] == [("fees", 440), ("materials", 21_000)]
    assert all(e.status == Expense.Status.CONFIRMED and e.payment_method == Expense.Payment.STATEMENT for e in deductions)
    assert ledger_world.balance_diff == 0
    unconfirm_statement(ledger_world)
    assert all(e.status == Expense.Status.DRAFT for e in Expense.objects.filter(statement=ledger_world))


def test_journal_entries_balance_and_statements(stylist, ledger_world):
    entries = journal.all_entries(stylist, 2026)
    tb = journal.trial_balance(entries)
    assert tb["balanced"] is True
    pl = journal.profit_and_loss(entries)
    assert pl["total_revenue"] == 230_000
    assert pl["total_cogs"] == 21_000
    assert pl["total_expenses"] == 440 + 3_000 + 5_000
    assert pl["net_income"] == 200_560
    bs = journal.balance_sheet(entries)
    assert bs["assets"]["現金"] == 47_000
    assert bs["assets"]["普通預金"] == 308_560
    assert bs["assets"].get("売掛金", 0) == 0
    assert bs["owner_credit"] == 5_000 and bs["capital"] == 150_000
    assert bs["balanced"] is True and bs["total_assets"] == 355_560


def test_general_ledger_running_balance(stylist, ledger_world):
    entries = journal.all_entries(stylist, 2026)
    ledger = {a["account"]: a for a in journal.general_ledger(entries)}
    receivable = ledger["売掛金"]
    assert receivable["rows"][-1]["balance"] == 0
    assert ledger["現金"]["balance"] == 47_000


def test_decision_sheet(stylist, ledger_world):
    d = journal.decision_sheet(stylist, 2026, blue_deduction=100_000)
    lines = dict(d["lines"])
    assert lines["売上（収入）金額"] == 230_000
    assert lines["売上原価（仕入金額）"] == 21_000
    assert lines["青色申告特別控除額"] == 100_000
    assert lines["所得金額"] == 100_560
    assert d["income"] == 100_560


def test_books_aggregations(stylist, ledger_world):
    summary = books.monthly_category_summary(stylist, 2026)
    assert summary["total"] == 21_000 + 440 + 3_000 + 5_000
    assert summary["month_totals"][8] == summary["total"]  # 9月
    codes = {r["code"] for r in summary["rows"]}
    assert codes == {"materials", "fees", "supplies", "communication"}
    inc = books.income_summary(stylist, 2026)
    assert inc["total_revenue"] == 230_000 and inc["total_net"] == 188_560 and inc["total_deductions"] == 21_440
    assert books.receivable_ledger(stylist, 2026)["closing"] == 0
    assert books.cash_book(stylist, 2026)["closing"] == 47_000
    actual = books.actual_by_month(stylist, 2026)
    assert actual == {9: {"revenue": 230_000, "expenses": 29_440, "withheld": 0}}


def test_forecast_uses_actual_and_projection(stylist, ledger_world):
    fc = forecast(stylist, 2026, today=date(2026, 10, 18))
    assert fc["projection"]["months_actual"] == [9]
    assert fc["projection"]["months_projected"] == [10, 11, 12]
    assert fc["projection"]["revenue_total"] == 230_000 * 4
    assert fc["estimate"]["revenue"] == 920_000
    assert fc["estimate"]["net_income"] < 920_000


def test_exports_shapes(stylist, ledger_world):
    entries = journal.all_entries(stylist, 2026)
    yayoi = exports.journal_csv_yayoi(entries).strip().splitlines()
    assert len(yayoi) == len(entries)
    assert all(len(line.split(",")) == 25 for line in yayoi)
    generic = exports.journal_csv_generic(entries).splitlines()
    assert generic[0].startswith("日付,借方科目")
    freee = exports.freee_csv(books.confirmed_expenses(stylist, 2026), books.confirmed_statements(stylist, 2026), books.other_incomes(stylist, 2026)).splitlines()
    assert freee[0].split(",")[0] == "収支区分"
    assert len(freee) == 1 + 1 + 4 + 1  # header + statement + 4 expenses + other income
    d = journal.decision_sheet(stylist, 2026, 100_000)
    etax = exports.etax_summary_csv(d, forecast(stylist, 2026, today=date(2026, 10, 18))["estimate"])
    assert "所得金額" in etax and "源泉徴収税額" in etax
    assert exports.encode("テスト", "cp932").decode("cp932") == "テスト"
    assert exports.encode("a", "utf-8").startswith("﻿".encode("utf-8"))


def test_manual_entry_included(stylist, ledger_world):
    from apps.ledger.models import ManualJournalEntry

    ManualJournalEntry.objects.create(stylist=stylist, date=date(2026, 9, 30), debit_account="事業主貸", credit_account="普通預金", amount=100_000, description="生活費")
    entries = journal.all_entries(stylist, 2026)
    assert journal.check_balanced(entries)
    bs = journal.balance_sheet(entries)
    assert bs["assets"]["普通預金"] == 208_560 and bs["drawings"] == 100_000 and bs["balanced"]
