from datetime import date, timedelta

import calculations


DEFAULT_WINDOW_DAYS = 30
DUE_SOON_DAYS = 7

INTRODUCTIONS = {
    "neutral": "Review the following bills and subscriptions that need attention.",
    "direct": "Take action on the bills and subscriptions listed below.",
    "supportive": "Use the action list below to stay on top of upcoming commitments.",
}


# PLAN: choose the review scope and priorities.
def plan(review_date=None, window_days=DEFAULT_WINDOW_DAYS):
    try:
        review_day = (
            date.today()
            if review_date in (None, "")
            else date.fromisoformat(review_date)
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Review date must use YYYY-MM-DD format.") from error

    try:
        window_days = int(window_days)
    except (TypeError, ValueError) as error:
        raise ValueError("Window days must be a number.") from error

    if not 1 <= window_days <= 90:
        raise ValueError("Window days must be between 1 and 90.")

    review_end = review_day + timedelta(days=window_days)

    return {
        "phase": "plan",
        "description": "Review active bills, renewals and trials in the selected period.",
        "review_date": review_day.isoformat(),
        "window_days": window_days,
        "review_end_date": review_end.isoformat(),
        "due_soon_days": DUE_SOON_DAYS,
        "priority_order": [
            "overdue bills",
            "trials ending soon",
            "payments due soon",
            "automatic renewals",
        ],
    }


# ACT: calculate costs and important dates.
def act(bills, plan_result):
    review_day = date.fromisoformat(plan_result["review_date"])
    active_bills = []

    for bill in bills:
        if bill["status"] != "active":
            continue

        due_date = date.fromisoformat(bill["next_due_date"])
        monthly_cost = calculations.monthly_cost(
            bill["amount"],
            bill["billing_frequency"],
        )

        active_bills.append({
            "id": bill["id"],
            "name": bill["name"],
            "provider": bill["provider"],
            "category": bill["category"],
            "amount": bill["amount"],
            "billing_frequency": bill["billing_frequency"],
            "monthly_cost": round(monthly_cost, 2),
            "annual_cost": round(monthly_cost * 12, 2),
            "next_due_date": bill["next_due_date"],
            "days_until_due": (due_date - review_day).days,
            "auto_renew": bool(bill["auto_renew"]),
            "trial_end_date": bill["trial_end_date"],
        })

    active_bills.sort(
        key=lambda bill: (bill["days_until_due"], bill["name"])
    )

    summary = calculations.build_cost_summary(bills)

    return {
        "phase": "act",
        "description": "Calculate recurring costs and days until each payment.",
        "active_bill_count": len(active_bills),
        "monthly_cost": summary["monthly_cost"],
        "annual_cost": summary["annual_cost"],
        "bills": active_bills,
    }


def _alert_bill(bill):
    return {
        "id": bill["id"],
        "name": bill["name"],
        "provider": bill["provider"],
        "next_due_date": bill["next_due_date"],
        "days_until_due": bill["days_until_due"],
        "monthly_cost": bill["monthly_cost"],
    }


# OBSERVE: flag items that need attention.
def observe(act_result, plan_result):
    review_day = date.fromisoformat(plan_result["review_date"])
    window_days = plan_result["window_days"]

    overdue = []
    due_soon = []
    upcoming_auto_renewals = []
    expiring_trials = []
    attention_ids = set()

    for bill in act_result["bills"]:
        days_until_due = bill["days_until_due"]

        if days_until_due < 0:
            overdue.append(_alert_bill(bill))
            attention_ids.add(bill["id"])
        elif days_until_due <= DUE_SOON_DAYS:
            due_soon.append(_alert_bill(bill))
            attention_ids.add(bill["id"])

        if bill["auto_renew"] and 0 <= days_until_due <= window_days:
            upcoming_auto_renewals.append(_alert_bill(bill))
            attention_ids.add(bill["id"])

        if bill["trial_end_date"]:
            trial_end = date.fromisoformat(bill["trial_end_date"])
            days_until_trial_end = (trial_end - review_day).days

            if 0 <= days_until_trial_end <= window_days:
                expiring_trials.append({
                    "id": bill["id"],
                    "name": bill["name"],
                    "provider": bill["provider"],
                    "trial_end_date": bill["trial_end_date"],
                    "days_until_trial_end": days_until_trial_end,
                })
                attention_ids.add(bill["id"])

    return {
        "phase": "observe",
        "description": "Flag overdue bills, near-term payments, renewals and trials.",
        "attention_count": len(attention_ids),
        "overdue": overdue,
        "due_soon": due_soon,
        "upcoming_auto_renewals": upcoming_auto_renewals,
        "expiring_trials": expiring_trials,
    }


def _day_label(days):
    return "day" if days == 1 else "days"


def _future_label(days):
    if days == 0:
        return "today"

    return f"in {days} {_day_label(days)}"


def _count_label(count, singular):
    label = singular if count == 1 else f"{singular}s"
    return f"{count} {label}"


# Build exact actions from the calculated alerts.
def build_actions(observe_result):
    actions = []
    added_ids = set()

    for bill in observe_result["overdue"]:
        overdue_days = abs(bill["days_until_due"])
        actions.append(
            f"Review or pay {bill['name']} from {bill['provider']}. It was due "
            f"on {bill['next_due_date']} and is {overdue_days} "
            f"{_day_label(overdue_days)} overdue."
        )
        added_ids.add(bill["id"])

    for trial in observe_result["expiring_trials"]:
        days = trial["days_until_trial_end"]
        actions.append(
            f"Decide whether to keep or cancel {trial['name']} from "
            f"{trial['provider']} before its trial ends on "
            f"{trial['trial_end_date']} {_future_label(days)}."
        )
        added_ids.add(trial["id"])

    for bill in observe_result["due_soon"]:
        if bill["id"] in added_ids:
            continue

        actions.append(
            f"Prepare for {bill['name']} from {bill['provider']}, which is due "
            f"on {bill['next_due_date']} {_future_label(bill['days_until_due'])}."
        )
        added_ids.add(bill["id"])

    for bill in observe_result["upcoming_auto_renewals"]:
        if bill["id"] in added_ids:
            continue

        actions.append(
            f"Review whether to keep {bill['name']} from {bill['provider']} "
            f"before it renews automatically on {bill['next_due_date']} "
            f"{_future_label(bill['days_until_due'])}."
        )
        added_ids.add(bill["id"])

    return actions


# Pick the first item using the planned order.
def choose_priority(observe_result):
    if observe_result["overdue"]:
        bill = observe_result["overdue"][0]
        return {
            "type": "overdue",
            "reason": f"{bill['name']} is overdue and should be reviewed first.",
        }

    if observe_result["expiring_trials"]:
        trial = observe_result["expiring_trials"][0]
        return {
            "type": "trial",
            "reason": f"The {trial['name']} trial ends soon and needs a decision.",
        }

    if observe_result["due_soon"]:
        bill = observe_result["due_soon"][0]
        return {
            "type": "due_soon",
            "reason": f"{bill['name']} is due soon and should be prepared for.",
        }

    if observe_result["upcoming_auto_renewals"]:
        bill = observe_result["upcoming_auto_renewals"][0]
        return {
            "type": "renewal",
            "reason": f"{bill['name']} will renew automatically and should be reviewed.",
        }

    return {
        "type": "clear",
        "reason": "No bills or subscriptions need attention in this period.",
    }


# Ask Ollama to choose a tone from the review results.
def build_adapt_prompt(act_result, observe_result, priority):
    return (
        "Choose a tone for introducing a bills and subscriptions action list. "
        f"The monthly cost is ${act_result['monthly_cost']:.2f}. "
        f"There are {_count_label(len(observe_result['overdue']), 'overdue bill')}, "
        f"{_count_label(len(observe_result['due_soon']), 'payment')} due soon, "
        f"{_count_label(len(observe_result['upcoming_auto_renewals']), 'renewal')} "
        f"and {_count_label(len(observe_result['expiring_trials']), 'trial')} ending. "
        f"The main priority is {priority['type']}. "
        "Reply with exactly one word: neutral, direct, or supportive. "
        "Do not include any other text."
    )


# ADAPT: explain the calculated alerts in plain language.
def adapt(act_result, observe_result, generate_fn, model_name):
    actions = build_actions(observe_result)
    priority = choose_priority(observe_result)

    if observe_result["attention_count"] == 0:
        return {
            "phase": "adapt",
            "description": "Provide a plain-language action summary.",
            "llm_called": False,
            "model_name": model_name,
            "summary": "No bills or subscriptions need attention in this period.",
            "summary_tone": "neutral",
            "priority": priority,
            "actions": [],
            "summary_fallback_used": False,
        }

    summary_tone = generate_fn(
        build_adapt_prompt(act_result, observe_result, priority)
    ).strip().lower()
    summary_fallback_used = summary_tone not in INTRODUCTIONS

    if summary_fallback_used:
        summary_tone = "neutral"

    summary = INTRODUCTIONS[summary_tone]

    return {
        "phase": "adapt",
        "description": "Provide a plain-language action summary.",
        "llm_called": True,
        "model_name": model_name,
        "summary": summary,
        "summary_tone": summary_tone,
        "priority": priority,
        "actions": actions,
        "summary_fallback_used": summary_fallback_used,
    }
