import pytest

import review


def sample_bills():
    return [
        {
            "id": 1,
            "name": "Overdue Bill",
            "provider": "Provider A",
            "category": "Utilities",
            "amount": 40,
            "billing_frequency": "monthly",
            "next_due_date": "2026-08-31",
            "auto_renew": 1,
            "trial_end_date": None,
            "status": "active",
        },
        {
            "id": 2,
            "name": "Trial App",
            "provider": "Provider B",
            "category": "Software",
            "amount": 20,
            "billing_frequency": "monthly",
            "next_due_date": "2026-09-03",
            "auto_renew": 1,
            "trial_end_date": "2026-09-03",
            "status": "active",
        },
        {
            "id": 3,
            "name": "Paused Bill",
            "provider": "Provider C",
            "category": "Other",
            "amount": 10,
            "billing_frequency": "monthly",
            "next_due_date": "2026-09-02",
            "auto_renew": 0,
            "trial_end_date": None,
            "status": "paused",
        },
    ]


def test_plan_sets_scope_and_priority_order():
    result = review.plan("2026-09-01", 30)

    assert result["review_end_date"] == "2026-10-01"
    assert result["due_soon_days"] == 7
    assert result["priority_order"][0] == "overdue bills"


@pytest.mark.parametrize("window_days", [0, 91, "not-a-number"])
def test_plan_rejects_invalid_window(window_days):
    with pytest.raises(ValueError):
        review.plan("2026-09-01", window_days)


def test_act_and_observe_return_calculated_findings():
    plan_result = review.plan("2026-09-01", 30)
    act_result = review.act(sample_bills(), plan_result)
    observe_result = review.observe(act_result, plan_result)

    assert act_result["active_bill_count"] == 2
    assert [bill["id"] for bill in act_result["bills"]] == [1, 2]
    assert len(observe_result["overdue"]) == 1
    assert len(observe_result["due_soon"]) == 1
    assert len(observe_result["upcoming_auto_renewals"]) == 1
    assert len(observe_result["expiring_trials"]) == 1
    assert observe_result["attention_count"] == 2


def test_adapt_prioritises_overdue_bill_and_uses_model_tone():
    plan_result = review.plan("2026-09-01", 30)
    act_result = review.act(sample_bills(), plan_result)
    observe_result = review.observe(act_result, plan_result)
    prompts = []

    result = review.adapt(
        act_result,
        observe_result,
        generate_fn=lambda prompt: prompts.append(prompt) or "direct",
        model_name="test-model",
    )

    assert result["priority"]["type"] == "overdue"
    assert result["summary_tone"] == "direct"
    assert result["actions"][0].startswith("Review or pay Overdue Bill")
    assert "1 overdue bill" in prompts[0]


def test_adapt_uses_safe_summary_for_unexpected_model_output():
    plan_result = review.plan("2026-09-01", 30)
    act_result = review.act(sample_bills(), plan_result)
    observe_result = review.observe(act_result, plan_result)

    result = review.adapt(
        act_result,
        observe_result,
        generate_fn=lambda prompt: "unexpected response",
        model_name="test-model",
    )

    assert result["summary_tone"] == "neutral"
    assert result["summary_fallback_used"] is True


def test_adapt_skips_model_when_nothing_needs_attention():
    empty_observation = {
        "attention_count": 0,
        "overdue": [],
        "due_soon": [],
        "upcoming_auto_renewals": [],
        "expiring_trials": [],
    }

    result = review.adapt(
        {"monthly_cost": 0},
        empty_observation,
        generate_fn=lambda prompt: pytest.fail("Ollama should not be called"),
        model_name="test-model",
    )

    assert result["llm_called"] is False
    assert result["priority"]["type"] == "clear"
    assert result["actions"] == []
