"""Request validation.

Two rules throughout:

  * collect every problem, then raise once. A form gets all of its errors in
    one response instead of one per round trip.
  * validate before the database sees anything. The schema's CHECK
    constraints are the backstop, not the error message -- a client should
    get "priority must be one of high, medium, low", not a raw
    IntegrityError.
"""

from __future__ import annotations

from typing import Any

from ..errors import ValidationFailed
from . import dates

GOAL_PRIORITIES = ("high", "medium", "low")
GOAL_STATUSES = ("active", "paused", "achieved", "abandoned")
STEP_STATUSES = ("pending", "complete", "skipped")
STEP_SOURCES = ("ai", "user")

MAX_NAME_LENGTH = 120
MAX_NOTES_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 300

# A ceiling that stops a typo like 1e30 reaching the arithmetic, while sitting
# far above any plausible savings goal.
MAX_AMOUNT = 100_000_000.0


# ---------------------------------------------------------------------------
# Field-level helpers. Each appends to `errors` and returns the cleaned value,
# or None if the field was absent or unusable.
# ---------------------------------------------------------------------------


def require_object(payload: Any) -> dict:
    """The body must be a JSON object, not a list, string or null."""
    if not isinstance(payload, dict):
        raise ValidationFailed(["request body must be a JSON object"])
    return payload


def clean_string(
    payload: dict,
    field: str,
    errors: list[str],
    *,
    required: bool,
    max_length: int,
    allow_empty: bool = False,
) -> str | None:
    if field not in payload or payload[field] is None:
        if required:
            errors.append(f"{field} is required")
        return None
    value = payload[field]
    if not isinstance(value, str):
        errors.append(f"{field} must be a string")
        return None
    value = value.strip()
    if not value and not allow_empty:
        errors.append(f"{field} must not be empty")
        return None
    if len(value) > max_length:
        errors.append(f"{field} must be {max_length} characters or fewer")
        return None
    return value


def clean_amount(
    payload: dict,
    field: str,
    errors: list[str],
    *,
    required: bool,
    allow_zero: bool = False,
) -> float | None:
    """A money amount, rounded to cents.

    Positive by default. `allow_zero` matches the schema for the two columns
    that permit 0: a step can be an action with no money attached ("compare
    prices"), and a monthly budget of zero is a legitimate thing to record.

    bool is rejected explicitly: in Python `True` is an int, and `True`
    reaching the database as an amount of 1.00 would be a silent bug.
    """
    if field not in payload or payload[field] is None:
        if required:
            errors.append(f"{field} is required")
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field} must be a number")
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):  # NaN / infinity
        errors.append(f"{field} must be a finite number")
        return None
    if allow_zero:
        if value < 0:
            errors.append(f"{field} must not be negative")
            return None
    elif value <= 0:
        errors.append(f"{field} must be greater than 0")
        return None
    if value > MAX_AMOUNT:
        errors.append(f"{field} must be {MAX_AMOUNT:,.0f} or less")
        return None
    return round(value, 2)


def clean_date(payload: dict, field: str, errors: list[str], *, required: bool) -> str | None:
    if field not in payload or payload[field] is None:
        if required:
            errors.append(f"{field} is required")
        return None
    value = payload[field]
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO-8601 date string (YYYY-MM-DD)")
        return None
    try:
        dates.parse_date(value.strip())
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 date (YYYY-MM-DD), got {value!r}")
        return None
    return value.strip()


def clean_choice(
    payload: dict, field: str, errors: list[str], choices: tuple[str, ...], *, required: bool
) -> str | None:
    if field not in payload or payload[field] is None:
        if required:
            errors.append(f"{field} is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in choices:
        errors.append(f"{field} must be one of: {', '.join(choices)}")
        return None
    return value


def clean_user_id(value: Any, errors: list[str], *, field: str = "user_id") -> int | None:
    """A positive integer user id, accepted as an int or a numeric string."""
    if value is None:
        return None
    if isinstance(value, bool):
        errors.append(f"{field} must be a positive integer")
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            errors.append(f"{field} must be a positive integer")
            return None
        value = int(value)
    if not isinstance(value, int) or value < 1:
        errors.append(f"{field} must be a positive integer")
        return None
    return value


# ---------------------------------------------------------------------------
# Goal payloads
# ---------------------------------------------------------------------------


def _check_target_date_not_past(target_date: str | None, status: str, errors: list[str]) -> None:
    """An active goal cannot have a target date that has already passed.

    This is a real constraint rather than tidiness: the planner divides the
    remaining amount across the months left, and a goal with no months left
    cannot be planned at all. Goals that are paused, achieved or abandoned
    are exempt -- an achieved goal's target date is history, and refusing to
    let it be edited would be perverse.
    """
    if target_date is None or status != "active":
        return
    if dates.parse_date(target_date) < dates.today():
        errors.append(
            f"target_date {target_date} is in the past; an active goal must target a future date"
        )


def validate_goal_create(payload: Any) -> dict:
    """Validate a POST /api/goals body. Returns the cleaned field values."""
    payload = require_object(payload)
    errors: list[str] = []

    clean = {
        "name": clean_string(payload, "name", errors, required=True, max_length=MAX_NAME_LENGTH),
        "target_amount": clean_amount(payload, "target_amount", errors, required=True),
        "target_date": clean_date(payload, "target_date", errors, required=True),
        "priority": clean_choice(payload, "priority", errors, GOAL_PRIORITIES, required=False) or "medium",
        "status": clean_choice(payload, "status", errors, GOAL_STATUSES, required=False) or "active",
    }

    user_id = clean_user_id(payload.get("user_id"), errors)
    if user_id is not None:
        clean["user_id"] = user_id

    _check_target_date_not_past(clean["target_date"], clean["status"], errors)

    if errors:
        raise ValidationFailed(errors)
    return clean


def validate_goal_update(payload: Any, current: dict) -> dict:
    """Validate a PUT /api/goals/<id> body against the goal as it stands.

    PUT merges: any field left out keeps its current value. There is no PATCH
    in this release, and the edit form sends the whole goal anyway, so a
    merge is the forgiving reading and costs nothing.
    """
    payload = require_object(payload)
    errors: list[str] = []

    if "user_id" in payload:
        # Ownership is not transferable through the edit form. Silently
        # ignoring it would be worse -- the client would think it worked.
        errors.append("user_id cannot be changed")

    clean: dict = {}
    updatable = {
        "name": lambda: clean_string(payload, "name", errors, required=False, max_length=MAX_NAME_LENGTH),
        "target_amount": lambda: clean_amount(payload, "target_amount", errors, required=False),
        "target_date": lambda: clean_date(payload, "target_date", errors, required=False),
        "priority": lambda: clean_choice(payload, "priority", errors, GOAL_PRIORITIES, required=False),
        "status": lambda: clean_choice(payload, "status", errors, GOAL_STATUSES, required=False),
    }
    for field, validator in updatable.items():
        if field in payload:
            value = validator()
            if value is not None:
                clean[field] = value

    if not clean and not errors:
        errors.append(
            "no updatable fields supplied; send at least one of: " + ", ".join(updatable)
        )

    # The past-date rule is checked against the goal as it will be after the
    # merge, not as it is now -- pausing a goal and back-dating it in the same
    # request is legitimate.
    _check_target_date_not_past(
        clean.get("target_date", current["target_date"]),
        clean.get("status", current["status"]),
        errors,
    )

    if errors:
        raise ValidationFailed(errors)
    return clean


# ---------------------------------------------------------------------------
# Query string
# ---------------------------------------------------------------------------


def validate_goal_filters(args: Any) -> dict:
    """Validate the ?status= / ?priority= / ?user_id= filters on GET /api/goals.

    `user_id=all` is a deliberate escape hatch that lifts the single-user
    scoping, so the seeded data for all three users can be shown at once.
    """
    errors: list[str] = []
    filters: dict = {}

    status = args.get("status")
    if status is not None:
        if status not in GOAL_STATUSES:
            errors.append(f"status must be one of: {', '.join(GOAL_STATUSES)}")
        else:
            filters["status"] = status

    priority = args.get("priority")
    if priority is not None:
        if priority not in GOAL_PRIORITIES:
            errors.append(f"priority must be one of: {', '.join(GOAL_PRIORITIES)}")
        else:
            filters["priority"] = priority

    raw_user = args.get("user_id")
    if raw_user is not None:
        if raw_user.strip().lower() == "all":
            filters["user_id"] = None  # explicit "every user"
        else:
            user_id = clean_user_id(raw_user, errors)
            if user_id is not None:
                filters["user_id"] = user_id

    if errors:
        raise ValidationFailed(errors)
    return filters


def validate_user_id_arg(args: Any, default_user_id: int) -> int:
    """Read ?user_id= from a query string, falling back to the default user.

    Used by the budget endpoints, which are always about exactly one user --
    there is no "all users" budget to summarise.
    """
    errors: list[str] = []
    raw = args.get("user_id")
    if raw is None:
        return default_user_id
    user_id = clean_user_id(raw, errors)
    if errors:
        raise ValidationFailed(errors)
    assert user_id is not None
    return user_id


# ---------------------------------------------------------------------------
# Step payloads
# ---------------------------------------------------------------------------


def validate_step_update(payload: Any) -> dict:
    """Validate a PUT /api/goals/<id>/steps/<step_id> body.

    A merge like the goal update: send only what changes. Editing the
    substance of a step (its description, amount or due date) is a different
    act from ticking it off, and the service treats them differently -- see
    services/steps.py.
    """
    payload = require_object(payload)
    errors: list[str] = []

    for immutable in ("step_id", "goal_id", "step_order", "source"):
        if immutable in payload:
            errors.append(f"{immutable} cannot be changed")

    clean: dict = {}
    if "description" in payload:
        value = clean_string(payload, "description", errors, required=False, max_length=MAX_DESCRIPTION_LENGTH)
        if value is not None:
            clean["description"] = value
    if "step_amount" in payload:
        value = clean_amount(payload, "step_amount", errors, required=False, allow_zero=True)
        if value is not None:
            clean["step_amount"] = value
    if "due_date" in payload:
        value = clean_date(payload, "due_date", errors, required=False)
        if value is not None:
            clean["due_date"] = value
    if "status" in payload:
        value = clean_choice(payload, "status", errors, STEP_STATUSES, required=False)
        if value is not None:
            clean["status"] = value

    if not clean and not errors:
        errors.append(
            "no updatable fields supplied; send at least one of: description, step_amount, due_date, status"
        )

    if errors:
        raise ValidationFailed(errors)
    return clean


# ---------------------------------------------------------------------------
# Contribution payloads
# ---------------------------------------------------------------------------


def validate_contribution_create(payload: Any) -> dict:
    """Validate a POST /api/goals/<id>/contributions body.

    contribution_date defaults to today. A future date is rejected: this
    table records money that has actually moved, which is what makes it the
    ACT phase of the loop rather than another kind of plan.
    """
    payload = require_object(payload)
    errors: list[str] = []

    clean = {
        "amount": clean_amount(payload, "amount", errors, required=True),
        "contribution_date": clean_date(payload, "contribution_date", errors, required=False),
        "notes": clean_string(
            payload, "notes", errors, required=False, max_length=MAX_NOTES_LENGTH, allow_empty=True
        ),
    }

    if clean["contribution_date"] is None:
        clean["contribution_date"] = dates.to_iso(dates.today())
    elif dates.parse_date(clean["contribution_date"]) > dates.today():
        errors.append(
            f"contribution_date {clean['contribution_date']} is in the future; "
            "record a contribution once the money has moved"
        )

    if not clean["notes"]:
        clean["notes"] = None

    if errors:
        raise ValidationFailed(errors)
    return clean


# ---------------------------------------------------------------------------
# Budget payloads
# ---------------------------------------------------------------------------

CURRENCY_LENGTH = 3


def validate_budget_settings(payload: Any, default_user_id: int) -> dict:
    """Validate a PUT /api/budget/settings body.

    monthly_budget is required -- this endpoint's whole purpose is to set it.
    currency is optional and defaults to AUD, matching the schema.
    """
    payload = require_object(payload)
    errors: list[str] = []

    clean = {
        "monthly_budget": clean_amount(payload, "monthly_budget", errors, required=True, allow_zero=True),
        "user_id": clean_user_id(payload.get("user_id"), errors) or default_user_id,
    }

    currency = clean_string(payload, "currency", errors, required=False, max_length=CURRENCY_LENGTH)
    if currency is None:
        clean["currency"] = "AUD"
    elif len(currency) != CURRENCY_LENGTH or not currency.isalpha():
        errors.append("currency must be a three-letter code, for example AUD")
    else:
        clean["currency"] = currency.upper()

    if errors:
        raise ValidationFailed(errors)
    return clean


# ---------------------------------------------------------------------------
# Release 1 payloads -- MCP and RAG
# ---------------------------------------------------------------------------

# A tool name long enough for anything the shared server advertises, short
# enough that a junk body cannot be stored as one.
MAX_TOOL_NAME_LENGTH = 80


def validate_mcp_call(payload: Any) -> dict:
    """Validate a POST /api/mcp/call body.

    Deliberately NOT checked against a list of the six tool names that exist
    today. This endpoint's purpose is to call whatever the shared server
    advertises, and a hardcoded allow-list here would turn one teammate adding
    a tool into a 400 from my backend. The server is the authority on which
    tools exist; an unknown name comes back as an MCP error, which is the
    honest answer.

    `arguments` must be an object because that is what the protocol sends --
    MCP arguments are named, never positional.

    `goal_id` is optional and only decides which goal the audit row is
    attributed to. It is never used to scope data.
    """
    payload = require_object(payload)
    errors: list[str] = []

    clean = {
        "tool": clean_string(payload, "tool", errors, required=True, max_length=MAX_TOOL_NAME_LENGTH),
        "goal_id": None,
    }

    arguments = payload.get("arguments")
    if arguments is None:
        clean["arguments"] = {}
    elif isinstance(arguments, dict):
        clean["arguments"] = arguments
    else:
        errors.append("arguments must be a JSON object")

    if payload.get("goal_id") is not None:
        goal_id = payload["goal_id"]
        if isinstance(goal_id, bool) or not isinstance(goal_id, int):
            errors.append("goal_id must be an integer")
        elif goal_id <= 0:
            errors.append("goal_id must be a positive integer")
        else:
            clean["goal_id"] = goal_id

    if errors:
        raise ValidationFailed(errors)
    return clean


# Query-string booleans. Accepted spellings are the same ones config.py takes
# for environment variables, so "use_mcp=false" means the same thing on the
# URL as MCP_ENABLED=false does in the environment.
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")


def flag_value(field: str, *sources: Any, default: bool) -> bool:
    """Read a boolean flag from the first source that mentions it.

    Two sources, because the same switch is wanted in two places: a JSON body
    for `POST /api/goals/<id>/plan {"use_mcp": false}`, and a query string for
    `GET /api/goals/<id>/mcp-context?use_mcp=false` and for the curl sequence
    the report uses as evidence. A real JSON boolean is taken as it is; a
    query-string value is read by the same spellings config.py accepts for
    environment variables, so `use_mcp=false` on a URL means what
    `MCP_ENABLED=false` means in the environment.

    An unrecognised value is a 400 rather than a silent default. `use_mcp=no`
    and `use_mcp=flase` must not both mean "on": the first asks for the
    fallback path and the second is a typo the caller needs to see, because
    quietly ignoring it would make a demonstration of the fallback path show
    the MCP path instead.
    """
    raw: Any = None
    for source in sources:
        if source is not None and hasattr(source, "get") and field in source:
            raw = source.get(field)
            break
    else:
        return default

    if isinstance(raw, bool):
        return raw
    if raw is None or not str(raw).strip():
        return default

    value = str(raw).strip().lower()
    if value in TRUE_WORDS:
        return True
    if value in FALSE_WORDS:
        return False
    raise ValidationFailed([f"{field} must be one of {', '.join(TRUE_WORDS + FALSE_WORDS)}"])


def flag_arg(args: Any, field: str, *, default: bool) -> bool:
    """Read a boolean query-string flag. See flag_value."""
    return flag_value(field, args, default=default)


# ---------------------------------------------------------------------------
# RAG payloads
# ---------------------------------------------------------------------------

# Long enough for a real question, short enough that a pasted document is
# rejected rather than embedded. The shared pipeline hashes the words of a
# question into a 256-dimension vector, so a very long question retrieves
# against everything and therefore against nothing in particular.
MAX_QUESTION_LENGTH = 500

# The shared server derives its confidence category from how many chunks came
# back, so top_k is not a free parameter: below 3 caps every answer at Medium.
# The ceiling is the corpus being small -- asking for 50 chunks would retrieve
# the whole thing and ground every answer in all of it.
MIN_TOP_K = 1
MAX_TOP_K = 20


def _clean_top_k(value: Any, errors: list[str]) -> int | None:
    """Validate an optional top_k. None means "use the configured default"."""
    if value is None:
        return None
    if isinstance(value, bool):
        errors.append("top_k must be an integer")
        return None
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            errors.append("top_k must be an integer")
            return None
    if not isinstance(value, int):
        errors.append("top_k must be an integer")
        return None
    if not MIN_TOP_K <= value <= MAX_TOP_K:
        errors.append(f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}")
        return None
    return value


def validate_rag_question(payload: Any) -> dict:
    """Validate a POST /api/rag/ask body."""
    payload = require_object(payload)
    errors: list[str] = []

    clean = {
        "question": clean_string(
            payload, "question", errors, required=True, max_length=MAX_QUESTION_LENGTH
        ),
        "top_k": _clean_top_k(payload.get("top_k"), errors),
    }

    if errors:
        raise ValidationFailed(errors)
    return clean


def validate_rag_options(payload: Any, args: Any = None) -> dict:
    """Validate the options for an endpoint that builds its own question.

    POST /api/goals/<id>/explain takes no question -- it writes one from the
    goal's observed figures -- so the only option is retrieval depth, from
    either a JSON body or the query string.
    """
    payload = payload if isinstance(payload, dict) else {}
    errors: list[str] = []

    raw = payload.get("top_k")
    if raw is None and args is not None:
        raw = args.get("top_k")

    clean = {"top_k": _clean_top_k(raw, errors)}

    if errors:
        raise ValidationFailed(errors)
    return clean
