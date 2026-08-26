import pytest

import drift
from drift import DEFAULT_DRIFT_THRESHOLD_PERCENT, act, adapt, observe, plan


def make_targets(**pairs):
    return [{"asset_class": k, "target_percent": v} for k, v in pairs.items()]


def make_portfolio(total_market_value, **class_percents):
    """Build the portfolio shape allocation.build_portfolio_report returns."""
    return {
        "total_market_value": total_market_value,
        "asset_class_allocation": [
            {
                "asset_class": asset_class,
                "market_value": total_market_value * percent / 100,
                "percent_of_total": percent,
            }
            for asset_class, percent in class_percents.items()
        ],
    }


class StubLLM:
    """Simple stub standing in for llm.generate."""

    def __init__(self, response="stub response"):
        self.response = response
        self.calls = []

    def __call__(self, prompt, system=None):
        self.calls.append({"prompt": prompt, "system": system})
        return self.response, "stub-model"


# --------------------------------------------------------------------------
# PLAN
# --------------------------------------------------------------------------

def test_plan_defaults_to_5_percent_when_env_unset(monkeypatch):
    monkeypatch.delenv("DRIFT_THRESHOLD_PERCENT", raising=False)

    result = plan(make_targets(Cash=50, Crypto=50))

    assert result["phase"] == "plan"
    assert result["threshold_percent"] == DEFAULT_DRIFT_THRESHOLD_PERCENT == 5.0


def test_plan_reads_threshold_from_environment(monkeypatch):
    monkeypatch.setenv("DRIFT_THRESHOLD_PERCENT", "2.5")

    assert plan(make_targets(Cash=100))["threshold_percent"] == pytest.approx(2.5)


@pytest.mark.parametrize("bad_value", ["", "   ", "abc", "-3"])
def test_plan_falls_back_to_default_on_unusable_env_value(monkeypatch, bad_value):
    monkeypatch.setenv("DRIFT_THRESHOLD_PERCENT", bad_value)

    assert plan(make_targets(Cash=100))["threshold_percent"] == DEFAULT_DRIFT_THRESHOLD_PERCENT


def test_plan_lists_target_classes_and_percentages(monkeypatch):
    monkeypatch.delenv("DRIFT_THRESHOLD_PERCENT", raising=False)

    result = plan(make_targets(Crypto=10, Cash=30, ETFs=60))

    assert result["asset_classes_to_examine"] == ["Cash", "Crypto", "ETFs"]
    assert result["target_percent_by_class"] == {"Cash": 30.0, "Crypto": 10.0, "ETFs": 60.0}


# --------------------------------------------------------------------------
# ACT
# --------------------------------------------------------------------------

def test_act_computes_drift_in_percentage_points():
    plan_result = plan(make_targets(Cash=30, Crypto=10, ETFs=60), threshold_percent=5)
    portfolio = make_portfolio(1000.0, Cash=25.0, Crypto=18.0, ETFs=57.0)

    rows = {r["asset_class"]: r for r in act(portfolio, plan_result)["drift_by_class"]}

    assert rows["Cash"]["drift_percentage_points"] == pytest.approx(-5.0)
    assert rows["Crypto"]["drift_percentage_points"] == pytest.approx(8.0)
    assert rows["ETFs"]["drift_percentage_points"] == pytest.approx(-3.0)
    assert rows["Crypto"]["market_value"] == pytest.approx(180.0)


def test_act_covers_a_class_held_with_no_target():
    plan_result = plan(make_targets(Cash=100), threshold_percent=5)
    portfolio = make_portfolio(1000.0, Cash=70.0, Crypto=30.0)

    rows = {r["asset_class"]: r for r in act(portfolio, plan_result)["drift_by_class"]}

    assert "Crypto" in rows, "a held class with no target must still be examined"
    assert rows["Crypto"]["target_percent"] == 0.0
    assert rows["Crypto"]["drift_percentage_points"] == pytest.approx(30.0)
    assert rows["Crypto"]["has_target"] is False
    assert rows["Crypto"]["is_held"] is True


def test_act_covers_a_targeted_class_that_is_not_held():
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    portfolio = make_portfolio(1000.0, Cash=100.0)

    rows = {r["asset_class"]: r for r in act(portfolio, plan_result)["drift_by_class"]}

    assert rows["Crypto"]["actual_percent"] == 0.0
    assert rows["Crypto"]["market_value"] == 0.0
    assert rows["Crypto"]["drift_percentage_points"] == pytest.approx(-50.0)
    assert rows["Crypto"]["is_held"] is False


def test_act_does_not_round_mid_calculation():
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    # Two-thirds / one-third split gives non-terminating decimals.
    portfolio = make_portfolio(900.0, Cash=200 / 3, Crypto=100 / 3)

    rows = {r["asset_class"]: r for r in act(portfolio, plan_result)["drift_by_class"]}

    assert rows["Cash"]["actual_percent"] == pytest.approx(200 / 3, rel=1e-12)
    assert rows["Cash"]["drift_percentage_points"] == pytest.approx(200 / 3 - 50, rel=1e-12)


def test_act_on_empty_portfolio_reports_full_underweight():
    plan_result = plan(make_targets(Cash=60, Crypto=40), threshold_percent=5)
    portfolio = make_portfolio(0.0)

    rows = {r["asset_class"]: r for r in act(portfolio, plan_result)["drift_by_class"]}

    assert rows["Cash"]["drift_percentage_points"] == pytest.approx(-60.0)
    assert rows["Crypto"]["drift_percentage_points"] == pytest.approx(-40.0)


# --------------------------------------------------------------------------
# OBSERVE
# --------------------------------------------------------------------------

def test_observe_classifies_overweight_and_underweight():
    plan_result = plan(make_targets(Cash=30, Crypto=10, ETFs=60), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=22.0, Crypto=18.0, ETFs=60.0), plan_result)

    result = observe(act_result, plan_result)
    by_class = {b["asset_class"]: b for b in result["breaches"]}

    assert result["phase"] == "observe"
    assert result["breach_count"] == 2
    assert by_class["Crypto"]["direction"] == "overweight"
    assert by_class["Crypto"]["drift_magnitude"] == pytest.approx(8.0)
    assert by_class["Cash"]["direction"] == "underweight"
    assert by_class["Cash"]["drift_magnitude"] == pytest.approx(8.0)
    assert [r["asset_class"] for r in result["within_threshold"]] == ["ETFs"]


def test_observe_reports_no_breaches_when_all_within_threshold():
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=52.0, Crypto=48.0), plan_result)

    result = observe(act_result, plan_result)

    assert result["breach_count"] == 0
    assert result["breaches"] == []
    assert len(result["within_threshold"]) == 2


def test_observe_treats_drift_exactly_at_threshold_as_a_breach():
    plan_result = plan(make_targets(Cash=45, Crypto=55), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=50.0, Crypto=50.0), plan_result)

    result = observe(act_result, plan_result)

    assert result["breach_count"] == 2
    assert {b["asset_class"] for b in result["breaches"]} == {"Cash", "Crypto"}


def test_observe_sorts_breaches_by_magnitude_descending():
    plan_result = plan(make_targets(Cash=40, Crypto=30, ETFs=30), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=10.0, Crypto=50.0, ETFs=40.0), plan_result)

    result = observe(act_result, plan_result)

    assert [b["asset_class"] for b in result["breaches"]] == ["Cash", "Crypto", "ETFs"]
    magnitudes = [b["drift_magnitude"] for b in result["breaches"]]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_observe_respects_a_custom_threshold():
    act_and_plan = plan(make_targets(Cash=50, Crypto=50), threshold_percent=1)
    act_result = act(make_portfolio(1000.0, Cash=52.0, Crypto=48.0), act_and_plan)

    assert observe(act_result, act_and_plan)["breach_count"] == 2


# --------------------------------------------------------------------------
# ADAPT -- stubbed, to prove the no-breach path never reaches the LLM
# --------------------------------------------------------------------------

def test_adapt_does_not_call_the_llm_when_nothing_breaches():
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=51.0, Crypto=49.0), plan_result)
    observe_result = observe(act_result, plan_result)

    stub = StubLLM()
    result = adapt(observe_result, generate_fn=stub)

    assert stub.calls == []
    assert result["llm_called"] is False
    assert result["model_name"] is None
    assert "within the configured drift threshold" in result["summary"]


def test_adapt_sends_only_breaches_to_the_llm():
    plan_result = plan(make_targets(Cash=30, Crypto=10, ETFs=60), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=22.0, Crypto=18.0, ETFs=60.0), plan_result)
    observe_result = observe(act_result, plan_result)

    stub = StubLLM("Crypto is overweight and Cash is underweight.")
    result = adapt(observe_result, generate_fn=stub)

    assert len(stub.calls) == 1
    prompt = stub.calls[0]["prompt"]
    assert "Crypto" in prompt and "Cash" in prompt
    assert "ETFs" not in prompt, "classes within threshold must not be sent to the LLM"
    assert result["llm_called"] is True
    assert result["summary"] == "Crypto is overweight and Cash is underweight."
    assert result["model_name"] == "stub-model"


def test_adapt_prompt_forbids_advice_and_arithmetic():
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=80.0, Crypto=20.0), plan_result)
    observe_result = observe(act_result, plan_result)

    stub = StubLLM()
    adapt(observe_result, generate_fn=stub)

    system = stub.calls[0]["system"]
    assert "never recommend trades" in system
    assert "never give advice" in system
    assert "Never perform arithmetic" in system


def test_adapt_defaults_to_the_real_llm_module(monkeypatch):
    """generate_fn is injectable, but the default path is llm.generate."""
    plan_result = plan(make_targets(Cash=50, Crypto=50), threshold_percent=5)
    act_result = act(make_portfolio(1000.0, Cash=80.0, Crypto=20.0), plan_result)
    observe_result = observe(act_result, plan_result)

    stub = StubLLM("from llm module")
    monkeypatch.setattr(drift.llm, "generate", stub)

    result = adapt(observe_result)

    assert len(stub.calls) == 1
    assert result["summary"] == "from llm module"
