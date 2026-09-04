import pytest

from summarize import act, adapt, observe, parse_summary_response, plan, summarize_document


SHORT_TEXT = "A short research note about ETFs and diversification."
LONG_TEXT = ("Dollar-cost averaging is a strategy. " * 200)  # well over the direct threshold


class StubLLM:
    """Stand-in for llm.generate, mirroring joshua/tests' StubLLM."""

    def __init__(self, response=None):
        self.response = response or (
            "SUMMARY: A concise summary.\nKEY POINTS:\n- First point\n- Second point"
        )
        self.calls = []

    def __call__(self, prompt, system=None):
        self.calls.append({"prompt": prompt, "system": system})
        return self.response, "stub-model"


# --------------------------------------------------------------------------
# parse_summary_response
# --------------------------------------------------------------------------

def test_parses_well_formed_response():
    text = "SUMMARY: The document discusses ETFs.\nKEY POINTS:\n- Low fees\n- Diversification\n- Tracks an index"

    summary, key_points = parse_summary_response(text)

    assert summary == "The document discusses ETFs."
    assert key_points == ["Low fees", "Diversification", "Tracks an index"]


def test_parses_response_with_numbered_key_points():
    text = "SUMMARY: A note on rates.\nKey Points:\n1. Rates held steady\n2) Inflation cooling"

    summary, key_points = parse_summary_response(text)

    assert summary == "A note on rates."
    assert key_points == ["Rates held steady", "Inflation cooling"]


def test_falls_back_gracefully_when_format_is_ignored():
    text = "This document is about bonds and interest rates in a rising-rate environment."

    summary, key_points = parse_summary_response(text)

    assert summary == text
    assert key_points == []


def test_empty_response_yields_empty_summary_and_no_key_points():
    assert parse_summary_response("") == ("", [])
    assert parse_summary_response(None) == ("", [])


# --------------------------------------------------------------------------
# PLAN
# --------------------------------------------------------------------------

def test_plan_chooses_direct_strategy_for_short_documents():
    result = plan(SHORT_TEXT, direct_char_threshold=3000)

    assert result["phase"] == "plan"
    assert result["strategy"] == "direct"


def test_plan_chooses_map_reduce_strategy_for_long_documents():
    result = plan(LONG_TEXT, direct_char_threshold=3000)

    assert result["strategy"] == "map_reduce"


def test_plan_reads_thresholds_from_environment(monkeypatch):
    monkeypatch.setenv("SUMMARIZE_DIRECT_CHAR_THRESHOLD", "10")
    monkeypatch.setenv("SUMMARIZE_MAX_CHUNKS", "2")

    result = plan(SHORT_TEXT)

    assert result["strategy"] == "map_reduce"  # SHORT_TEXT is longer than 10 chars
    assert result["max_chunks"] == 2


# --------------------------------------------------------------------------
# ACT / OBSERVE
# --------------------------------------------------------------------------

def test_act_direct_strategy_produces_one_segment():
    plan_result = plan(SHORT_TEXT, direct_char_threshold=3000)

    act_result = act(SHORT_TEXT, plan_result)

    assert act_result["strategy"] == "direct"
    assert act_result["segments"] == [SHORT_TEXT]
    assert act_result["truncated"] is False


def test_act_map_reduce_strategy_produces_multiple_segments():
    plan_result = plan(LONG_TEXT, direct_char_threshold=3000, max_chunks=6)

    act_result = act(LONG_TEXT, plan_result)

    assert act_result["strategy"] == "map_reduce"
    assert act_result["segment_count"] > 1


def test_act_truncates_when_more_chunks_than_max_chunks():
    plan_result = plan(LONG_TEXT, direct_char_threshold=3000, max_chunks=1)

    act_result = act(LONG_TEXT, plan_result)

    assert act_result["segment_count"] == 1
    assert act_result["truncated"] is True


def test_observe_flags_needs_reduce_only_for_multi_segment_map_reduce():
    plan_result = plan(LONG_TEXT, direct_char_threshold=3000, max_chunks=6)
    act_result = act(LONG_TEXT, plan_result)

    observe_result = observe(act_result)

    assert observe_result["needs_reduce"] is True

    direct_plan = plan(SHORT_TEXT, direct_char_threshold=3000)
    direct_act = act(SHORT_TEXT, direct_plan)
    direct_observe = observe(direct_act)
    assert direct_observe["needs_reduce"] is False


# --------------------------------------------------------------------------
# ADAPT
# --------------------------------------------------------------------------

def test_adapt_direct_strategy_makes_exactly_one_llm_call():
    stub = StubLLM()
    plan_result = plan(SHORT_TEXT, direct_char_threshold=3000)
    act_result = act(SHORT_TEXT, plan_result)
    observe_result = observe(act_result)

    result = adapt(observe_result, generate_fn=stub)

    assert result["llm_called"] is True
    assert result["llm_call_count"] == 1
    assert len(stub.calls) == 1
    assert result["summary_text"] == "A concise summary."
    assert result["key_points"] == ["First point", "Second point"]


def test_adapt_map_reduce_calls_once_per_segment_plus_one_reduce_call():
    stub = StubLLM()
    plan_result = plan(LONG_TEXT, direct_char_threshold=3000, max_chunks=4)
    act_result = act(LONG_TEXT, plan_result)
    observe_result = observe(act_result)

    result = adapt(observe_result, generate_fn=stub)

    assert result["llm_called"] is True
    assert len(stub.calls) == len(observe_result["segments"]) + 1
    assert result["llm_call_count"] == len(observe_result["segments"]) + 1


def test_adapt_never_calls_the_model_for_empty_segments():
    observe_result = {"strategy": "direct", "segments": [], "needs_reduce": False}
    stub = StubLLM()

    result = adapt(observe_result, generate_fn=stub)

    assert result["llm_called"] is False
    assert result["llm_call_count"] == 0
    assert stub.calls == []


def test_summarize_document_runs_the_full_loop():
    stub = StubLLM()

    plan_result, act_result, observe_result, adapt_result = summarize_document(
        SHORT_TEXT, generate_fn=stub
    )

    assert plan_result["phase"] == "plan"
    assert act_result["phase"] == "act"
    assert observe_result["phase"] == "observe"
    assert adapt_result["phase"] == "adapt"
    assert adapt_result["summary_text"] == "A concise summary."
