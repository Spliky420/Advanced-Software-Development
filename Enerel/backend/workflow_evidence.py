"""Builds the task and evidence the Research Library sends to the shared
Multi-Agent Server (Release 2).

The evidence is the document's details and its text (cut to TEXT_SENT_CHARS).
Every figure shown alongside a run -- word counts, how much text was sent --
is computed here in Python, per the arithmetic rule in CLAUDE.md, and none
of the agents is asked for a number.

Evidence keys are named for what they hold, because the Planner's steps
refer to the evidence by key and those references show up in the UI.
"""

import re

from validation import ValidationError

# Enough of the document for the Worker to describe it, small enough that
# three agent prompts stay well inside qwen2.5:0.5b's context on CPU.
TEXT_SENT_CHARS = 2000

DECISIONS = ("approve", "correct", "partial", "reject")
NOTE_MAX = 2000
CORRECTED_MAX = 10000

_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")


def text_statistics(body_text):
    words = body_text.split()
    paragraphs = [p for p in re.split(r"\n\s*\n", body_text) if p.strip()]
    sentences = len(_SENTENCE_END.findall(body_text)) or (1 if words else 0)
    return {
        "word_count": len(words),
        "sentence_count": sentences,
        "paragraph_count": len(paragraphs),
        "character_count": len(body_text),
    }


def build_task(document):
    return (
        f"Prepare a research brief for the library document \"{document['title']}\". "
        "Say what the document covers, list its main takeaways for an investor, "
        "and flag any claim in it that a reader should verify before relying on it. "
        "Write each takeaway on its own line starting with \"- \", taken from the "
        "document text itself, not a description of what you will do. "
        "Use only the supplied evidence and quote figures exactly as given."
    )


def sent_summary(document):
    """What was sent, for the UI's run facts. Not part of the evidence."""
    body = document["body_text"]
    return {
        **text_statistics(body),
        "characters_sent": min(len(body), TEXT_SENT_CHARS),
        "cut_short": len(body) > TEXT_SENT_CHARS,
    }


def build_evidence(document):
    body = document["body_text"]
    text_sent = body[:TEXT_SENT_CHARS]
    # No word/sentence counts or character totals here: they do nothing for
    # finding takeaways, and qwen2.5:0.5b latched onto them and repeated them
    # line after line. sent_summary() reports them to the UI instead.
    evidence = {
        "document_metadata": {
            "title": document["title"],
            "doc_type": document["doc_type"],
            "source": document.get("source"),
            "published_on": document.get("published_on"),
        },
        "document_text": {
            "text": text_sent,
            "cut_short": len(text_sent) < len(body),
        },
    }
    if document.get("summary_text"):
        evidence["existing_summary"] = {
            "summary_text": document["summary_text"],
            "key_points": document.get("key_points") or [],
        }
    return evidence


def remove_repeated_lines(text):
    """Drop every non-blank line that already appeared earlier in the text
    (ignoring case and spacing). Small models loop, writing the same line
    dozens of times. Returns (cleaned_text, number_of_lines_removed)."""
    seen, kept, removed = set(), [], 0
    for line in (text or "").splitlines():
        key = " ".join(line.split()).lower()
        if key and key in seen:
            removed += 1
            continue
        if key:
            seen.add(key)
        kept.append(line)
    return "\n".join(kept).strip(), removed


def accepted_brief(review, work):
    """The brief a decision keeps: the person's correction, the agents' text
    for approve or partial, and nothing for reject."""
    if review["decision"] == "correct":
        return review["corrected"]
    if review["decision"] in ("approve", "partial"):
        return remove_repeated_lines(work)[0] or None
    return None


# A list item: "1. ", "2) ", "- ", "* " or "• " at the start of a line.
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$")
_EMPHASIS = re.compile(r"\*\*|__|`")


def takeaways(brief_text):
    """The brief's list items, which the task asks the Worker to write one
    per takeaway. Markdown bold and code marks are dropped. Empty when the
    brief has no list -- a small model often just restates the plan as
    "Step N:" paragraphs -- and the UI then shows the text as it is rather
    than presenting those step lines as takeaways. A point the model repeated
    is shown once (small models loop)."""
    matches = (_LIST_ITEM.match(line) for line in brief_text.splitlines())
    points = (_EMPHASIS.sub("", m.group(1)).strip() for m in matches if m)
    return list(dict.fromkeys(point for point in points if point))


def validate_review_payload(data):
    """Mirrors the Multi-Agent Server's own rules, so a bad decision is a 400
    here without a round trip, and the UI gets field-level messages."""
    if not isinstance(data, dict):
        raise ValidationError(["request body must be a JSON object"])

    errors = []
    decision = data.get("decision")
    note = data.get("note")
    corrected = data.get("corrected")

    if decision not in DECISIONS:
        errors.append(f"decision must be one of: {', '.join(DECISIONS)}")
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
        errors.append(f"note must be a string of at most {NOTE_MAX} characters")
    if corrected is not None and (not isinstance(corrected, str) or len(corrected) > CORRECTED_MAX):
        errors.append(f"corrected must be a string of at most {CORRECTED_MAX} characters")

    note = (note or "").strip() if isinstance(note, str) else ""
    corrected = corrected.strip() if isinstance(corrected, str) else ""

    if decision == "correct" and not corrected:
        errors.append("corrected is required when the decision is 'correct'")
    if decision != "correct" and corrected:
        errors.append("corrected is only allowed when the decision is 'correct'")
    if decision == "partial" and not note:
        errors.append("note is required when the decision is 'partial': say which part is accepted")

    if errors:
        raise ValidationError(errors)

    review = {"decision": decision, "note": note}
    if decision == "correct":
        review["corrected"] = corrected
    return review
