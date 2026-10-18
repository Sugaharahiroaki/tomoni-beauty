"""所得税・住民税・社会保険料の概算（純粋関数・テスト対象）。

すべて「見込み」のための簡略計算。実際の税額は控除の内容・自治体・年度の改正で変わる。
最終的な申告内容は税理士の確認を前提とする。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 所得税の速算表（上限, 税率, 控除額）
INCOME_TAX_BRACKETS = [
    (1_950_000, 0.05, 0),
    (3_300_000, 0.10, 97_500),
    (6_950_000, 0.20, 427_500),
    (9_000_000, 0.23, 636_000),
    (18_000_000, 0.33, 1_536_000),
    (40_000_000, 0.40, 2_796_000),
    (None, 0.45, 4_796_000),
]
RECONSTRUCTION_SURTAX = 0.021

# 基礎控除（所得税）: 2025年分からの改正。2025・2026年分は所得に応じた上乗せあり
BASIC_DEDUCTION_2025_2026 = [
    (1_320_000, 950_000),
    (3_360_000, 880_000),
    (4_890_000, 680_000),
    (6_550_000, 630_000),
    (23_500_000, 580_000),
    (24_000_000, 480_000),
    (24_500_000, 320_000),
    (25_000_000, 160_000),
    (None, 0),
]
BASIC_DEDUCTION_2027_ONWARD = [
    (1_320_000, 950_000),
    (23_500_000, 580_000),
    (24_000_000, 480_000),
    (24_500_000, 320_000),
    (25_000_000, 160_000),
    (None, 0),
]

BLUE_DEDUCTION_CHOICES = [
    (100_000, "10万円（簡易簿記）"),
    (550_000, "55万円（複式簿記・紙提出）"),
    (650_000, "65万円（複式簿記・e-Tax または電子帳簿保存）"),
]


@dataclass
class TaxParams:
    year: int = 2026
    blue_deduction: int = 100_000
    pension_monthly: int = 17_920
    include_pension: bool = True
    nhi_rate_pct: float = 11.0
    nhi_cap: int = 1_090_000
    nhi_basic_deduction: int = 430_000
    resident_tax_rate_pct: float = 10.0
    resident_tax_flat: int = 5_000
    resident_basic_deduction: int = 430_000
    other_deductions: int = 0  # 生命保険料控除・配偶者控除・医療費控除などの合計（手入力）
    extra: dict = field(default_factory=dict)


def floor_to(value: int, unit: int) -> int:
    value = int(value)
    if value <= 0:
        return 0
    return value - (value % unit)


def basic_deduction(total_income: int, year: int = 2026) -> int:
    table = BASIC_DEDUCTION_2025_2026 if year <= 2026 else BASIC_DEDUCTION_2027_ONWARD
    for limit, amount in table:
        if limit is None or total_income <= limit:
            return amount
    return 0


def income_tax(taxable_income: int) -> int:
    """課税所得（1,000円未満切捨て済み or 生値）→ 所得税＋復興特別所得税（100円未満切捨て）。"""
    taxable = floor_to(taxable_income, 1000)
    if taxable <= 0:
        return 0
    base = 0
    for limit, rate, deduction in INCOME_TAX_BRACKETS:
        if limit is None or taxable <= limit:
            base = int(taxable * rate) - deduction
            break
    base = max(base, 0)
    surtax = int(base * RECONSTRUCTION_SURTAX)
    return floor_to(base + surtax, 100)


def national_pension(params: TaxParams) -> int:
    return params.pension_monthly * 12 if params.include_pension else 0


def national_health_insurance(business_income: int, params: TaxParams) -> int:
    """国民健康保険の概算: (所得 − 基礎控除43万) × 料率、上限あり。市区町村で大きく異なる。"""
    base = max(business_income - params.nhi_basic_deduction, 0)
    return min(int(base * params.nhi_rate_pct / 100), params.nhi_cap)


def resident_tax(business_income: int, social_insurance: int, params: TaxParams) -> int:
    """住民税の概算: 所得割10%＋均等割。基礎控除は43万（住民税側）。"""
    taxable = floor_to(business_income - social_insurance - params.other_deductions - params.resident_basic_deduction, 1000)
    if taxable <= 0:
        return 0
    return floor_to(int(taxable * params.resident_tax_rate_pct / 100) + params.resident_tax_flat, 100)


def estimate_year(revenue: int, expenses: int, withheld: int, params: TaxParams) -> dict:
    """年間の収入・経費から、税・社会保険・手取りの見込みを計算する。"""
    revenue = max(int(revenue), 0)
    expenses = max(int(expenses), 0)
    profit = max(revenue - expenses, 0)  # 青色申告特別控除前の所得
    blue = min(params.blue_deduction, profit)  # 控除は所得が上限
    business_income = profit - blue  # 事業所得

    nhi = national_health_insurance(business_income, params)
    pension = national_pension(params)
    social = nhi + pension
    basic = basic_deduction(business_income, params.year)
    taxable = floor_to(business_income - social - params.other_deductions - basic, 1000)
    itax = income_tax(taxable)
    rtax = resident_tax(business_income, social, params)
    balance_due = itax - withheld  # 正: 納付 / 負: 還付

    net = revenue - expenses - itax - rtax - nhi - pension
    return {
        "revenue": revenue,
        "expenses": expenses,
        "profit": profit,
        "blue_deduction": blue,
        "business_income": business_income,
        "nhi": nhi,
        "pension": pension,
        "social_insurance": social,
        "basic_deduction": basic,
        "other_deductions": params.other_deductions,
        "taxable_income": taxable,
        "income_tax": itax,
        "withheld": withheld,
        "balance_due": balance_due,
        "resident_tax": rtax,
        "net_income": net,
        "net_income_monthly": int(net / 12),
        "effective_rate_pct": round((itax + rtax + nhi + pension) / revenue * 100, 1) if revenue else 0.0,
    }


def project_year(actual_by_month: dict[int, dict], current_month: int, override_monthly_revenue: int | None = None, override_monthly_expenses: int | None = None) -> dict:
    """月ごとの実績（revenue / expenses / withheld）から年間を見込む。

    実績のある月はそのまま、残りの月は平均（または上書き値）で埋める。
    current_month 以降の月を「未来」とみなす。
    """
    months_actual = sorted(m for m in actual_by_month if 1 <= m <= 12)
    rev_actual = sum(int(actual_by_month[m].get("revenue", 0)) for m in months_actual)
    exp_actual = sum(int(actual_by_month[m].get("expenses", 0)) for m in months_actual)
    wh_actual = sum(int(actual_by_month[m].get("withheld", 0)) for m in months_actual)
    n = len(months_actual)
    avg_rev = int(rev_actual / n) if n else 0
    avg_exp = int(exp_actual / n) if n else 0
    avg_wh = int(wh_actual / n) if n else 0

    remaining = [m for m in range(1, 13) if m not in months_actual and m >= current_month]
    monthly_rev = override_monthly_revenue if override_monthly_revenue is not None else avg_rev
    monthly_exp = override_monthly_expenses if override_monthly_expenses is not None else avg_exp

    return {
        "months_actual": months_actual,
        "months_projected": remaining,
        "revenue_actual": rev_actual,
        "expenses_actual": exp_actual,
        "withheld_actual": wh_actual,
        "monthly_revenue_assumed": monthly_rev,
        "monthly_expenses_assumed": monthly_exp,
        "revenue_total": rev_actual + monthly_rev * len(remaining),
        "expenses_total": exp_actual + monthly_exp * len(remaining),
        "withheld_total": wh_actual + (avg_wh * len(remaining) if override_monthly_revenue is None else 0),
    }
