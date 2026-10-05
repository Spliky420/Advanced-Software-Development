"""Plan -> Act -> Observe -> Adapt drift review.

The four phases of the agentic loop are the four public functions below, in
order. Plan, Act and Observe are pure Python and involve no LLM at all; only
Adapt talks to the model, and only ever about breaches Observe already found.

Between Observe and Adapt, gather_context fetches reference material when
Observe found breaches: glossary definitions through the shared MCP server's
glossary_lookup tool, and passages from the team's RAG server. Adapt puts that
material in the prompt for wording only, then checks the model's text: any
number that was not in the portfolio figures block rejects the summary in
favour of one built in Python, so every figure that reaches the client still
originates in allocation.py.

No Flask imports here, and nothing in this module rounds: rounding belongs at
the output layer, the same rule allocation.py follows.

Each phase emits one aligned INFO line tagged with the run's correlation id, so
a single review reads as four consecutive lines in the terminal. Handler
configuration is the application's job, not this module's -- see
app.create_app.
"""

import logging
import os
import re
import uuid

import llm
import mcp_client
import rag_client

logger = logging.getLogger(__name__)

DEFAULT_DRIFT_THRESHOLD_PERCENT = 5.0

GLOSSARY_TOOL = "glossary_lookup"

# Asset class -> the term Maxwell's glossary is seeded with. The glossary
# matches terms exactly, and on a miss Maxwell's backend has the LLM write a
# definition, so only classes with a seeded counterpart are looked up at all.
GLOSSARY_TERM_BY_ASSET_CLASS = {
    "Australian equities": "Equity",
    "International equities": "Equity",
    "ETFs": "ETF",
    "Commodities": "Commodity",
}

# A passage counts as relevant only if it mentions a breached asset class (or
# a general allocation concept). The RAG server always returns its top k, so
# without this a corpus about, say, tax deductions would be cited as grounding
# for a portfolio drift summary.
RELEVANCE_PATTERNS_BY_ASSET_CLASS = {
    "Australian equities": (r"\bequit", r"\bshares?\b", r"\bstocks?\b"),
    "International equities": (r"\bequit", r"\bshares?\b", r"\bstocks?\b"),
    "ETFs": (r"\bETFs?\b", r"exchange[- ]traded", r"\bindex funds?\b"),
    "REITs": (r"\bREITs?\b", r"\breal estate\b"),
    "Government bonds": (r"\bbonds?\b", r"\bfixed[- ]income\b"),
    "Corporate bonds": (r"\bbonds?\b", r"\bfixed[- ]income\b"),
    "Cash": (r"\bcash\b",),
    "Term deposits": (r"\bterm deposits?\b",),
    "Commodities": (r"\bcommodit", r"\bgold\b"),
    "Crypto": (r"\bcrypto", r"\bbitcoin\b"),
}
GENERAL_RELEVANCE_PATTERNS = (
    r"\brebalanc", r"\basset allocation\b", r"\btarget allocation\b",
    r"\bdiversif", r"\ballocation drift\b",
)

# Passages requested from the RAG server, and the most characters of any one
# reference item (passage or definition) that reaches the prompt.
RAG_TOP_K = 3
MAX_REFERENCE_CHARS = 600

# Matches 12, 12.5, 1,234.56 -- the figures the output check compares.
NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Phase names are padded to the width of the longest ("OBSERVE") so the four
# lines of a run align in a terminal.
PHASE_NAME_WIDTH = 7

FIGURES_HEADING = "PORTFOLIO FIGURES (use every figure verbatim):"
REFERENCE_HEADING = "REFERENCE MATERIAL (for wording only -- contains no portfolio figures):"
# Sent instead of a reference block when Context found nothing relevant, so the
# model states the figures rather than filling the gap with unsupported
# background of its own.
INSUFFICIENT_CONTEXT_NOTICE = (
    "REFERENCE MATERIAL: none available -- insufficient context. Describe only "
    "the portfolio figures above. Do not explain what any asset class is, and "
    "do not add background, definitions or reasons for the drift."
)

DRIFT_SYSTEM_PROMPT = (
    "You are a portfolio reporting assistant. The PORTFOLIO FIGURES block "
    "lists asset classes whose actual allocation has drifted away from its "
    "target allocation by at least a stated threshold. Each line states the "
    "asset class, its target percentage, its actual percentage, the size of "
    "the drift in percentage points, and whether it is overweight or "
    "underweight. Using only those figures, write a short plain-English "
    "paragraph naming which asset classes are overweight and which are "
    "underweight, and by how many percentage points. Describe only -- never "
    "recommend trades, never give advice, and never make predictions. Never "
    "perform arithmetic yourself, and never introduce, restate or recalculate "
    "any figure that is not given to you exactly as provided in PORTFOLIO "
    "FIGURES. All portfolio figures are supplied in that block and must be "
    "used verbatim. A REFERENCE MATERIAL block may follow: it is background "
    "text from other services, for wording only, such as explaining what an "
    "asset class is. It contains no portfolio figures. Never repeat any number "
    "from it, and never present anything in it as a figure about this "
    "portfolio."
)


def _run_id(*sources):
    """The correlation id carried by the first source that has one.

    Falls back to "-" so a caller passing a hand-built dict -- as several tests
    do -- logs an anonymous run instead of raising.
    """
    for source in sources:
        try:
            value = source.get("run_id")
        except AttributeError:
            continue
        if value:
            return value
    return "-"


def _log(level, phase, run_id, template, *args):
    """Emit one aligned agentic-loop line.

    Never raises. Logging is additive evidence that the loop ran; a phase must
    not fail because a handler, a formatter or a malformed argument did.
    """
    try:
        logger.log(
            level,
            "[agentic-loop %s] %-*s | " + template,
            run_id, PHASE_NAME_WIDTH, phase, *args,
        )
    except Exception:  # noqa: BLE001 -- see docstring
        pass


def _chars(value):
    """Length of a text field for the log line, or -1 if it has none.

    Keeps len() out of the argument list of a log call, so a stub or a model
    client that returned something unexpected cannot fail the phase.
    """
    try:
        return len(value)
    except TypeError:
        return -1


def _breached_summary(breaches):
    """"ETFs +9.30pp overweight; Cash -6.10pp underweight", or "none".

    Reads drift_magnitude and direction straight off the rows Observe already
    classified -- the sign comes from the direction, not from re-deriving it.
    """
    signs = {"overweight": "+", "underweight": "-"}
    try:
        parts = [
            f"{row.get('asset_class', '?')} "
            f"{signs.get(row.get('direction'), '')}"
            f"{row.get('drift_magnitude', 0.0):.2f}pp "
            f"{row.get('direction', '?')}"
            for row in breaches
        ]
    except Exception:  # noqa: BLE001 -- this string is evidence, not logic
        return "unavailable"
    return "; ".join(parts) if parts else "none"


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

    result = {
        "phase": "plan",
        # Plan opens the run, so it is where the correlation id is minted; the
        # other three phases carry this same id forward.
        "run_id": uuid.uuid4().hex[:8],
        "description": (
            "Read the allocation targets and set the drift threshold that "
            "decides which asset classes count as off-target."
        ),
        "threshold_percent": threshold,
        "asset_classes_to_examine": sorted(target_by_class),
        "target_percent_by_class": target_by_class,
    }

    _log(
        logging.INFO, "PLAN", _run_id(result),
        "threshold=%.2fpp | classes_to_examine=%d",
        threshold, len(result["asset_classes_to_examine"]),
    )
    return result


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

    result = {
        "phase": "act",
        "run_id": _run_id(plan_result),
        "description": (
            "Compute the current allocation and the drift, in percentage "
            "points, between actual and target for each asset class."
        ),
        "total_market_value": portfolio["total_market_value"],
        "drift_by_class": drift_by_class,
    }

    run_id = _run_id(result, plan_result)
    _log(
        logging.INFO, "ACT", run_id,
        "total_market_value=%.2f | classes_evaluated=%d",
        portfolio["total_market_value"], len(drift_by_class),
    )
    # The per-class rows are far too long for a terminal screenshot, so they
    # sit at DEBUG for when a specific number needs tracing.
    _log(logging.DEBUG, "ACT", run_id, "drift_by_class=%r", drift_by_class)
    return result


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

    result = {
        "phase": "observe",
        # Adapt is handed only this dict, so the id has to travel in it.
        "run_id": _run_id(act_result, plan_result),
        "description": (
            "Identify which asset classes breach the drift threshold and "
            "classify each as overweight or underweight."
        ),
        "threshold_percent": threshold,
        "breach_count": len(breaches),
        "breaches": breaches,
        "within_threshold": within_threshold,
    }

    _log(
        logging.INFO, "OBSERVE", _run_id(result, act_result, plan_result),
        "breaches=%d | within_threshold=%d | breached=%s",
        len(breaches), len(within_threshold), _breached_summary(breaches),
    )
    return result


def _glossary_entry(term, asset_classes, result):
    definition = result["data"].get("definition") if isinstance(result["data"], dict) else None
    if result["ok"] and isinstance(definition, str) and definition.strip():
        status, error = "found", None
    else:
        status = "unavailable"
        definition = None
        error = result["error"] or "glossary response had no definition"
    return {
        "term": term,
        "asset_classes": asset_classes,
        "status": status,
        "definition": definition,
        "error": error,
        "source": f"mcp:{GLOSSARY_TOOL}",
    }


def build_retrieval_query(observe_result):
    """"Portfolio allocation drift: ETFs overweight; Cash underweight."

    Names and directions only -- no figures, so the query asks about the
    concepts rather than matching on numbers.
    """
    parts = [
        f"{breach.get('asset_class', '?')} {breach.get('direction', '?')}"
        for breach in observe_result["breaches"]
    ]
    return "Portfolio allocation drift: " + "; ".join(parts) + "."


def _lookup_glossary(observe_result, call_tools_fn):
    """(mcp_called, reason, glossary entries) for the breached classes."""
    # Term -> the breached classes it explains, in breach order, deduplicated
    # so "Equity" is fetched once for both equity classes.
    classes_by_term = {}
    for breach in observe_result["breaches"]:
        term = GLOSSARY_TERM_BY_ASSET_CLASS.get(breach.get("asset_class"))
        if term is not None:
            classes_by_term.setdefault(term, []).append(breach["asset_class"])

    if not classes_by_term:
        return False, "no breached asset class has a glossary term", []

    call_tools = call_tools_fn if call_tools_fn is not None else mcp_client.call_tools
    terms = list(classes_by_term)
    try:
        responses = call_tools([(GLOSSARY_TOOL, {"term": term}) for term in terms])
    except Exception as exc:  # noqa: BLE001 -- context is optional to the loop
        responses = [
            {"tool": GLOSSARY_TOOL, "ok": False, "data": None, "error": f"MCP call failed: {exc}"}
            for _ in terms
        ]

    return True, None, [
        _glossary_entry(term, classes_by_term[term], response)
        for term, response in zip(terms, responses)
    ]


def _relevance_patterns(observe_result):
    """Word patterns a passage must contain to be relevant to this review."""
    patterns = list(GENERAL_RELEVANCE_PATTERNS)
    for breach in observe_result["breaches"]:
        patterns.extend(RELEVANCE_PATTERNS_BY_ASSET_CLASS.get(breach.get("asset_class"), ()))
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


def is_relevant(text, patterns):
    return any(pattern.search(text) for pattern in patterns)


def _retrieve_passages(observe_result, retrieve_fn):
    """The retrieval section: query, status, relevant chunks, dropped chunks.

    status is one of:
      found                -- at least one relevant passage
      insufficient_context -- the server answered, but nothing it returned
                              is about the breached asset classes
      unavailable          -- the server could not be used (failure says
                              unreachable, timeout or error)
      disabled             -- RAG_SERVER_URL is empty

    Relevance is a word match against the breached asset classes, never the
    distance: the server always returns its top k however poor the match, and
    the distance's meaning is the server's business. Order is preserved.
    """
    retrieve = retrieve_fn if retrieve_fn is not None else rag_client.retrieve
    query = build_retrieval_query(observe_result)
    try:
        response = retrieve(query, RAG_TOP_K)
    except Exception as exc:  # noqa: BLE001 -- context is optional to the loop
        response = {"ok": False, "status": "error", "data": None, "error": f"RAG call failed: {exc}"}

    section = {
        "query": query,
        "status": None,
        "failure": None,
        "error": response.get("error"),
        "chunks": [],
        "dropped": [],
    }

    if not response["ok"]:
        failure = response.get("status") or "error"
        if failure == "disabled":
            section["status"] = "disabled"
        else:
            section["status"], section["failure"] = "unavailable", failure
        return section

    patterns = _relevance_patterns(observe_result)
    for chunk in response["data"]["chunks"]:
        if is_relevant(chunk["text"], patterns):
            section["chunks"].append(chunk)
        else:
            section["dropped"].append({
                key: chunk.get(key) for key in ("rank", "chunk_id", "source_id", "distance")
            })

    section["status"] = "found" if section["chunks"] else "insufficient_context"
    return section


def _insufficient_reason(glossary, retrieval):
    """Why there is no reference material, naming the RAG cause precisely."""
    status = retrieval["status"]
    if status == "insufficient_context":
        if retrieval["dropped"]:
            rag = (
                f"the RAG server returned {len(retrieval['dropped'])} passage(s), "
                f"none about the breached asset classes"
            )
        else:
            rag = "the RAG server returned no passages"
    elif status == "disabled":
        rag = "RAG is disabled"
    elif retrieval["failure"] == "timeout":
        rag = "the RAG server did not respond in time"
    elif retrieval["failure"] == "unreachable":
        rag = "the RAG server is unreachable"
    else:
        rag = "the RAG server returned an error"

    glossary_note = (
        "no glossary definition was available"
        if glossary else "no breached asset class has a glossary term"
    )
    return f"No relevant reference material: {rag}, and {glossary_note}."


def gather_context(observe_result, call_tools_fn=None, retrieve_fn=None):
    """CONTEXT: fetch reference material about the breached asset classes.

    Runs only when Observe found a breach -- the same decision that gates the
    LLM in Adapt. Two sources, each optional: glossary definitions from the
    shared MCP server, and passages from the team's RAG server. Both are
    reference material for Adapt's wording; neither supplies a figure.

    Never raises. With either server down, its part is reported as
    "unavailable" and the loop carries on to Adapt.
    """
    run_id = _run_id(observe_result)
    result = {
        "phase": "context",
        "run_id": run_id,
        "description": (
            "Fetch reference material about the breached asset classes: "
            "glossary definitions through the shared MCP server and passages "
            "from the RAG server."
        ),
        "mcp_called": False,
        "rag_called": False,
        "reason": None,
        "glossary": [],
        "retrieval": None,
        # True when breaches exist but neither source produced anything
        # relevant; Adapt then tells the model it has no reference material.
        "insufficient_context": False,
        "insufficient_reason": None,
    }

    if observe_result["breach_count"] == 0:
        result["reason"] = "no breaches, context lookup skipped"
        _log(logging.INFO, "CONTEXT", run_id, "mcp_called=False | rag_called=False | reason=%s", result["reason"])
        return result

    result["mcp_called"], result["reason"], result["glossary"] = _lookup_glossary(
        observe_result, call_tools_fn
    )
    result["rag_called"] = True
    result["retrieval"] = _retrieve_passages(observe_result, retrieve_fn)

    found = sum(1 for entry in result["glossary"] if entry["status"] == "found")
    if found == 0 and not result["retrieval"]["chunks"]:
        result["insufficient_context"] = True
        result["insufficient_reason"] = _insufficient_reason(result["glossary"], result["retrieval"])

    _log(
        logging.INFO, "CONTEXT", run_id,
        "mcp_called=%s | glossary_found=%d/%d | rag_status=%s | passages=%d | dropped=%d | "
        "insufficient_context=%s",
        result["mcp_called"], found, len(result["glossary"]),
        result["retrieval"]["status"], len(result["retrieval"]["chunks"]),
        len(result["retrieval"]["dropped"]), result["insufficient_context"],
    )
    return result


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


def _clip(text):
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_REFERENCE_CHARS else text[:MAX_REFERENCE_CHARS].rstrip() + "..."


def reference_items(context_result):
    """(citation, text) pairs for the reference block, in citation order.

    RAG passages first, in the order the server returned them; then the
    glossary definitions that were found.
    """
    if not context_result:
        return []

    items = []
    retrieval = context_result.get("retrieval") or {}
    for chunk in retrieval.get("chunks") or []:
        items.append((
            {
                "kind": "rag",
                "rank": chunk.get("rank"),
                "chunk_id": chunk.get("chunk_id"),
                "source_id": chunk.get("source_id"),
                "distance": chunk.get("distance"),
            },
            chunk["text"],
        ))
    for entry in context_result.get("glossary") or []:
        if entry.get("status") == "found":
            items.append((
                {"kind": "glossary", "term": entry["term"], "source": entry["source"]},
                entry["definition"],
            ))
    return items


def build_reference_block(items):
    """The REFERENCE MATERIAL block, or None when there is nothing to add."""
    if not items:
        return None
    lines = [REFERENCE_HEADING]
    for citation, text in items:
        if citation["kind"] == "rag":
            label = f"passage {citation.get('source_id') or '?'}#{citation.get('chunk_id') or '?'}"
        else:
            label = f"glossary: {citation['term']}"
        lines.append(f"- [{label}] {_clip(text)}")
    return "\n".join(lines)


def _numbers(text):
    """Every number in text, as floats rounded to 2dp, sign ignored."""
    found = set()
    for match in NUMBER_PATTERN.findall(text):
        try:
            found.add(round(float(match.rstrip(",").replace(",", "")), 2))
        except ValueError:
            continue
    return found


def unsupplied_figures(response_text, figures):
    """Numbers in the model's text that the figures block did not contain."""
    if not isinstance(response_text, str):
        return []
    return sorted(_numbers(response_text) - _numbers(figures))


DIRECTION_PATTERN = re.compile(r"\b(overweight|underweight)", re.IGNORECASE)

# Lines, sentences and semicolon-separated clauses. Commas are deliberately
# not boundaries: "ETFs (target 15.00%, actual 24.30%, 9.30 points
# overweight)" must stay one unit. A decimal point is never followed by
# whitespace, so "9.30" is not split.
SEGMENT_SPLIT = re.compile(r"\n+|(?<=[.!?;])\s+")

# "overweight in ETFs" / "underweight in the REITs asset class".
_BINDS_FORWARD = re.compile(r"\s+(?:in|on)\s+(?:the\s+)?$", re.IGNORECASE)


def _segment_tokens(segment, class_pattern):
    """Class mentions, numbers and direction words in reading order."""
    tokens = []
    for match in class_pattern.finditer(segment):
        tokens.append((match.start(), match.end(), "class", match.group(0)))
    for match in NUMBER_PATTERN.finditer(segment):
        tokens.append((match.start(), match.end(), "number", match.group(0)))
    for match in DIRECTION_PATTERN.finditer(segment):
        tokens.append((match.start(), match.end(), "direction", match.group(1).lower()))
    tokens.sort()
    return tokens


def misattributed_figures(response_text, observe_result):
    """Figures or directions the model attached to the wrong asset class.

    unsupplied_figures only asks whether a number was supplied at all, so a
    model that swaps two classes' drifts passes it. This checks the binding,
    by position within each line or sentence:

    - A number belongs to the class named most recently before it, and must
      be that class's target, actual or drift (or the threshold). Numbers
      after a run of several classes ("ETFs and Crypto ... 9.30 and 8.26")
      cannot be attributed and are not judged.
    - "overweight in X" binds the direction to X. Otherwise a direction word
      binds to the class (or run of classes) named before it; with none
      before it, to every class named after it in the same segment.
    - A segment naming no class but one direction ("Overweight classes:")
      is a heading: list lines below it that state no direction inherit it.

    Every bound direction must be that class's actual direction.
    """
    if not isinstance(response_text, str) or not observe_result["breaches"]:
        return []

    threshold = round(observe_result["threshold_percent"], 2)
    by_class = {}
    for breach in observe_result["breaches"]:
        figures = {
            round(breach["target_percent"], 2),
            round(breach["actual_percent"], 2),
            round(breach["drift_magnitude"], 2),
            threshold,
        }
        by_class[breach["asset_class"].lower()] = (breach["asset_class"], figures, breach["direction"])

    names = sorted(by_class, key=len, reverse=True)
    class_pattern = re.compile("|".join(re.escape(name) for name in names), re.IGNORECASE)

    problems = []

    def check_direction(key, stated):
        name, _, actual = by_class[key]
        if stated != actual:
            problems.append({"asset_class": name, "figure": None, "direction": stated})

    def check_number(key, text):
        name, figures, _ = by_class[key]
        try:
            value = round(float(text.rstrip(",").replace(",", "")), 2)
        except ValueError:
            return
        if value not in figures:
            problems.append({"asset_class": name, "figure": value, "direction": None})

    heading_direction = None
    for segment in SEGMENT_SPLIT.split(response_text):
        tokens = _segment_tokens(segment, class_pattern)
        kinds = {kind for _, _, kind, _ in tokens}
        if "class" not in kinds:
            directions = {value for _, _, kind, value in tokens if kind == "direction"}
            if len(directions) == 1:
                heading_direction = directions.pop()
            continue

        group = []              # the most recent run of consecutive classes
        group_open = False      # still accepting classes into that run
        pending = None          # direction stated before any class
        bound = set()           # classes given a direction in this segment
        for index, (start, end, kind, value) in enumerate(tokens):
            if kind == "class":
                key = value.lower()
                if not group_open:
                    group = []
                group.append(key)
                group_open = True
                if pending is not None:
                    check_direction(key, pending)
                    bound.add(key)
            elif kind == "number":
                group_open = False
                if len(group) == 1:
                    check_number(group[0], value)
            else:  # direction
                group_open = False
                following = tokens[index + 1] if index + 1 < len(tokens) else None
                if (
                    following is not None
                    and following[2] == "class"
                    and _BINDS_FORWARD.match(segment[end:following[0]])
                ):
                    key = following[3].lower()
                    check_direction(key, value)
                    bound.add(key)
                    # The class is bound already; don't let it re-bind as
                    # "pending" or as part of an older run.
                    group, group_open = [], False
                elif pending is not None:
                    # Direction-first phrasing ("overweight are ETFs ...,
                    # while underweight are REITs"): start a new run.
                    pending = value
                elif group:
                    for key in group:
                        check_direction(key, value)
                        bound.add(key)
                else:
                    pending = value

        if heading_direction is not None:
            for _, _, kind, value in tokens:
                if kind == "class" and value.lower() not in bound:
                    check_direction(value.lower(), heading_direction)
                    bound.add(value.lower())

    return problems


def build_fallback_summary(observe_result):
    """A summary built entirely in Python from the observed breaches.

    Used when the model's text fails the figures check. Every number is
    formatted exactly as in the figures block the model was given.
    """
    parts = [
        f"{breach['asset_class']} is {breach['drift_magnitude']:.2f} percentage points "
        f"{breach['direction']} (target {breach['target_percent']:.2f}%, "
        f"actual {breach['actual_percent']:.2f}%)"
        for breach in observe_result["breaches"]
    ]
    return (
        f"The following asset classes have drifted by at least "
        f"{observe_result['threshold_percent']:.2f} percentage points from target: "
        + "; ".join(parts) + "."
    )


def adapt(observe_result, generate_fn=None, context_result=None):
    """ADAPT: have the model describe the observed breaches in plain English.

    Only the breaches are sent as figures; context_result, when given, adds a
    reference block for wording. The model's text is then checked: a number
    not present in the figures block means it quoted the reference material
    or invented a figure, so the text is replaced by build_fallback_summary.
    When nothing breached, this says so directly and never calls the LLM.
    """
    run_id = _run_id(observe_result)
    description = (
        "Report the observed breaches in plain English, or state directly "
        "that there were none."
    )

    if observe_result["breach_count"] == 0:
        # The skip is the decision that makes this loop agentic rather than a
        # fixed pipeline, so it is logged as explicitly as a call would be.
        _log(
            logging.INFO, "ADAPT", run_id,
            "llm_called=False | reason=no breaches, LLM skipped",
        )
        return {
            "phase": "adapt",
            "run_id": run_id,
            "description": description,
            "llm_called": False,
            "summary": (
                f"No asset class has drifted by "
                f"{observe_result['threshold_percent']:.2f} percentage points or more "
                f"from its target, so the portfolio is within the configured "
                f"drift threshold."
            ),
            "summary_source": "no_breaches",
            "context_status": None,
            "unsupplied_figures": [],
            "misattributed": [],
            "citations": [],
            "model_response": None,
            "prompt_sent": None,
            "model_name": None,
        }

    generate = generate_fn if generate_fn is not None else llm.generate
    figures = build_drift_prompt(observe_result)
    items = reference_items(context_result)
    reference = build_reference_block(items)

    # None when no Context phase ran (a direct call), so the prompt is the
    # figures alone and nothing is claimed either way.
    if context_result is None:
        context_status = None
    elif reference:
        context_status = "grounded"
    else:
        context_status = "insufficient_context"

    user_prompt = FIGURES_HEADING + "\n" + figures
    if reference:
        user_prompt += "\n\n" + reference
    elif context_status == "insufficient_context":
        user_prompt += "\n\n" + INSUFFICIENT_CONTEXT_NOTICE

    response_text, model_name = generate(user_prompt, system=DRIFT_SYSTEM_PROMPT)
    prompt_sent = DRIFT_SYSTEM_PROMPT + "\n\n" + user_prompt

    rejected = unsupplied_figures(response_text, figures)
    misattributed = misattributed_figures(response_text, observe_result)
    verified = isinstance(response_text, str) and not rejected and not misattributed
    if verified:
        summary, summary_source = response_text, "model"
        # Citations back the model's text, so a fallback cites nothing.
        citations = [citation for citation, _ in items]
    else:
        summary, summary_source = build_fallback_summary(observe_result), "fallback"
        citations = []

    _log(
        logging.INFO, "ADAPT", run_id,
        "llm_called=True | model=%s | prompt_chars=%d | response_chars=%d | "
        "reference_items=%d | context_status=%s | summary_source=%s | unsupplied_figures=%d | "
        "misattributed=%d",
        model_name, _chars(prompt_sent), _chars(response_text),
        len(items), context_status, summary_source, len(rejected), len(misattributed),
    )
    # Full text at DEBUG only: prompt_sent runs to hundreds of characters and
    # would bury the other phases in a terminal.
    _log(logging.DEBUG, "ADAPT", run_id, "prompt_sent=%s", prompt_sent)
    _log(logging.DEBUG, "ADAPT", run_id, "response_text=%s", response_text)

    return {
        "phase": "adapt",
        "run_id": run_id,
        "description": description,
        "llm_called": True,
        "summary": summary,
        "summary_source": summary_source,
        "unsupplied_figures": rejected,
        "misattributed": misattributed,
        "context_status": context_status,
        "citations": citations,
        "model_response": response_text,
        "prompt_sent": prompt_sent,
        "model_name": model_name,
    }
