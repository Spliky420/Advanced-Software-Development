import pytest
import requests

import library_qa
import rag_client

LIBRARY_CHUNK = {
    "rank": 1,
    "chunk_id": "Enerel_research_library_knowledge_1",
    "source_id": "Enerel_research_library_knowledge.txt",
    "text": (
        "The Research Library summarizes a long document map-reduce style: "
        "each chunk is summarized first, then the chunk summaries are combined."
    ),
    "distance": 0.8,
}
UNRELATED_CHUNK = {
    "rank": 2,
    "chunk_id": "Thomas_personal_finance_knowledge_1",
    "source_id": "Thomas_personal_finance_knowledge.txt",
    "text": "Receipts provide supporting evidence for transactions.",
    "distance": 1.1,
}


class StubAnswer:
    def __init__(self, text="It summarizes each chunk, then combines them.", confidence="High"):
        self.text = text
        self.confidence = confidence
        self.calls = []

    def __call__(self, question, k):
        self.calls.append((question, k))
        return {"answer": self.text, "confidence_category": self.confidence, "citations": []}


def retrieve_returning(*chunks):
    return lambda question, k: list(chunks)


# --------------------------------------------------------------------------
# PLAN
# --------------------------------------------------------------------------

def test_content_terms_drops_stopwords_short_words_and_duplicates():
    assert library_qa.content_terms("How does the library summarize a long long document?") == [
        "library", "summarize", "long", "document",
    ]


@pytest.mark.parametrize("question", [None, "", "   ", 42])
def test_plan_rejects_missing_question(question):
    with pytest.raises(library_qa.QuestionError, match="required"):
        library_qa.plan(question)


def test_plan_rejects_overlong_question():
    with pytest.raises(library_qa.QuestionError, match="at most"):
        library_qa.plan("word " * 200)


def test_plan_rejects_question_with_only_stopwords():
    with pytest.raises(library_qa.QuestionError, match="no searchable terms"):
        library_qa.plan("what is it?")


def test_plan_reads_top_k_from_env(monkeypatch):
    monkeypatch.setenv("RAG_TOP_K", "3")
    assert library_qa.plan("summarize documents")["top_k"] == 3


@pytest.mark.parametrize("raw", ["0", "99", "abc", ""])
def test_plan_ignores_invalid_top_k(monkeypatch, raw):
    monkeypatch.setenv("RAG_TOP_K", raw)
    assert library_qa.plan("summarize documents")["top_k"] == library_qa.DEFAULT_TOP_K


# --------------------------------------------------------------------------
# OBSERVE -- coverage and confidence, all Python
# --------------------------------------------------------------------------

def observe_for(question, *chunks):
    plan_result = library_qa.plan(question)
    act_result = library_qa.act(plan_result, retrieve_fn=retrieve_returning(*chunks))
    return library_qa.observe(plan_result, act_result)


def test_observe_full_coverage_is_high_and_cites_only_supporting_chunks():
    result = observe_for("How does the library summarize a long document?", LIBRARY_CHUNK, UNRELATED_CHUNK)

    assert result["coverage"] == 1.0
    assert result["confidence_category"] == "High"
    assert result["sufficient"] is True
    assert [c["chunk_id"] for c in result["supporting_chunks"]] == [LIBRARY_CHUNK["chunk_id"]]


def test_observe_prefix_match_counts_word_variants():
    # "summarization" shares the 6-letter prefix "summar" with "summarizes".
    result = observe_for("library summarization", LIBRARY_CHUNK)
    assert result["missing_terms"] == []


def test_observe_plurals_match_singulars_both_ways():
    chunk = {**LIBRARY_CHUNK, "text": "Each document type is stored with its sources."}
    result = observe_for("document types source", chunk)
    assert result["missing_terms"] == []


def test_citations_need_half_the_terms_and_are_capped():
    weak = {**UNRELATED_CHUNK, "rank": 1, "chunk_id": "weak", "text": "The library."}
    strong = [
        {**LIBRARY_CHUNK, "rank": i + 2, "chunk_id": f"strong{i}"} for i in range(4)
    ]
    result = observe_for("How does the library summarize a long document?", weak, *strong)

    assert result["supporting_count"] == 5
    assert [c["chunk_id"] for c in result["citations"]] == ["strong0", "strong1", "strong2"]


def test_thin_coverage_still_cites_the_best_chunk():
    a = {**LIBRARY_CHUNK, "rank": 1, "chunk_id": "a", "text": "library"}
    b = {**LIBRARY_CHUNK, "rank": 2, "chunk_id": "b", "text": "summarize"}
    result = observe_for("library summarize document mortgage", a, b)

    assert result["confidence_category"] == "Medium"
    assert [c["chunk_id"] for c in result["citations"]] == ["a"]


def test_chunk_about_the_term_outranks_one_that_mentions_it_once():
    passing = {**UNRELATED_CHUNK, "rank": 1, "chunk_id": "liquidity", "text": "Shares and ETFs are liquid."}
    about = {**LIBRARY_CHUNK, "rank": 2, "chunk_id": "etf", "text": "An ETF is a fund. ETFs trade on the ASX. Each ETF tracks an index."}
    result = observe_for("What is an ETF?", passing, about)

    assert [c["chunk_id"] for c in result["citations"]] == ["etf", "liquidity"]
    assert result["supporting_chunks"][0]["term_hits"] == 3


def test_observe_no_overlap_is_insufficient():
    result = observe_for("Who won the football world cup?", LIBRARY_CHUNK, UNRELATED_CHUNK)

    assert result["coverage"] == 0.0
    assert result["confidence_category"] == "Insufficient"
    assert result["sufficient"] is False
    assert result["supporting_chunks"] == []


def test_observe_with_no_chunks_is_insufficient():
    assert observe_for("summarize documents")["sufficient"] is False


@pytest.mark.parametrize(
    "coverage, expected",
    [(1.0, "High"), (0.75, "High"), (0.74, "Medium"), (0.5, "Medium"), (0.34, "Low"), (0.33, "Insufficient"), (0.0, "Insufficient")],
)
def test_confidence_bands(coverage, expected):
    assert library_qa.confidence_for(coverage) == expected


def test_most_matched_chunk_is_cited_first():
    partial = {**UNRELATED_CHUNK, "rank": 1, "text": "The library stores documents."}
    full = {**LIBRARY_CHUNK, "rank": 2}
    result = observe_for("library summarize document", partial, full)
    assert [c["chunk_id"] for c in result["supporting_chunks"]] == [full["chunk_id"], partial["chunk_id"]]


# --------------------------------------------------------------------------
# ADAPT -- the model is only reached when Observe allows it
# --------------------------------------------------------------------------

def test_ask_answers_when_grounded():
    stub = StubAnswer()
    _, _, observe_result, adapt_result = library_qa.ask(
        "How does the library summarize a long document?",
        retrieve_fn=retrieve_returning(LIBRARY_CHUNK),
        answer_fn=stub,
    )
    assert adapt_result["status"] == "answered"
    assert adapt_result["answer"] == stub.text
    assert adapt_result["llm_called"] is True
    assert len(stub.calls) == 1


def test_ask_never_calls_the_model_when_context_is_insufficient():
    stub = StubAnswer()
    _, _, _, adapt_result = library_qa.ask(
        "Who won the football world cup?",
        retrieve_fn=retrieve_returning(LIBRARY_CHUNK),
        answer_fn=stub,
    )
    assert adapt_result["status"] == "insufficient_context"
    assert adapt_result["llm_called"] is False
    assert adapt_result["answer"] == library_qa.INSUFFICIENT_ANSWER
    assert stub.calls == []


@pytest.mark.parametrize("model_text", ["Insufficient evidence.", "  insufficient EVIDENCE  ", ""])
def test_model_reporting_no_evidence_becomes_insufficient_context(model_text):
    _, _, _, adapt_result = library_qa.ask(
        "How does the library summarize a long document?",
        retrieve_fn=retrieve_returning(LIBRARY_CHUNK),
        answer_fn=StubAnswer(text=model_text),
    )
    assert adapt_result["status"] == "insufficient_context"
    assert adapt_result["llm_called"] is True
    assert adapt_result["answer"] == library_qa.INSUFFICIENT_ANSWER


# --------------------------------------------------------------------------
# rag_client -- HTTP behaviour, no real network
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def rag_on(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_SERVER_URL", "http://rag.test:5003/")


def test_retrieve_posts_query_k_and_caller(monkeypatch, rag_on):
    seen = {}

    def fake_post(url, json, timeout):
        seen.update(url=url, json=json)
        return FakeResponse(200, {"status": "success", "results": [LIBRARY_CHUNK]})

    monkeypatch.setattr(rag_client.requests, "post", fake_post)

    assert rag_client.retrieve("q", 4) == [LIBRARY_CHUNK]
    assert seen == {"url": "http://rag.test:5003/retrieve", "json": {"query": "q", "k": 4, "caller": "Enerel"}}


def test_disabled_rag_never_posts(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setattr(rag_client.requests, "post", lambda *a, **k: pytest.fail("RAG must not be called when disabled"))

    with pytest.raises(rag_client.RAGDisabledError):
        rag_client.retrieve("q", 5)


def test_connection_error_becomes_unavailable(monkeypatch, rag_on):
    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(rag_client.requests, "post", boom)

    with pytest.raises(rag_client.RAGUnavailableError, match="could not reach"):
        rag_client.answer("q", 5)


@pytest.mark.parametrize(
    "status, payload, match",
    [
        (500, {"status": "error", "error": "chroma exploded"}, "chroma exploded"),
        (200, ValueError("bad json"), "non-JSON"),
        (200, {"status": "success"}, "no answer text"),
    ],
)
def test_bad_rag_responses_become_unavailable(monkeypatch, rag_on, status, payload, match):
    monkeypatch.setattr(rag_client.requests, "post", lambda *a, **k: FakeResponse(status, payload))

    with pytest.raises(rag_client.RAGUnavailableError, match=match):
        rag_client.answer("q", 5)
