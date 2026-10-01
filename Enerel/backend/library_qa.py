"""Grounded question answering over the shared RAG server: Plan -> Act -> Observe -> Adapt.

Same loop shape as summarize.py. Plan, Act and Observe make no model call at
all -- Act only asks the shared RAG server for ranked chunks (/retrieve is a
vector lookup) -- and only Adapt asks the server to generate an answer
(/answer), and only if Observe decided the retrieved context can support one.

Why Observe gates on term coverage rather than the RAG server's own signal:
the shared server's confidence_category is "High" whenever it returns 3+
chunks, and it always returns k chunks, so it cannot tell a relevant result
from an irrelevant one. Its distances do not help either -- its embedding is
a hashed bag of words that stopwords dominate. So this module measures
grounding directly, in Python: which of the question's content terms
actually appear in the retrieved text. That one number decides both the
confidence category and whether to answer at all, which is how "display an
insufficient-context response instead of generating an unsupported answer"
is enforced -- an ungrounded question never reaches the model.

Every figure here (coverage, matched-term counts) is computed in Python, per
CLAUDE.md's arithmetic rule. The model only writes prose from retrieved text.
"""

import math
import os
import re

import rag_client

# Deliberately the maximum the endpoint allows. The shared RAG server's
# hashed bag-of-words embedding ranks the right chunk poorly (punctuation
# and stopwords dominate it), so a deep retrieval lets Observe's term
# matching find the relevant chunk even when the server ranks it low --
# measured on the investment-terms corpus: right chunk cited 7/12 at k=8,
# 10/12 at k=20. Chroma returns every chunk if the corpus has fewer. Override
# with RAG_TOP_K.
DEFAULT_TOP_K = 20
MAX_QUESTION_LENGTH = 500
SNIPPET_CHARS = 220
# A supporting chunk is cited only if it matches at least half the
# question's terms, so a chunk that merely shares a generic word ("library")
# isn't presented as a source. At most this many are cited.
MAX_CITATIONS = 3

# Coverage = share of the question's content terms found anywhere in the
# retrieved chunks. Bands are inclusive lower bounds.
HIGH_COVERAGE = 0.75
MEDIUM_COVERAGE = 0.5
MIN_COVERAGE = 0.34  # below this, the context is treated as insufficient

# Terms of at least this length also match on a shared prefix of this
# length, so "deduction" matches "deductible" and "summarise" matches
# "summary" -- a light stand-in for stemming, with no dependency.
PREFIX_MATCH_LENGTH = 6

INSUFFICIENT_ANSWER = (
    "Insufficient context: the shared knowledge base does not contain enough "
    "information to answer this question, so no answer was generated."
)
MODEL_INSUFFICIENT_MARKER = "insufficient evidence"

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """
    a about after all also an and any are as at be been being but by can could
    did do does doing for from had has have how i if in into is it its just me
    mean means my of on or our please should so some tell than that the their
    them then there these they this those to use used using was we were what
    when where which who why will with would you your explain describe give
    list show many much
    """.split()
)


class QuestionError(ValueError):
    """The question is missing, too long, or has no searchable terms."""


def _top_k():
    raw = os.environ.get("RAG_TOP_K", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TOP_K
    return value if 1 <= value <= 20 else DEFAULT_TOP_K


def content_terms(text):
    """Lower-cased, de-duplicated, order-preserving content terms of text."""
    seen = []
    for token in TOKEN_RE.findall(text.lower()):
        if len(token) < 3 or token in STOPWORDS or token in seen:
            continue
        seen.append(token)
    return seen


def _singular(token):
    """Fold a plain plural onto its singular ("types" -> "type"), leaving
    words like "loss" alone -- enough for matching, not real stemming."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _term_in(term, chunk_tokens):
    if term in chunk_tokens or _singular(term) in chunk_tokens:
        return True
    if len(term) < PREFIX_MATCH_LENGTH:
        return False
    prefix = term[:PREFIX_MATCH_LENGTH]
    return any(len(t) >= PREFIX_MATCH_LENGTH and t[:PREFIX_MATCH_LENGTH] == prefix for t in chunk_tokens)


def confidence_for(coverage):
    if coverage >= HIGH_COVERAGE:
        return "High"
    if coverage >= MEDIUM_COVERAGE:
        return "Medium"
    if coverage >= MIN_COVERAGE:
        return "Low"
    return "Insufficient"


def plan(question):
    """PLAN: validate the question and pick out the terms grounding is measured on."""
    if not isinstance(question, str) or not question.strip():
        raise QuestionError("question is required and cannot be empty")
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        raise QuestionError(f"question must be at most {MAX_QUESTION_LENGTH} characters")

    terms = content_terms(question)
    if not terms:
        raise QuestionError("question has no searchable terms -- ask about a specific topic")

    return {
        "phase": "plan",
        "description": (
            "Validate the question, extract its content terms, and decide how "
            "many chunks to retrieve from the shared RAG server."
        ),
        "question": question,
        "terms": terms,
        "top_k": _top_k(),
    }


def act(plan_result, retrieve_fn=None):
    """ACT: retrieve ranked chunks from the shared RAG server. No model call."""
    retrieve = retrieve_fn if retrieve_fn is not None else rag_client.retrieve
    chunks = retrieve(plan_result["question"], plan_result["top_k"])
    return {
        "phase": "act",
        "description": "Retrieve ranked context chunks from the shared RAG server (/retrieve).",
        "rag_server": rag_client.server_url(),
        "chunks": chunks,
    }


def observe(plan_result, act_result):
    """OBSERVE: measure, in Python, how much of the question the context covers."""
    terms = plan_result["terms"]
    supporting = []
    covered = set()

    for chunk in act_result["chunks"]:
        text = chunk.get("text") or ""
        raw_tokens = TOKEN_RE.findall(text.lower())
        chunk_tokens = set(raw_tokens) | {_singular(t) for t in raw_tokens}
        matched = [term for term in terms if _term_in(term, chunk_tokens)]
        if not matched:
            continue
        covered.update(matched)
        # How often the matched terms occur -- a chunk *about* ETFs says
        # "ETF" many times, one that mentions ETFs in passing says it once.
        term_hits = sum(1 for t in raw_tokens if any(_term_in(term, {t, _singular(t)}) for term in matched))
        supporting.append({
            "chunk_id": chunk.get("chunk_id"),
            "source_id": chunk.get("source_id"),
            "rank": chunk.get("rank"),
            "matched_terms": matched,
            "term_hits": term_hits,
            "snippet": text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else ""),
        })

    # Most distinct terms matched first, then most occurrences of them, then
    # the server's own rank -- its ranking is weak (see DEFAULT_TOP_K), so it
    # is only the last tie-break.
    supporting.sort(key=lambda c: (-len(c["matched_terms"]), -c["term_hits"], c["rank"] or 0))

    coverage = round(len(covered) / len(terms), 2)
    confidence = confidence_for(coverage)

    min_matched = math.ceil(len(terms) / 2)
    cited = [c for c in supporting if len(c["matched_terms"]) >= min_matched]
    # Coverage can be spread thinly across chunks; still cite the best one.
    citations = (cited or supporting[:1])[:MAX_CITATIONS]

    return {
        "phase": "observe",
        "description": (
            "Check which of the question's terms appear in the retrieved "
            "chunks; that coverage sets the confidence category and decides "
            "whether there is enough context to answer."
        ),
        "retrieved_count": len(act_result["chunks"]),
        "supporting_count": len(supporting),
        "covered_terms": [term for term in terms if term in covered],
        "missing_terms": [term for term in terms if term not in covered],
        "coverage": coverage,
        "confidence_category": confidence,
        "sufficient": confidence != "Insufficient",
        "supporting_chunks": supporting,
        "citations": citations,
    }


def adapt(plan_result, observe_result, answer_fn=None):
    """ADAPT: ask the RAG server for a grounded answer -- only when Observe allows it."""
    base = {
        "phase": "adapt",
        "description": (
            "Generate an answer from the retrieved context via the shared RAG "
            "server (/answer), or return an insufficient-context response "
            "without calling the model when Observe found too little support."
        ),
    }

    if not observe_result["sufficient"]:
        return {
            **base,
            "llm_called": False,
            "status": "insufficient_context",
            "answer": INSUFFICIENT_ANSWER,
            "reason": "the retrieved context does not cover enough of the question",
        }

    answer_call = answer_fn if answer_fn is not None else rag_client.answer
    data = answer_call(plan_result["question"], plan_result["top_k"])
    text = data["answer"].strip()

    if not text or MODEL_INSUFFICIENT_MARKER in text.lower():
        return {
            **base,
            "llm_called": True,
            "status": "insufficient_context",
            "answer": INSUFFICIENT_ANSWER,
            "reason": "the model found no supporting evidence in the retrieved context",
            "rag_server_confidence": data.get("confidence_category"),
        }

    return {
        **base,
        "llm_called": True,
        "status": "answered",
        "answer": text,
        "rag_server_confidence": data.get("confidence_category"),
    }


def ask(question, retrieve_fn=None, answer_fn=None):
    """Run the whole loop; returns (plan, act, observe, adapt)."""
    plan_result = plan(question)
    act_result = act(plan_result, retrieve_fn=retrieve_fn)
    observe_result = observe(plan_result, act_result)
    adapt_result = adapt(plan_result, observe_result, answer_fn=answer_fn)
    return plan_result, act_result, observe_result, adapt_result
