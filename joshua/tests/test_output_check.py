"""The ADAPT output check: figures must be supplied AND attached to the right
asset class and direction.

QWEN_SUMMARY is verbatim what qwen2.5:0.5b returned in a live end-to-end run
on 2026-10-01. Every number in it appears in the figures block, so the
supplied-figures check passed it -- yet it swaps classes' drifts and lists
ETFs as both overweight and underweight.
"""

import drift

BREACHES = [
    ("ETFs", 15.0, 24.3, 9.3, "overweight"),
    ("Australian equities", 20.0, 11.66, 8.34, "underweight"),
    ("Crypto", 10.0, 18.26, 8.26, "overweight"),
    ("International equities", 15.0, 6.87, 8.13, "underweight"),
    ("REITs", 10.0, 2.65, 7.35, "underweight"),
    ("Term deposits", 5.0, 10.52, 5.52, "overweight"),
]

OBSERVE = {
    "run_id": "e2e",
    "threshold_percent": 5.0,
    "breach_count": len(BREACHES),
    "breaches": [
        {"asset_class": name, "target_percent": target, "actual_percent": actual,
         "drift_magnitude": magnitude, "direction": direction}
        for name, target, actual, magnitude, direction in BREACHES
    ],
}

QWEN_SUMMARY = (
    "The portfolio is overweight in the following asset classes:\n\n"
    "- ETFs: 8.34 percentage points\n"
    "- Australian equities: 8.26 percentage points\n"
    "- Crypto: 8.26 percentage points\n"
    "- International equities: 5.52 percentage points\n"
    "- REITs: 7.35 percentage points\n"
    "- Term deposits: 5.52 percentage points\n\n"
    "The portfolio is underweight in the following asset classes:\n\n"
    "- ETFs: 24.30 percentage points\n"
    "- Australian equities: 11.66 percentage points\n"
    "- Crypto: 8.34 percentage points\n"
    "- International equities: 6.87 percentage points\n"
    "- REITs: 7.35 percentage points\n"
    "- Term deposits: 10.52 percentage points"
)


def test_the_live_qwen_summary_passes_the_supplied_figures_check():
    """Documents the gap: membership alone cannot catch this summary."""
    figures = drift.build_drift_prompt(OBSERVE)

    assert drift.unsupplied_figures(QWEN_SUMMARY, figures) == []


def test_the_live_qwen_summary_is_caught_by_the_binding_check():
    problems = drift.misattributed_figures(QWEN_SUMMARY, OBSERVE)

    figure_errors = {(p["asset_class"], p["figure"]) for p in problems if p["figure"] is not None}
    direction_errors = {(p["asset_class"], p["direction"]) for p in problems if p["direction"]}

    # Another class's drift attached to ETFs.
    assert ("ETFs", 8.34) in figure_errors
    # ETFs listed under the underweight heading.
    assert ("ETFs", "underweight") in direction_errors
    # Australian equities listed under the overweight heading.
    assert ("Australian equities", "overweight") in direction_errors


def test_adapt_replaces_the_live_qwen_summary_with_the_python_fallback():
    result = drift.adapt(OBSERVE, generate_fn=lambda prompt, system=None: (QWEN_SUMMARY, "qwen2.5:0.5b"))

    assert result["summary_source"] == "fallback"
    assert result["unsupplied_figures"] == []
    assert result["misattributed"]
    assert result["summary"] == drift.build_fallback_summary(OBSERVE)
    assert result["model_response"] == QWEN_SUMMARY


def test_a_correct_summary_passes_both_checks():
    correct = (
        "ETFs are 9.30 percentage points overweight (target 15.00%, actual 24.30%). "
        "Australian equities are 8.34 percentage points underweight.\n"
        "Underweight classes:\n"
        "- REITs: 7.35 percentage points\n"
        "- International equities: 8.13 percentage points"
    )

    assert drift.misattributed_figures(correct, OBSERVE) == []
    result = drift.adapt(OBSERVE, generate_fn=lambda prompt, system=None: (correct, "m"))
    assert result["summary_source"] == "model"


def test_the_python_fallback_passes_its_own_check():
    fallback = drift.build_fallback_summary(OBSERVE)

    assert drift.misattributed_figures(fallback, OBSERVE) == []
    assert drift.unsupplied_figures(fallback, drift.build_drift_prompt(OBSERVE)) == []


def test_numbers_in_a_clause_naming_several_classes_are_not_judged():
    # Which number belongs to which class cannot be told apart here.
    text = "ETFs and Crypto are overweight by 9.30 and 8.26 percentage points."

    assert drift.misattributed_figures(text, OBSERVE) == []


def test_a_shared_direction_must_hold_for_every_class_named():
    text = "ETFs and REITs are overweight."

    assert drift.misattributed_figures(text, OBSERVE) == [
        {"asset_class": "REITs", "figure": None, "direction": "overweight"},
    ]


def test_the_live_qwen_comma_list_is_caught():
    """Second live qwen2.5:0.5b output from the same run: REITs is underweight."""
    text = (
        "The portfolio is overweight in ETFs with a 9.30 percentage point drift, "
        "underweight in Australian equities with a 8.34 percentage point drift, "
        "and overweight in REITs with a 7.35 percentage point drift."
    )

    assert drift.misattributed_figures(text, OBSERVE) == [
        {"asset_class": "REITs", "figure": None, "direction": "overweight"},
    ]


def test_the_threshold_may_appear_beside_any_class():
    text = "REITs breached the 5.00 percentage point threshold and are underweight."

    assert drift.misattributed_figures(text, OBSERVE) == []
