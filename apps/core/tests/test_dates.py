from datetime import date

from apps.core.dates import compute_follow_up_date, month_end_exclusive, month_start, recommended_visit_date, shift_months, year_month


def test_recommended_visit_date_uses_weeks():
    assert recommended_visit_date(date(2026, 10, 1), 6) == date(2026, 11, 12)


def test_recommended_visit_date_falls_back_to_default_cycle():
    assert recommended_visit_date(date(2026, 10, 1), None, default_cycle_weeks=4) == date(2026, 10, 29)
    # settings default = 6 weeks
    assert recommended_visit_date(date(2026, 10, 1), None) == date(2026, 11, 12)
    assert recommended_visit_date(date(2026, 10, 1), 0) == date(2026, 11, 12)


def test_follow_up_is_lead_days_before_target():
    assert compute_follow_up_date(date(2026, 10, 1), 6, lead_days=7) == date(2026, 11, 5)
    assert compute_follow_up_date(date(2026, 10, 1), 6, lead_days=0) == date(2026, 11, 12)


def test_follow_up_never_before_day_after_visit():
    # 1週間後が目安で7日前に送る → 来店当日になってしまうので翌日に繰り下げ
    assert compute_follow_up_date(date(2026, 10, 1), 1, lead_days=7) == date(2026, 10, 2)
    assert compute_follow_up_date(date(2026, 10, 1), 1, lead_days=30) == date(2026, 10, 2)


def test_follow_up_crosses_year_boundary():
    assert compute_follow_up_date(date(2026, 12, 20), 4, lead_days=7) == date(2027, 1, 10)


def test_month_helpers():
    assert month_start(date(2026, 2, 17)) == date(2026, 2, 1)
    assert month_end_exclusive(date(2026, 2, 17)) == date(2026, 3, 1)
    assert month_end_exclusive(date(2028, 2, 1)) == date(2028, 3, 1)  # 閏年
    assert month_end_exclusive(date(2026, 12, 5)) == date(2027, 1, 1)
    assert shift_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert shift_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert year_month(date(2026, 3, 9)) == "2026-03"
