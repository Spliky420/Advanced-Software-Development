# Converts each billing period into a monthly amount.
MONTHLY_MULTIPLIERS = {
    "weekly": 52 / 12,
    "fortnightly": 26 / 12,
    "monthly": 1,
    "quarterly": 1 / 3,
    "yearly": 1 / 12,
}


def monthly_cost(amount, billing_frequency):
    return float(amount) * MONTHLY_MULTIPLIERS[billing_frequency]


def build_cost_summary(bills):
    active_bills = [
        bill for bill in bills
        if bill["status"] == "active"
    ]

    monthly_total = 0
    category_totals = {}

    for bill in active_bills:
        cost = monthly_cost(
            bill["amount"],
            bill["billing_frequency"],
        )

        monthly_total += cost

        category = bill["category"]
        category_totals[category] = (
            category_totals.get(category, 0) + cost
        )

    return {
        "active_bill_count": len(active_bills),
        "auto_renew_count": sum(
            1 for bill in active_bills
            if bill["auto_renew"]
        ),
        "monthly_cost": round(monthly_total, 2),
        "annual_cost": round(monthly_total * 12, 2),
        "category_monthly_costs": {
            category: round(cost, 2)
            for category, cost in sorted(category_totals.items())
        },
    }