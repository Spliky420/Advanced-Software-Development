"""Plan -> Act -> Observe -> Adapt drift review.

The four phases of the agentic loop are the four public functions below, in
order. Plan, Act and Observe are pure Python and involve no LLM at all; only
Adapt talks to the model, and only ever about breaches Observe already found.

No Flask imports here, and nothing in this module rounds: rounding belongs at
the output layer, the same rule allocation.py follows.
"""

import os

import llm

DEFAULT_DRIFT_THRESHOLD_PERCENT = 5.0

DRIFT_SYSTEM_PROMPT = (
    "You are a portfolio reporting assistant. You will be given a list of "
    "asset classes whose actual allocation has drifted away from its target "
    "allocation by at least a stated threshold. Each line states the asset "
    "class, its target percentage, its actual percentage, the size of the "
    "drift in percentage points, and whether it is overweight or underweight. "
    "Using only those figures, write a short plain-English paragraph naming "
    "which asset classes are overweight and which are underweight, and by how "
    "many percentage points. Describe only -- never recommend trades, never "
    "give advice, and never make predictions. Never perform arithmetic "
    "yourself, and never introduce, restate or recalculate any figure that is "
    "not given to you exactly as provided below."
)


def get_threshold_percent():
    """Drift threshold in percentage points, from DRIFT_THRESHOLD_PERCENT.

    Read at call time rather than import time so a container can set it
    without the module being re-imported. Unparseable or negative values fall
    back to the default rather than failing the request.
    """
    raw = os.environ.get("DRIFT_THRESHOLD_PERCENT")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_DRIFT_THRESHOLD_PERCENT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_DRIFT_THRESHOLD_PERCENT
    if value < 0:
        return DEFAULT_DRIFT_THRESHOLD_PERCENT
    return value


def plan(targets, threshold_percent=None):
    """PLAN: decide which asset classes to examine and at what threshold."""
    threshold = get_threshold_percent() if threshold_percent is None else float(threshold_percent)
    target_by_class = {t["asset_class"]: float(t["target_percent"]) for t in targets}

    return {
        "phase": "plan",
        "description": (
            "Read the allocation targets and set the drift threshold that "
            "decides which asset classes count as off-target."
        ),
        "threshold_percent": threshold,
        "asset_classes_to_examine": sorted(target_by_class),
        "target_percent_by_class": target_by_class,
    }


def act(portfolio, plan_result):
    """ACT: compute actual allocation and per-class drift in percentage points.

    Coverage is the union of the planned classes and the classes actually
    held: a class held with no target is real drift (target treated as 0) and
    would be invisible if only the planned list were walked.
    """
    target_by_class = plan_result["target_percent_by_class"]
    actual_by_class = {
        item["asset_class"]: item for item in portfolio["asset_class_allocation"]
    }

    drift_by_class = []
    for asset_class in sorted(set(target_by_class) | set(actual_by_class)):
        target_percent = target_by_class.get(asset_class, 0.0)
        actual = actual_by_class.get(asset_class)
        actual_percent = actual["percent_of_total"] if actual is not None else 0.0
        market_value = actual["market_value"] if actual is not None else 0.0

        drift_by_class.append({
            "asset_class": asset_class,
            "target_percent": target_percent,
            "actual_percent": actual_percent,
            "market_value": market_value,
            # Positive = above target (overweight), negative = below target.
            "drift_percentage_points": actual_percent - target_percent,
            "has_target": asset_class in target_by_class,
            "is_held": actual is not None,
        })

    return {
        "phase": "act",
        "description": (
            "Compute the current allocation and the drift, in percentage "
            "points, between actual and target for each asset class."
        ),
        "total_market_value": portfolio["total_market_value"],
        "drift_by_class": drift_by_class,
    }


def observe(act_result, plan_result):
    """OBSERVE: flag classes at or beyond the threshold as over/underweight.

    Pure Python -- no LLM involvement. A drift of exactly the threshold counts
    as a breach.
    """
    threshold = plan_result["threshold_percent"]

    breaches = []
    within_threshold = []
    for row in act_result["drift_by_class"]:
        drift = row["drift_percentage_points"]
        if abs(drift) >= threshold:
            classified = dict(row)
            if drift > 0:
                classified["direction"] = "overweight"
            elif drift < 0:
                classified["direction"] = "underweight"
            else:
                classified["direction"] = "on_target"
            classified["drift_magnitude"] = abs(drift)
            breaches.append(classified)
        else:
            within_threshold.append(row)

    breaches.sort(key=lambda r: r["drift_magnitude"], reverse=True)

    return {
        "phase": "observe",
        "description": (
            "Identify which asset classes breach the drift threshold and "
            "classify each as overweight or underweight."
        ),
        "threshold_percent": threshold,
        "breach_count": len(breaches),
        "breaches": breaches,
        "within_threshold": within_threshold,
    }


def build_drift_prompt(observe_result):
    """Format the observed breaches as finished figures for the model."""
    lines = [
        f"Drift threshold: {observe_result['threshold_percent']:.2f} percentage points",
        "Asset classes breaching the threshold:",
    ]
    for breach in observe_result["breaches"]:
        lines.append(
            f"- {breach['asset_class']}: target {breach['target_percent']:.2f}%, "
            f"actual {breach['actual_percent']:.2f}%, "
            f"{breach['drift_magnitude']:.2f} percentage points {breach['direction']}"
        )
    return "\n".join(lines)


def adapt(observe_result, generate_fn=None):
    """ADAPT: have the model describe the observed breaches in plain English.

    Only the breaches are sent. When nothing breached, this says so directly
    and never calls the LLM.
    """
    if observe_result["breach_count"] == 0:
        return {
            "phase": "adapt",
            "description": (
                "Report the observed breaches in plain English, or state "
                "directly that there were none."
            ),
            "llm_called": False,
            "summary": (
                f"No asset class has drifted by "
                f"{observe_result['threshold_percent']:.2f} percentage points or more "
                f"from its target, so the portfolio is within the configured "
                f"drift threshold."
            ),
            "prompt_sent": None,
            "model_name": None,
        }

    generate = generate_fn if generate_fn is not None else llm.generate
    figures = build_drift_prompt(observe_result)
    response_text, model_name = generate(figures, system=DRIFT_SYSTEM_PROMPT)

    return {
        "phase": "adapt",
        "description": (
            "Report the observed breaches in plain English, or state "
            "directly that there were none."
        ),
        "llm_called": True,
        "summary": response_text,
        "prompt_sent": DRIFT_SYSTEM_PROMPT + "\n\n" + figures,
        "model_name": model_name,
    }
