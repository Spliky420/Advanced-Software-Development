import pytest

import calculations


@pytest.mark.parametrize(
    ("frequency", "expected"),
    [
        ("weekly", 52.0),
        ("fortnightly", 26.0),
        ("monthly", 12.0),
        ("quarterly", 4.0),
        ("yearly", 1.0),
    ],
)
def test_monthly_cost_converts_each_frequency(frequency, expected):
    assert calculations.monthly_cost(12, frequency) == pytest.approx(expected)


def test_summary_uses_active_bills_only():
    bills = [
        {
            "amount": 20,
            "billing_frequency": "monthly",
            "category": "Software",
            "auto_renew": 1,
            "status": "active",
        },
        {
            "amount": 120,
            "billing_frequency": "yearly",
            "category": "Insurance",
            "auto_renew": 0,
            "status": "active",
        },
        {
            "amount": 50,
            "billing_frequency": "monthly",
            "category": "Other",
            "auto_renew": 1,
            "status": "paused",
        },
    ]

    summary = calculations.build_cost_summary(bills)

    assert summary["active_bill_count"] == 2
    assert summary["auto_renew_count"] == 1
    assert summary["monthly_cost"] == 30.0
    assert summary["annual_cost"] == 360.0
    assert summary["category_monthly_costs"] == {
        "Insurance": 10.0,
        "Software": 20.0,
    }
