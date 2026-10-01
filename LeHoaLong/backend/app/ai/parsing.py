"""Parsing and validating what the model sends back.

The contract is narrow by design (see prompts.py): the model returns
descriptions keyed by step_order, and optionally a one-sentence summary.
Nothing numeric. This module turns that response into a
`{step_order: description}` mapping, or reports that it could not.

`merge_descriptions` is where the no-invented-figures guarantee actually
lives: it walks **Python's** schedule and attaches the model's words to it.
Any amount, date or extra step the model tried to send is discarded on the
way through, because it is never read.
"""

from __future__ import annotations

import json
import re

MAX_DESCRIPTION_LENGTH = 300

# Ollama's format:"json" usually returns bare JSON, but a model can still wrap
# it in prose or a ```json fence. Pull out the first {...} block before giving
# up -- a recoverable answer should not cost a retry.
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class ResponseUnusable(Exception):
    """The model's answer could not be read as the agreed shape.

    Not an error condition for the API: the caller retries once and then
    falls back to deterministic descriptions. The message is recorded in
    ai_plan_log so a bad answer is still evidence.
    """


def _loads(raw: str) -> dict:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass

    match = _JSON_BLOCK.search(raw or "")
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError as exc:
            raise ResponseUnusable(f"response was not valid JSON: {exc}") from exc
    raise ResponseUnusable("response contained no JSON object")


def _clean_description(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:MAX_DESCRIPTION_LENGTH]


def parse_step_descriptions(raw: str, expected_orders: list[int]) -> dict[int, str]:
    """Read `{"steps":[{"step_order":n,"description":"..."}]}`.

    Returns the descriptions the model supplied, keyed by step_order and
    filtered to the orders that were actually asked for. Raises
    ResponseUnusable when the shape is wrong or nothing usable came back.

    A partial answer is accepted: if the model described eight of twelve
    steps, those eight are used and the remaining four get deterministic
    descriptions. Discarding good work because the tail was missing would
    make the small model's most common failure much more expensive than it
    needs to be.
    """
    payload = _loads(raw)
    if not isinstance(payload, dict):
        raise ResponseUnusable("response JSON was not an object")

    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ResponseUnusable("response JSON had no 'steps' array")

    wanted = set(expected_orders)
    found: dict[int, str] = {}
    for entry in steps:
        if not isinstance(entry, dict):
            continue
        order = entry.get("step_order")
        if isinstance(order, bool) or not isinstance(order, int) or order not in wanted:
            continue
        description = _clean_description(entry.get("description"))
        if description is not None:
            found[order] = description

    if not found:
        raise ResponseUnusable("response contained no usable step descriptions")
    return found


def parse_summary(raw: str) -> str | None:
    """Read the optional one-sentence `summary`. None if it is missing."""
    try:
        payload = _loads(raw)
    except ResponseUnusable:
        return None
    if not isinstance(payload, dict):
        return None
    return _clean_description(payload.get("summary"))


def merge_descriptions(schedule: list[dict], descriptions: dict[int, str], fallback) -> list[dict]:
    """Attach descriptions to Python's schedule.

    This is the guarantee in code. The iteration is over `schedule` -- the
    amounts and dates Python calculated -- and the model's contribution is
    looked up by step_order and used for one field only. A model that
    returned different amounts, extra steps, or steps in another order cannot
    change what gets stored, because none of that is read here.

    `fallback(index, total)` supplies a description for any step the model did
    not usefully describe.
    """
    total = len(schedule)
    merged = []
    for index, item in enumerate(schedule):
        description = descriptions.get(item["step_order"]) or fallback(index, total)
        merged.append({**item, "description": description})
    return merged
