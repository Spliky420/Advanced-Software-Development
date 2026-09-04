"""Plan -> Act -> Observe -> Adapt document summarization.

The four phases of the agentic loop are the four public functions below, in
order. Plan, Act and Observe are pure Python; only Adapt talks to the model,
and it may do so more than once -- a long document is summarized map-reduce
style (each chunk summarized, then the chunk summaries combined), but every
one of those calls still happens inside the Adapt phase, so "only ADAPT talks
to the model" holds exactly as it does in joshua/backend/drift.py.

Nothing here computes a number. The model's job is genuinely to read text and
condense it -- that is what summarization is -- not to calculate a figure, so
this does not conflict with CLAUDE.md's arithmetic rule. The rule is about
numeric figures (totals, percentages); Plan/Act/Observe still do all of the
non-model decision-making (chunk boundaries, which strategy to use), and the
model never invents a number of its own because none is ever asked of it.
"""

import os
import re

import embeddings
import llm

DEFAULT_DIRECT_CHAR_THRESHOLD = 3000
DEFAULT_MAP_REDUCE_CHUNK_SIZE = 2000
DEFAULT_MAX_CHUNKS = 6

MAP_SYSTEM_PROMPT = (
    "You are a research library assistant. You will be given one excerpt "
    "from a longer financial document. Condense it into 2-3 sentences that "
    "preserve its concrete claims and figures exactly as written. Do not "
    "add information that is not in the excerpt, and do not perform any "
    "calculation."
)

FINAL_SYSTEM_PROMPT = (
    "You are a research library assistant. You will be given text about a "
    "financial document -- either the full document or condensed excerpts "
    "of it. Using only that text, respond in exactly this format:\n\n"
    "SUMMARY: <a concise 2-4 sentence summary of the document>\n"
    "KEY POINTS:\n"
    "- <first key point>\n"
    "- <second key point>\n"
    "- <third key point>\n\n"
    "Write 3 to 6 key points, one per line, each starting with a hyphen. "
    "Describe only what the text says -- never give financial advice or "
    "recommendations, never invent a fact or figure not present in the "
    "text, and never perform arithmetic."
)

KEY_POINTS_MARKER_RE = re.compile(r"key\s*points\s*:?", re.IGNORECASE)
SUMMARY_MARKER_RE = re.compile(r"^\s*summary\s*:?", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _get_int_env(name, default):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def parse_summary_response(text):
    """Parse the model's `SUMMARY: ... KEY POINTS: ...` formatted response.

    Never raises -- a model that ignores the format still yields a usable
    summary (the whole response) and an empty key_points list rather than a
    crash.
    """
    if not isinstance(text, str) or not text.strip():
        return "", []
    text = text.strip()

    kp_match = KEY_POINTS_MARKER_RE.search(text)
    if kp_match:
        summary_part = text[: kp_match.start()]
        points_part = text[kp_match.end() :]
    else:
        summary_part = text
        points_part = ""

    summary_part = SUMMARY_MARKER_RE.sub("", summary_part, count=1).strip()
    if not summary_part:
        summary_part = text

    key_points = []
    for line in points_part.splitlines():
        cleaned = BULLET_RE.sub("", line.strip()).strip()
        if cleaned:
            key_points.append(cleaned)

    return summary_part, key_points


def plan(body_text, direct_char_threshold=None, max_chunks=None):
    """PLAN: decide whether this document is short enough to summarize in one
    pass, or needs to be chunked and summarized map-reduce style.
    """
    threshold = (
        _get_int_env("SUMMARIZE_DIRECT_CHAR_THRESHOLD", DEFAULT_DIRECT_CHAR_THRESHOLD)
        if direct_char_threshold is None
        else direct_char_threshold
    )
    cap = (
        _get_int_env("SUMMARIZE_MAX_CHUNKS", DEFAULT_MAX_CHUNKS)
        if max_chunks is None
        else max_chunks
    )

    strategy = "direct" if len(body_text) <= threshold else "map_reduce"

    return {
        "phase": "plan",
        "description": (
            "Decide whether the document is short enough to summarize in a "
            "single pass, or long enough to need chunking and a map-reduce pass."
        ),
        "strategy": strategy,
        "direct_char_threshold": threshold,
        "max_chunks": cap,
        "document_length": len(body_text),
    }


def act(body_text, plan_result):
    """ACT: build the segment(s) that Adapt will send to the model.

    Pure Python -- chunking, truncation and segment selection, no LLM call.
    """
    if plan_result["strategy"] == "direct":
        segments = [body_text.strip()] if body_text.strip() else []
        truncated = False
    else:
        all_chunks = embeddings.chunk_text(body_text, chunk_size=DEFAULT_MAP_REDUCE_CHUNK_SIZE)
        cap = plan_result["max_chunks"]
        segments = all_chunks[:cap]
        truncated = len(all_chunks) > cap

    return {
        "phase": "act",
        "description": "Build the text segment(s) to send to the model for summarization.",
        "strategy": plan_result["strategy"],
        "segments": segments,
        "segment_count": len(segments),
        "truncated": truncated,
    }


def observe(act_result):
    """OBSERVE: drop empty segments and decide whether a reduce pass is
    needed (more than one segment survived Act).
    """
    segments = [s for s in act_result["segments"] if s and s.strip()]
    needs_reduce = act_result["strategy"] == "map_reduce" and len(segments) > 1

    return {
        "phase": "observe",
        "description": (
            "Confirm which segments actually need summarizing, and whether "
            "a reduce pass is needed to combine more than one."
        ),
        "strategy": act_result["strategy"],
        "segments": segments,
        "needs_reduce": needs_reduce,
        "truncated": act_result["truncated"],
    }


def adapt(observe_result, generate_fn=None):
    """ADAPT: call the model to produce the final summary + key points.

    Direct strategy: one call on the whole document.
    Map-reduce strategy: one call per segment (map), then one call combining
    the per-segment summaries (reduce). Every model call in the loop happens
    here, in Adapt, regardless of how many there are.
    """
    generate = generate_fn if generate_fn is not None else llm.generate
    segments = observe_result["segments"]

    if not segments:
        return {
            "phase": "adapt",
            "description": "Produce the final summary and key points.",
            "llm_called": False,
            "llm_call_count": 0,
            "model_name": None,
            "summary_text": "",
            "key_points": [],
            "prompt_sent": None,
        }

    prompts_sent = []

    if observe_result["strategy"] == "direct" or not observe_result["needs_reduce"]:
        # Direct strategy, or map-reduce that collapsed to one usable segment.
        response_text, model_name = generate(segments[0], system=FINAL_SYSTEM_PROMPT)
        prompts_sent.append(FINAL_SYSTEM_PROMPT + "\n\n" + segments[0])
        summary_text, key_points = parse_summary_response(response_text)
        call_count = 1
    else:
        # Map: condense each segment.
        mini_summaries = []
        model_name = None
        for segment in segments:
            mini_text, model_name = generate(segment, system=MAP_SYSTEM_PROMPT)
            prompts_sent.append(MAP_SYSTEM_PROMPT + "\n\n" + segment)
            mini_summaries.append(mini_text.strip())

        # Reduce: combine the condensed segments into one final summary.
        combined = "\n\n".join(
            f"Excerpt {i + 1} summary: {s}" for i, s in enumerate(mini_summaries)
        )
        response_text, model_name = generate(combined, system=FINAL_SYSTEM_PROMPT)
        prompts_sent.append(FINAL_SYSTEM_PROMPT + "\n\n" + combined)
        summary_text, key_points = parse_summary_response(response_text)
        call_count = len(segments) + 1

    return {
        "phase": "adapt",
        "description": "Produce the final summary and key points.",
        "llm_called": True,
        "llm_call_count": call_count,
        "model_name": model_name,
        "summary_text": summary_text,
        "key_points": key_points,
        "prompt_sent": "\n\n---\n\n".join(prompts_sent),
    }


def summarize_document(body_text, generate_fn=None):
    """Run the full Plan -> Act -> Observe -> Adapt loop and return all four
    phase results, the way joshua/backend/app.py exposes drift.py's phases.
    """
    plan_result = plan(body_text)
    act_result = act(body_text, plan_result)
    observe_result = observe(act_result)
    adapt_result = adapt(observe_result, generate_fn=generate_fn)
    return plan_result, act_result, observe_result, adapt_result
