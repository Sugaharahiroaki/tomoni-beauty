"""簡易簿記向けの集計・帳簿（月別科目別、経費帳、売掛帳、現金出納帳）。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .categories import EXPENSE_CATEGORIES, category_label
from .models import Expense, IncomeStatement, OpeningBalance, OtherIncome


def confirmed_expenses(stylist, year: int):
    return Expense.objects.filter(stylist=stylist, status=Expense.Status.CONFIRMED, date__year=year).order_by("date", "id")


def confirmed_statements(stylist, year: int):
    return IncomeStatement.objects.filter(stylist=stylist, status=IncomeStatement.Status.CONFIRMED, year=year).order_by("month", "id")


def other_incomes(stylist, year: int):
    return OtherIncome.objects.filter(stylist=stylist, date__year=year).order_by("date", "id")


def monthly_category_summary(stylist, year: int) -> dict:
    months = {m: defaultdict(int) for m in range(1, 13)}
    totals = defaultdict(int)
    for e in confirmed_expenses(stylist, year):
        months[e.date.month][e.category] += e.business_amount
        totals[e.category] += e.business_amount
    used = [c for c in EXPENSE_CATEGORIES if totals.get(c[0])]
    rows = []
    for c in used:
        code = c[0]
        rows.append({"code": code, "label": c[1], "section": c[4], "months": [months[m].get(code, 0) for m in range(1, 13)], "total": totals[code]})
    month_totals = [sum(months[m].values()) for m in range(1, 13)]
    return {"rows": rows, "month_totals": month_totals, "total": sum(month_totals), "year": year}


def income_summary(stylist, year: int) -> dict:
    statements = list(confirmed_statements(stylist, year))
    others = list(other_incomes(stylist, year))
    by_month = defaultdict(lambda: {"revenue": 0, "deductions": 0, "withheld": 0, "net": 0, "other": 0})
    for s in statements:
        m = by_month[s.month]
        m["revenue"] += s.commission_amount
        m["deductions"] += s.deductions_total
        m["withheld"] += s.withholding_tax
        m["net"] += s.net_paid
    for o in others:
        by_month[o.date.month]["other"] += o.amount
        by_month[o.date.month]["withheld"] += o.withholding_tax
    total_revenue = sum(s.commission_amount for s in statements) + sum(o.amount for o in others)
    return {
        "statements": statements,
        "others": others,
        "by_month": [{"month": m, **by_month[m]} for m in range(1, 13)],
        "total_revenue": total_revenue,
        "total_commission": sum(s.commission_amount for s in statements),
        "total_other": sum(o.amount for o in others),
        "total_deductions": sum(s.deductions_total for s in statements),
        "total_withheld": sum(s.withholding_tax for s in statements) + sum(o.withholding_tax for o in others),
        "total_net": sum(s.net_paid for s in statements),
        "year": year,
    }


def expense_ledger(stylist, year: int) -> list[dict]:
    """経費帳（科目別の明細）。"""
    groups = defaultdict(list)
    for e in confirmed_expenses(stylist, year):
        groups[e.category].append(e)
    out = []
    for c in EXPENSE_CATEGORIES:
        rows = groups.get(c[0])
        if not rows:
            continue
        out.append({"code": c[0], "label": c[1], "account": c[3], "rows": rows, "total": sum(r.business_amount for r in rows)})
    return out


def receivable_ledger(stylist, year: int) -> dict:
    """売掛帳: 報酬の発生（月末）→ 控除・源泉 → 入金。"""
    opening = OpeningBalance.objects.filter(stylist=stylist, year=year).first()
    balance = opening.receivable if opening else 0
    rows = []
    if balance:
        rows.append({"date": date(year, 1, 1), "description": "前年からの未入金", "debit": balance, "credit": 0, "balance": balance})
    events = []
    for s in confirmed_statements(stylist, year):
        events.append((s.period_end, 0, f"{s.month}月分 報酬（{s.salon_name}）", s.commission_amount, 0))
        if s.deductions_total:
            events.append((s.period_end, 1, f"{s.month}月分 控除（材料費・場所代等）", 0, s.deductions_total))
        if s.withholding_tax:
            events.append((s.period_end, 2, f"{s.month}月分 源泉徴収", 0, s.withholding_tax))
        if s.paid_on:
            events.append((s.paid_on, 3, f"{s.month}月分 入金", 0, s.net_paid))
    for ev in sorted(events, key=lambda x: (x[0], x[1])):
        balance += ev[3] - ev[4]
        rows.append({"date": ev[0], "description": ev[2], "debit": ev[3], "credit": ev[4], "balance": balance})
    return {"rows": rows, "closing": balance}


def cash_book(stylist, year: int) -> dict:
    """現金出納帳: 現金で支払った経費・現金で受け取った収入。"""
    opening = OpeningBalance.objects.filter(stylist=stylist, year=year).first()
    balance = opening.cash if opening else 0
    rows = [{"date": date(year, 1, 1), "description": "前年繰越", "income": 0, "expense": 0, "balance": balance}] if opening else []
    events = []
    for e in confirmed_expenses(stylist, year).filter(payment_method=Expense.Payment.CASH):
        events.append((e.date, f"{e.category_label} {e.vendor} {e.description}".strip(), 0, e.business_amount))
    for o in other_incomes(stylist, year).filter(received_to=OtherIncome.ReceivedTo.CASH):
        events.append((o.date, o.description, o.amount, 0))
    for ev in sorted(events, key=lambda x: x[0]):
        balance += ev[2] - ev[3]
        rows.append({"date": ev[0], "description": ev[1], "income": ev[2], "expense": ev[3], "balance": balance})
    return {"rows": rows, "closing": balance}


def year_overview(stylist, year: int) -> dict:
    inc = income_summary(stylist, year)
    exp = monthly_category_summary(stylist, year)
    return {
        "year": year,
        "revenue": inc["total_revenue"],
        "expenses": exp["total"],
        "profit": inc["total_revenue"] - exp["total"],
        "withheld": inc["total_withheld"],
        "income": inc,
        "expense_summary": exp,
    }


def actual_by_month(stylist, year: int) -> dict[int, dict]:
    """手取り見込み用: 月ごとの収入・経費・源泉（確定分のみ、収入のある月だけ）。"""
    inc = income_summary(stylist, year)
    exp = monthly_category_summary(stylist, year)
    out = {}
    for row in inc["by_month"]:
        m = row["month"]
        revenue = row["revenue"] + row["other"]
        if revenue:
            out[m] = {"revenue": revenue, "expenses": exp["month_totals"][m - 1], "withheld": row["withheld"]}
    return out


def category_label_safe(code: str) -> str:
    return category_label(code)
