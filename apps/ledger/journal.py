"""複式簿記: 仕訳の自動生成、総勘定元帳、試算表、損益計算書、貸借対照表（第3段階）。

業務委託美容師向けの超簡易版。前提:
- 報酬は月末に売掛金/売上高で計上（発生主義）、支払日に普通預金/売掛金で入金
- 明細の控除（材料費・場所代等）は月末に 経費/売掛金、源泉徴収は 事業主貸/売掛金
- 経費の支払: 現金→現金、事業用口座・カード→普通預金、個人の財布→事業主借
- 消費税は免税事業者を想定し、税区分は扱わない（インボイス登録者は税理士に確認）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .categories import ACCOUNTS, ACCOUNT_ORDER, DEBIT_NORMAL, EXPENSE_CATEGORIES, category_account
from .models import Expense, IncomeStatement, ManualJournalEntry, OpeningBalance, OtherIncome


@dataclass(frozen=True)
class Entry:
    date: date
    debit: str
    credit: str
    amount: int
    description: str
    source: str  # opening | statement | payment | expense | other_income | manual

    def as_dict(self) -> dict:
        return {"date": self.date, "debit": self.debit, "credit": self.credit, "amount": self.amount, "description": self.description, "source": self.source}


PAYMENT_CREDIT = {
    Expense.Payment.CASH: "現金",
    Expense.Payment.BANK: "普通預金",
    Expense.Payment.PRIVATE: "事業主借",
    Expense.Payment.STATEMENT: "売掛金",
}


def opening_entries(stylist, year: int) -> list[Entry]:
    ob = OpeningBalance.objects.filter(stylist=stylist, year=year).first()
    if not ob:
        return []
    d = date(year, 1, 1)
    out = []
    for account, amount in (("現金", ob.cash), ("普通預金", ob.bank), ("売掛金", ob.receivable)):
        if amount:
            out.append(Entry(d, account, "元入金", amount, "期首残高", "opening"))
    return out


def statement_entries(statement: IncomeStatement) -> list[Entry]:
    out = []
    pe = statement.period_end
    label = f"{statement.month}月分 報酬 {statement.salon_name}".strip()
    if statement.commission_amount:
        out.append(Entry(pe, "売掛金", "売上高", statement.commission_amount, label, "statement"))
    for exp in statement.deduction_expenses.filter(status=Expense.Status.CONFIRMED):
        if exp.business_amount:
            out.append(Entry(pe, exp.account_name, "売掛金", exp.business_amount, f"{statement.month}月分 {exp.description}（明細控除）", "statement"))
    if statement.withholding_tax:
        out.append(Entry(pe, "事業主貸", "売掛金", statement.withholding_tax, f"{statement.month}月分 源泉所得税", "statement"))
    if statement.paid_on and statement.net_paid:
        out.append(Entry(statement.paid_on, "普通預金", "売掛金", statement.net_paid, f"{statement.month}月分 報酬入金", "payment"))
    return out


def expense_entries(expense: Expense) -> list[Entry]:
    if expense.statement_id:
        return []  # 明細側で起票
    amount = expense.business_amount
    if amount <= 0:
        return []
    desc = " ".join(x for x in (expense.vendor, expense.description) if x) or expense.category_label
    return [Entry(expense.date, expense.account_name, PAYMENT_CREDIT[expense.payment_method], amount, desc, "expense")]


def other_income_entries(income: OtherIncome) -> list[Entry]:
    debit = "現金" if income.received_to == OtherIncome.ReceivedTo.CASH else "普通預金"
    out = [Entry(income.date, debit, "雑収入", income.amount - income.withholding_tax, income.description, "other_income")]
    if income.withholding_tax:
        out.append(Entry(income.date, "事業主貸", "雑収入", income.withholding_tax, f"{income.description} 源泉所得税", "other_income"))
    return out


def auto_entries(stylist, year: int) -> list[Entry]:
    entries = opening_entries(stylist, year)
    for s in IncomeStatement.objects.filter(stylist=stylist, status=IncomeStatement.Status.CONFIRMED, year=year).prefetch_related("deduction_expenses"):
        entries.extend(statement_entries(s))
    for e in Expense.objects.filter(stylist=stylist, status=Expense.Status.CONFIRMED, date__year=year, statement__isnull=True):
        entries.extend(expense_entries(e))
    for o in OtherIncome.objects.filter(stylist=stylist, date__year=year):
        entries.extend(other_income_entries(o))
    return entries


def manual_entries(stylist, year: int) -> list[Entry]:
    return [Entry(m.date, m.debit_account, m.credit_account, m.amount, m.description or "手入力", "manual") for m in ManualJournalEntry.objects.filter(stylist=stylist, date__year=year)]


def all_entries(stylist, year: int) -> list[Entry]:
    entries = auto_entries(stylist, year) + manual_entries(stylist, year)
    return sorted(entries, key=lambda e: (e.date, e.source != "opening", e.description))


def account_type(name: str) -> str:
    return ACCOUNTS.get(name, "expense")


def general_ledger(entries: list[Entry]) -> list[dict]:
    """総勘定元帳: 勘定科目ごとの明細と残高。"""
    accounts: dict[str, dict] = {}
    for e in entries:
        for side, name in (("debit", e.debit), ("credit", e.credit)):
            acc = accounts.setdefault(name, {"account": name, "type": account_type(name), "rows": [], "debit_total": 0, "credit_total": 0})
            amount = e.amount
            acc[side + "_total"] += amount
            acc["rows"].append({"date": e.date, "description": e.description, "counter": e.credit if side == "debit" else e.debit, "debit": amount if side == "debit" else 0, "credit": amount if side == "credit" else 0})
    out = []
    for name in sorted(accounts, key=lambda n: ACCOUNT_ORDER.index(n) if n in ACCOUNT_ORDER else 99):
        acc = accounts[name]
        acc["rows"].sort(key=lambda r: r["date"])
        running = 0
        debit_normal = acc["type"] in DEBIT_NORMAL
        for r in acc["rows"]:
            running += (r["debit"] - r["credit"]) if debit_normal else (r["credit"] - r["debit"])
            r["balance"] = running
        acc["balance"] = running
        out.append(acc)
    return out


def trial_balance(entries: list[Entry]) -> dict:
    ledger = general_ledger(entries)
    rows = []
    debit_total = credit_total = 0
    for acc in ledger:
        bal = acc["balance"]
        debit_normal = acc["type"] in DEBIT_NORMAL
        debit = bal if (debit_normal and bal >= 0) or (not debit_normal and bal < 0) else 0
        credit = bal if (not debit_normal and bal >= 0) or (debit_normal and bal < 0) else 0
        debit, credit = abs(debit), abs(credit)
        debit_total += debit
        credit_total += credit
        rows.append({"account": acc["account"], "type": acc["type"], "debit": debit, "credit": credit})
    return {"rows": rows, "debit_total": debit_total, "credit_total": credit_total, "balanced": debit_total == credit_total}


def profit_and_loss(entries: list[Entry]) -> dict:
    ledger = {a["account"]: a for a in general_ledger(entries)}
    revenue = {name: a["balance"] for name, a in ledger.items() if a["type"] == "revenue"}
    cogs = {name: a["balance"] for name, a in ledger.items() if a["type"] == "cogs"}
    expenses = {name: a["balance"] for name, a in ledger.items() if a["type"] == "expense"}
    total_revenue = sum(revenue.values())
    total_cogs = sum(cogs.values())
    total_expenses = sum(expenses.values())
    gross = total_revenue - total_cogs
    net = gross - total_expenses
    return {
        "revenue": revenue,
        "total_revenue": total_revenue,
        "cogs": cogs,
        "total_cogs": total_cogs,
        "gross_profit": gross,
        "expenses": expenses,
        "total_expenses": total_expenses,
        "net_income": net,
    }


def balance_sheet(entries: list[Entry]) -> dict:
    ledger = {a["account"]: a for a in general_ledger(entries)}
    assets = {n: a["balance"] for n, a in ledger.items() if a["type"] == "asset"}
    drawings = ledger.get("事業主貸", {}).get("balance", 0)
    owner_credit = ledger.get("事業主借", {}).get("balance", 0)
    capital = ledger.get("元入金", {}).get("balance", 0)
    pl = profit_and_loss(entries)
    total_assets = sum(assets.values()) + drawings
    total_equity = capital + owner_credit + pl["net_income"]
    return {
        "assets": assets,
        "drawings": drawings,
        "total_assets": total_assets,
        "liabilities": {},
        "owner_credit": owner_credit,
        "capital": capital,
        "net_income": pl["net_income"],
        "total_liabilities_equity": total_equity,
        "balanced": total_assets == total_equity,
    }


def decision_sheet(stylist, year: int, blue_deduction: int) -> dict:
    """青色申告決算書（一般用）1ページ目の損益計算書に転記するための集計。"""
    entries = all_entries(stylist, year)
    pl = profit_and_loss(entries)
    lines = [("売上（収入）金額", pl["total_revenue"])]
    lines.append(("売上原価（仕入金額）", pl["total_cogs"]))
    lines.append(("差引金額", pl["gross_profit"]))
    for c in EXPENSE_CATEGORIES:
        if c[4] != "expense":
            continue
        amount = pl["expenses"].get(c[3], 0)
        if amount:
            lines.append((c[3], amount))
    lines.append(("経費計", pl["total_expenses"]))
    lines.append(("差引金額（青色申告特別控除前の所得金額）", pl["net_income"]))
    blue = min(blue_deduction, max(pl["net_income"], 0))
    lines.append(("青色申告特別控除額", blue))
    lines.append(("所得金額", pl["net_income"] - blue))
    bs = balance_sheet(entries)
    tb = trial_balance(entries)
    return {"lines": lines, "pl": pl, "bs": bs, "trial_balance": tb, "entries": entries, "blue_deduction": blue, "income": pl["net_income"] - blue}


def check_balanced(entries: list[Entry]) -> bool:
    return trial_balance(entries)["balanced"]
