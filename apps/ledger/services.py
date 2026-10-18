"""帳簿まわりの業務ロジック（確定・見込み計算・年の選択）。"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import transaction

from apps.core.dates import today_local

from .books import actual_by_month, year_overview
from .models import Expense, IncomeStatement, OtherIncome, Receipt, TaxSettings
from .tax import estimate_year, project_year


def get_tax_settings(stylist) -> TaxSettings:
    defaults = settings.TAX_DEFAULTS
    obj, _ = TaxSettings.objects.get_or_create(
        stylist=stylist,
        defaults={"pension_monthly": defaults["pension_monthly"], "nhi_rate_pct": defaults["nhi_rate_pct"], "nhi_cap": defaults["nhi_cap"]},
    )
    return obj


def available_years(stylist) -> list[int]:
    years = set()
    years.update(IncomeStatement.objects.filter(stylist=stylist).values_list("year", flat=True))
    years.update(e.year for e in Expense.objects.filter(stylist=stylist).dates("date", "year"))
    years.update(o.year for o in OtherIncome.objects.filter(stylist=stylist).dates("date", "year"))
    years.add(today_local().year)
    return sorted(years, reverse=True)


@transaction.atomic
def confirm_statement(statement: IncomeStatement) -> IncomeStatement:
    statement.status = IncomeStatement.Status.CONFIRMED
    statement.save(update_fields=["status", "updated_at"])
    statement.sync_deduction_expenses()
    return statement


@transaction.atomic
def unconfirm_statement(statement: IncomeStatement) -> IncomeStatement:
    statement.status = IncomeStatement.Status.DRAFT
    statement.save(update_fields=["status", "updated_at"])
    statement.sync_deduction_expenses()
    return statement


def receipt_initial(receipt: Receipt) -> dict:
    ocr = receipt.ocr_raw or {}
    payment = {"cash": Expense.Payment.CASH, "card": Expense.Payment.PRIVATE, "transfer": Expense.Payment.BANK}.get(ocr.get("payment_hint"), Expense.Payment.PRIVATE)
    items = "、".join(i.get("name", "") for i in ocr.get("items", []) if isinstance(i, dict) and i.get("name"))
    initial = {
        "date": ocr.get("date") or today_local().isoformat(),
        "amount": ocr.get("total") or "",
        "category": ocr.get("suggested_category") if ocr.get("suggested_category") not in (None, "unknown") else "misc",
        "vendor": ocr.get("vendor", "")[:100],
        "description": items[:200],
        "payment_method": payment,
        "business_ratio": 100,
        "notes": (ocr.get("notes") or "")[:200],
    }
    return initial


@transaction.atomic
def apply_receipt(receipt: Receipt, expense: Expense) -> Expense:
    expense.stylist = receipt.stylist
    expense.receipt = receipt
    expense.status = Expense.Status.CONFIRMED
    expense.save()
    receipt.status = Receipt.Status.APPLIED
    receipt.save(update_fields=["status", "updated_at"])
    return expense


def forecast(stylist, year: int, today: date | None = None) -> dict:
    """年間の手取り見込み。実績月＋見込み月 → 税・社保の概算。"""
    today = today or today_local()
    ts = get_tax_settings(stylist)
    actual = actual_by_month(stylist, year)
    if year < today.year:
        current_month = 13  # すべて実績
    elif year > today.year:
        current_month = 1
    else:
        current_month = today.month
    projection = project_year(actual, current_month, ts.projected_monthly_revenue, ts.projected_monthly_expenses)
    params = ts.params(year)
    estimate = estimate_year(projection["revenue_total"], projection["expenses_total"], projection["withheld_total"], params)
    overview = year_overview(stylist, year)
    return {
        "year": year,
        "projection": projection,
        "estimate": estimate,
        "params": params,
        "settings": ts,
        "overview": overview,
        "has_data": bool(actual),
    }
