"""The RAG client and the three RAG endpoints.

Four claims under test, in rough order of how much a marker will care:

**Citations and the confidence category are passed through unmodified.** Not
re-ordered, not re-labelled, not recomputed, and not "improved" when the
server sends something this UI did not expect. A confidence this backend
calculated would be this backend's opinion of someone else's retrieval.

**"Insufficient evidence." is surfaced, not papered over.** It comes back as a
200 with the sentence intact and a derived flag beside it. There is no
fallback to an ungrounded answer, and a test asserts that the model is not
asked a second time.

**The goal explanation's question is built from Python's figures**, concept
words first -- because the shared pipeline retrieves on word overlap using the
same string it answers with, so a question that opens with currency amounts
retrieves against currency amounts.

**The server being down is a clean 503 that says what to check**, and the
attempt is still audited.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import RAG_ANSWER, RAG_CHUNKS, RAG_SOURCE, rag_citations

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.rag import client as rag_client

GOAL_ID = 3  # seeded behind its plan
ACHIEVED_GOAL_ID = 8


def _ask(client, question="What does it mean to be behind on a savings goal?", **body):
    response = client.post("/api/rag/ask", json={"question": question, **body})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _explain(client, goal_id=GOAL_ID, **body):
    response = client.post(f"/api/goals/{goal_id}/explain", json=body or None)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _rag_rows(conn, goal_id=None):
    if goal_id is None:
        return conn.execute("SELECT * FROM ai_plan_log WHERE phase = 'rag' ORDER BY log_id").fetchall()
    return conn.execute(
        "SELECT * FROM ai_plan_log WHERE phase = 'rag' AND goal_id = ? ORDER BY log_id", (goal_id,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


def test_ask_returns_the_answer_citations_confidence_and_chunks(client, stub_rag):
    stub_rag()

    body = _ask(client)

    assert body["answer"] == RAG_ANSWER
    assert body["citations"] == rag_citations()
    assert body["confidence_category"] == "High"
    assert body["retrieved_chunks"] == RAG_CHUNKS
    assert body["retrieval_summary"] == {"k": 5, "retrieved_count": 3}
    assert body["insufficient_evidence"] is False
    assert body["log_id"]


def test_ask_calls_retrieve_and_answer_with_the_same_question_and_depth(client, stub_rag):
    """The chunk text shown has to be the text that grounded the answer."""
    calls = stub_rag()

    _ask(client, question="How should competing savings goals be prioritised?")

    assert [call["path"] for call in calls] == ["/retrieve", "/answer"]
    assert calls[0]["payload"]["query"] == calls[1]["payload"]["query"]
    assert calls[0]["payload"]["k"] == calls[1]["payload"]["k"] == 5


def test_the_chunks_are_confirmed_to_match_the_citations(client, stub_rag):
    stub_rag()

    assert _ask(client)["chunks_match_citations"] is True


def test_a_mismatch_between_chunks_and_citations_is_reported_not_hidden(client, stub_rag):
    """Only possible if the corpus were refreshed between the two calls. The
    response says so rather than showing text that did not ground anything."""
    stub_rag(citations=[{"chunk_id": "something_else_1", "source_id": "other.txt"}])

    body = _ask(client)

    assert body["chunks_match_citations"] is False
    # And the citations are still the server's, untouched.
    assert body["citations"] == [{"chunk_id": "something_else_1", "source_id": "other.txt"}]


def test_this_backend_identifies_itself_to_the_rag_servers_audit_log(client, stub_rag):
    """rag-server records a `caller` per request in its own audit file."""
    calls = stub_rag()

    _ask(client)

    assert calls[0]["payload"]["caller"] == "lehoalong-goals-budgeting"


# ---------------------------------------------------------------------------
# Pass-through -- the marking requirement
# ---------------------------------------------------------------------------


def test_citations_are_passed_through_object_for_object(client, stub_rag):
    """Including extra fields this backend knows nothing about, and in the
    server's order -- re-sorting would be a modification too."""
    supplied = [
        {"chunk_id": "c_3", "source_id": "a.txt", "score": 0.91, "note": "added later"},
        {"chunk_id": "c_1", "source_id": "b.txt", "score": 0.44},
    ]
    stub_rag(citations=supplied)

    assert _ask(client)["citations"] == supplied


@pytest.mark.parametrize("confidence", ["High", "Medium", "Low", "Unknown", "", None])
def test_the_confidence_category_is_never_relabelled(client, stub_rag, confidence):
    """"Low" and "Unknown" included deliberately. The shared server currently
    never returns Low -- it reads >=3 chunks as High and fewer as Medium -- but
    if that changes, this client must carry the new value rather than mapping
    it onto what it expected."""
    stub_rag(confidence=confidence)

    assert _ask(client)["confidence_category"] == confidence


def test_the_confidence_is_not_recomputed_from_the_chunk_count(client, stub_rag):
    """One chunk with a High category is contradictory by the server's own
    rule, and it is still passed through. Second-guessing it here would mean
    this backend quietly owning a figure it did not compute."""
    stub_rag(chunks=RAG_CHUNKS[:1], confidence="High")

    body = _ask(client)

    assert body["confidence_category"] == "High"
    assert len(body["retrieved_chunks"]) == 1


def test_the_distance_is_not_converted_into_a_similarity(client, stub_rag):
    """Lower is closer in Chroma. Inverting it here would be inventing a
    score, so the server's units and field name are kept."""
    body = _ask(client)["retrieved_chunks"] if stub_rag() is None else _ask(client)["retrieved_chunks"]

    assert body[0]["distance"] == RAG_CHUNKS[0]["distance"]
    assert "similarity" not in body[0]


# ---------------------------------------------------------------------------
# Insufficient evidence
# ---------------------------------------------------------------------------


def test_insufficient_evidence_is_surfaced_exactly(client, stub_rag):
    stub_rag(answer="Insufficient evidence.")

    body = _ask(client, question="What is the capital of France?")

    assert body["answer"] == "Insufficient evidence."
    assert body["insufficient_evidence"] is True


def test_insufficient_evidence_does_not_fall_back_to_an_ungrounded_answer(client, stub_rag):
    """The point of grounding. One call to /answer, no retry, no substitute."""
    calls = stub_rag(answer="Insufficient evidence.")

    _ask(client)

    assert [call["path"] for call in calls] == ["/retrieve", "/answer"]


def test_insufficient_evidence_still_returns_the_citations_it_had(client, stub_rag):
    """Chunks were retrieved; they just did not support an answer. Showing
    what was looked at is part of being honest about why."""
    stub_rag(answer="Insufficient evidence.")

    body = _ask(client)

    assert body["citations"] == rag_citations()
    assert body["retrieved_chunks"] == RAG_CHUNKS


@pytest.mark.parametrize(
    "answer",
    ["Insufficient evidence.", "insufficient evidence.", "  Insufficient evidence.  ", "INSUFFICIENT EVIDENCE."],
)
def test_insufficient_evidence_is_detected_despite_small_model_variation(client, stub_rag, answer):
    """A 0.5b model varies capitalisation and trailing whitespace. Treating
    "insufficient evidence." as a real answer would be worse than matching
    loosely."""
    stub_rag(answer=answer)

    assert _ask(client)["insufficient_evidence"] is True


def test_an_answer_that_merely_mentions_evidence_is_not_flagged(client, stub_rag):
    stub_rag(answer="There is insufficient evidence in the context about tax, but goals are explained.")

    assert _ask(client)["insufficient_evidence"] is False


def test_insufficient_evidence_is_recorded_as_such_in_the_audit_trail(client, stub_rag, conn):
    stub_rag(answer="Insufficient evidence.")

    _ask(client)

    logged = json.loads(_rag_rows(conn)[0]["response"])
    assert logged["insufficient_evidence"] is True
    assert logged["answer"] == "Insufficient evidence."


# ---------------------------------------------------------------------------
# The server being down or broken
# ---------------------------------------------------------------------------


def test_an_unreachable_server_is_a_503_that_says_what_to_check(client, stub_rag):
    stub_rag(
        unavailable=rag_client.RAGUnavailable(
            "could not reach the RAG server at http://rag.invalid:5003/answer: refused. "
            "It runs as a host process, not a container"
        )
    )

    response = client.post("/api/rag/ask", json={"question": "anything"})

    assert response.status_code == 503
    assert "host process" in response.get_json()["error"]


def test_an_unreachable_server_still_records_the_question(client, stub_rag, conn):
    stub_rag(unavailable=rag_client.RAGUnavailable("could not reach the RAG server: refused"))

    client.post("/api/rag/ask", json={"question": "what is an emergency fund?"})

    rows = _rag_rows(conn)
    assert len(rows) == 1
    assert rows[0]["prompt"] == "what is an emergency fund?"
    assert json.loads(rows[0]["response"])["unavailable"] is True


def test_an_answer_with_no_answer_text_is_a_503_naming_the_contract(client, stub_rag):
    """If the shared server's contract changes under this feature, it should
    fail loudly rather than render an empty grounded answer."""
    stub_rag(overrides={"answer": None})

    response = client.post("/api/rag/ask", json={"question": "anything"})

    assert response.status_code == 503
    assert "confidence_category" in response.get_json()["error"]


def test_a_missing_citations_field_does_not_invent_citations(client, stub_rag):
    """An empty list is the honest answer. Deriving citations from the chunks
    this client retrieved separately would be fabricating the server's
    attribution."""
    stub_rag(overrides={"citations": None})

    body = _ask(client)

    assert body["citations"] == []
    assert body["chunks_match_citations"] is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("post", "/api/rag/ask", {"question": "x"}), ("post", f"/api/goals/{GOAL_ID}/explain", None)],
)
def test_disabled_rag_is_a_503_that_says_so(client, app, stub_rag, method, path, body):
    """The CI configuration: RAG_ENABLED=false."""
    stub_rag()
    app.config["RAG_ENABLED"] = False

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 503
    assert "RAG_ENABLED=false" in response.get_json()["error"]


def test_disabled_rag_does_not_touch_the_server(client, app, stub_rag):
    calls = stub_rag()
    app.config["RAG_ENABLED"] = False

    client.post("/api/rag/ask", json={"question": "x"})

    assert calls == []


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_reports_a_reachable_server(client, stub_rag):
    stub_rag()

    body = client.get("/api/rag/health").get_json()

    assert body["enabled"] is True
    assert body["reachable"] is True
    assert body["service"] == "rag-server"
    assert body["server_url"] == "http://rag.invalid:5003"


def test_health_reports_an_unreachable_server_as_200(client, stub_rag):
    stub_rag(healthy=False)

    response = client.get("/api/rag/health")

    assert response.status_code == 200
    assert response.get_json()["reachable"] is False
    assert "refused" in response.get_json()["detail"]


def test_health_reports_disabled_without_connecting(client, app, stub_rag):
    calls = stub_rag()
    app.config["RAG_ENABLED"] = False

    body = client.get("/api/rag/health").get_json()

    assert body["enabled"] is False
    assert body["reachable"] is False
    assert "RAG_ENABLED=false" in body["detail"]
    assert calls == []


def test_the_health_probe_uses_its_own_short_timeout(client, stub_rag):
    """A page load must not block on the 150s a grounded answer may take."""
    calls = stub_rag()

    client.get("/api/rag/health")

    assert calls[0]["timeout"] == rag_client.HEALTH_TIMEOUT_SECONDS
    assert rag_client.HEALTH_TIMEOUT_SECONDS < 10


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, "question is required"),
        ({"question": ""}, "question must not be empty"),
        ({"question": 7}, "question must be a string"),
        ({"question": "x" * 501}, "question must be 500 characters or fewer"),
        ({"question": "x", "top_k": 0}, "top_k must be between 1 and 20"),
        ({"question": "x", "top_k": 21}, "top_k must be between 1 and 20"),
        ({"question": "x", "top_k": "lots"}, "top_k must be an integer"),
        ({"question": "x", "top_k": True}, "top_k must be an integer"),
    ],
)
def test_ask_rejects_an_unusable_body(client, stub_rag, body, expected):
    stub_rag()

    response = client.post("/api/rag/ask", json=body)

    assert response.status_code == 400
    assert expected in response.get_json()["details"]


def test_top_k_overrides_the_configured_default(client, stub_rag):
    calls = stub_rag()

    _ask(client, top_k=2)

    assert calls[0]["payload"]["k"] == 2
    assert calls[1]["payload"]["k"] == 2


def test_validation_happens_before_the_server_is_called(client, stub_rag):
    calls = stub_rag()

    client.post("/api/rag/ask", json={})

    assert calls == []


# ---------------------------------------------------------------------------
# The goal explanation
# ---------------------------------------------------------------------------


def test_explain_builds_the_question_from_pythons_figures(client, stub_rag):
    calls = stub_rag()

    body = _explain(client)
    question = calls[1]["payload"]["query"]
    situation = body["situation"]

    assert body["question"] == question
    assert f"{situation['saved_to_date']:,.2f}" in question
    assert f"{situation['target_amount']:,.2f}" in question
    assert f"{situation['required_to_date']:,.2f}" in question
    assert situation["status"] in question


def test_the_question_leads_with_concepts_not_figures(client, stub_rag):
    """Not cosmetic. The shared pipeline embeds a question by hashing its
    words and uses the same string to retrieve and to answer, so a question
    that opens with currency amounts retrieves against currency amounts."""
    calls = stub_rag()

    _explain(client)
    question = calls[1]["payload"]["query"]

    first_line = question.splitlines()[0]
    assert "savings goal" in first_line
    assert "contributions" in first_line
    # The figures come after the concepts, in their own sentence.
    assert question.index("My situation") > question.index("savings goal")


def test_the_question_vocabulary_follows_the_observed_status(client, stub_rag):
    """A question that said "lagging" would not find a corpus paragraph that
    says "behind" -- the retrieval matches words, not meaning."""
    calls = stub_rag()

    _explain(client, goal_id=GOAL_ID)
    behind_question = calls[1]["payload"]["query"]
    _explain(client, goal_id=ACHIEVED_GOAL_ID)
    achieved_question = calls[3]["payload"]["query"]

    assert "behind on a savings goal" in behind_question
    assert "achieved" in achieved_question
    assert "catch up" in behind_question


def test_explain_reports_the_python_figures_as_figures(client, stub_rag):
    """The UI states these itself rather than trusting the model's prose to
    repeat them correctly -- the standing caveat in CLAUDE.md about a small
    model misreading correctly-supplied figures."""
    stub_rag()

    body = _explain(client)
    progress = client.get(f"/api/goals/{GOAL_ID}/progress").get_json()

    situation = body["situation"]
    assert situation["computed_by"] == "python"
    assert situation["saved_to_date"] == progress["saved_to_date"]
    assert situation["variance"] == progress["variance"]
    assert situation["status"] == progress["status"]
    assert situation["remaining_amount"] == progress["remaining_amount"]


def test_explain_returns_citations_and_confidence_like_ask_does(client, stub_rag):
    stub_rag()

    body = _explain(client)

    assert body["citations"] == rag_citations()
    assert body["confidence_category"] == "High"
    assert body["retrieved_chunks"][0]["source_id"] == RAG_SOURCE


def test_explain_attributes_its_audit_row_to_the_goal(client, stub_rag, conn):
    stub_rag()

    body = _explain(client)

    rows = _rag_rows(conn, goal_id=GOAL_ID)
    assert len(rows) == 1
    assert rows[0]["log_id"] == body["log_id"]
    assert rows[0]["model_name"] == "rag-server"
    logged = json.loads(rows[0]["response"])
    assert logged["chunk_ids"] == [chunk["chunk_id"] for chunk in RAG_CHUNKS]
    assert logged["source_ids"] == [RAG_SOURCE]
    assert logged["confidence_category"] == "High"


def test_explain_does_not_write_a_second_observe_row(client, stub_rag, conn):
    """An explanation is a read of the same figures /progress reports, not a
    new observation of the goal."""
    stub_rag()
    before = conn.execute(
        "SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'observe' AND goal_id = ?", (GOAL_ID,)
    ).fetchone()[0]

    _explain(client)

    after = conn.execute(
        "SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'observe' AND goal_id = ?", (GOAL_ID,)
    ).fetchone()[0]
    assert after == before


def test_explain_404s_for_a_goal_that_does_not_exist(client, stub_rag):
    calls = stub_rag()

    assert client.post("/api/goals/99999/explain").status_code == 404
    assert calls == []


def test_explain_accepts_top_k_from_a_body_or_a_query_string(client, stub_rag):
    calls = stub_rag()

    _explain(client, top_k=2)
    assert calls[0]["payload"]["k"] == 2

    client.post(f"/api/goals/{GOAL_ID}/explain?top_k=4")
    assert calls[2]["payload"]["k"] == 4


def test_explain_rejects_a_bad_top_k(client, stub_rag):
    stub_rag()

    response = client.post(f"/api/goals/{GOAL_ID}/explain", json={"top_k": 99})

    assert response.status_code == 400
    assert "top_k must be between 1 and 20" in response.get_json()["details"]


# ---------------------------------------------------------------------------
# The audit row, in detail
# ---------------------------------------------------------------------------


def test_the_audit_row_stores_the_question_the_chunks_the_answer_and_the_confidence(client, stub_rag, conn):
    stub_rag()
    question = "How should competing savings goals be prioritised?"

    _ask(client, question=question)

    row = _rag_rows(conn)[0]
    assert row["phase"] == "rag"
    assert row["model_name"] == "rag-server"
    assert row["goal_id"] is None  # a general question belongs to no goal
    assert row["prompt"] == question
    logged = json.loads(row["response"])
    assert logged["answer"] == RAG_ANSWER
    assert logged["chunk_ids"] == [chunk["chunk_id"] for chunk in RAG_CHUNKS]
    assert logged["confidence_category"] == "High"
    assert logged["k"] == 5
