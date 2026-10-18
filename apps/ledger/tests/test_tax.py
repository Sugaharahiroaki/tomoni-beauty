from apps.ledger.tax import TaxParams, basic_deduction, estimate_year, floor_to, income_tax, national_health_insurance, project_year, resident_tax


def test_floor_to():
    assert floor_to(999_260, 1000) == 999_000
    assert floor_to(50_998, 100) == 50_900
    assert floor_to(-5, 1000) == 0


def test_income_tax_brackets():
    # 195万以下 5%: 97,500 + 復興税 2,047 = 99,547 → 100円未満切捨て
    assert income_tax(1_950_000) == 99_500
    assert income_tax(1_950_500) == 99_500  # 1,000円未満切捨て
    # 330万: 330,000 − 97,500 = 232,500 + 4,882 = 237,382 → 237,300
    assert income_tax(3_300_000) == 237_300
    # 695万: 1,390,000 − 427,500 = 962,500 + 20,212 = 982,712 → 982,700
    assert income_tax(6_950_000) == 982_700
    assert income_tax(0) == 0
    assert income_tax(-100) == 0


def test_basic_deduction_2026_table():
    assert basic_deduction(1_320_000) == 950_000
    assert basic_deduction(1_320_001) == 880_000
    assert basic_deduction(3_360_000) == 880_000
    assert basic_deduction(4_890_000) == 680_000
    assert basic_deduction(6_550_000) == 630_000
    assert basic_deduction(10_000_000) == 580_000
    assert basic_deduction(23_500_001) == 480_000
    assert basic_deduction(30_000_000) == 0


def test_basic_deduction_2027_onward():
    assert basic_deduction(1_000_000, year=2027) == 950_000
    assert basic_deduction(2_000_000, year=2027) == 580_000
    assert basic_deduction(24_200_000, year=2027) == 320_000


def test_nhi_and_resident_tax():
    p = TaxParams(nhi_rate_pct=11.0, nhi_cap=1_090_000)
    assert national_health_insurance(2_300_000, p) == 205_700
    assert national_health_insurance(400_000, p) == 0
    assert national_health_insurance(50_000_000, p) == 1_090_000  # 上限
    assert resident_tax(2_300_000, 420_740, p) == 149_900
    assert resident_tax(400_000, 0, p) == 0


def test_estimate_year_full_example():
    p = TaxParams(year=2026, blue_deduction=100_000, pension_monthly=17_920, include_pension=True, nhi_rate_pct=11.0, nhi_cap=1_090_000)
    e = estimate_year(3_000_000, 600_000, 0, p)
    assert e["profit"] == 2_400_000
    assert e["blue_deduction"] == 100_000
    assert e["business_income"] == 2_300_000
    assert e["nhi"] == 205_700
    assert e["pension"] == 215_040
    assert e["basic_deduction"] == 880_000
    assert e["taxable_income"] == 999_000
    assert e["income_tax"] == 50_900
    assert e["resident_tax"] == 149_900
    assert e["balance_due"] == 50_900
    assert e["net_income"] == 1_778_460
    assert e["net_income_monthly"] == 148_205


def test_estimate_blue_deduction_capped_by_profit():
    p = TaxParams(blue_deduction=650_000, include_pension=False)
    e = estimate_year(50_000, 0, 0, p)
    assert e["blue_deduction"] == 50_000
    assert e["business_income"] == 0
    assert e["income_tax"] == 0 and e["resident_tax"] == 0 and e["nhi"] == 0
    assert e["net_income"] == 50_000


def test_estimate_refund_when_withheld_exceeds_tax():
    p = TaxParams(blue_deduction=100_000, include_pension=False)
    e = estimate_year(1_000_000, 200_000, 100_000, p)
    assert e["income_tax"] == 0
    assert e["balance_due"] == -100_000  # 還付


def test_estimate_handles_loss():
    e = estimate_year(300_000, 500_000, 0, TaxParams())
    assert e["profit"] == 0 and e["income_tax"] == 0
    assert e["net_income"] == 300_000 - 500_000 - e["pension"]


def test_project_year_fills_remaining_months_with_average():
    actual = {1: {"revenue": 200_000, "expenses": 50_000, "withheld": 0}, 2: {"revenue": 300_000, "expenses": 70_000, "withheld": 0}}
    p = project_year(actual, current_month=3)
    assert p["months_projected"] == list(range(3, 13))
    assert p["monthly_revenue_assumed"] == 250_000
    assert p["revenue_total"] == 500_000 + 250_000 * 10
    assert p["expenses_total"] == 120_000 + 60_000 * 10


def test_project_year_overrides_and_past_year():
    actual = {9: {"revenue": 230_000, "expenses": 29_440, "withheld": 0}}
    p = project_year(actual, current_month=10, override_monthly_revenue=100_000)
    assert p["months_projected"] == [10, 11, 12]
    assert p["revenue_total"] == 230_000 + 300_000
    assert p["expenses_total"] == 29_440 + 29_440 * 3
    done = project_year(actual, current_month=13)
    assert done["months_projected"] == [] and done["revenue_total"] == 230_000


def test_project_year_skips_future_months_with_data():
    actual = {5: {"revenue": 100_000, "expenses": 0, "withheld": 0}}
    p = project_year(actual, current_month=3)
    assert 5 not in p["months_projected"]
    assert p["months_projected"] == [3, 4, 6, 7, 8, 9, 10, 11, 12]
