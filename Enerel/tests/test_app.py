import os
import sqlite3

import pytest

import app as app_module
import db
import llm

DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    try:
        with open(os.path.join(DATABASE_DIR, "init.sql"), encoding="utf-8") as handle:
            conn.executescript(handle.read())
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", str(db_path))

    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def no_real_ollama_calls(monkeypatch):
    """Every test either stubs llm.generate/llm.embed explicitly or expects
    them never to be called; fail loudly if a test accidentally reaches
    Ollama instead of silently hanging or hitting the network.
    """

    def refuse_generate(*args, **kwargs):
        raise AssertionError("llm.generate should have been stubbed in this test")

    def refuse_embed(*args, **kwargs):
        raise AssertionError("llm.embed should have been stubbed in this test")

    monkeypatch.setattr(llm, "generate", refuse_generate)
    monkeypatch.setattr(llm, "embed", refuse_embed)


def make_payload(**overrides):
    payload = {
        "title": "Understanding Dollar-Cost Averaging",
        "source": "Investopedia",
        "doc_type": "guide",
        "published_on": "2025-11-03",
        "body_text": "Dollar-cost averaging is an investment strategy that spreads purchases over time.",
    }
    payload.update(overrides)
    return payload


def stub_embed(monkeypatch, vector=None):
    vector = vector or [1.0, 0.0, 0.0]

    def fake_embed(text):
        return vector, "stub-embed-model"

    monkeypatch.setattr(llm, "embed", fake_embed)
    return fake_embed


def stub_generate(monkeypatch, response=None):
    response = response or "SUMMARY: A concise summary.\nKEY POINTS:\n- First point\n- Second point"

    def fake_generate(prompt, system=None):
        return response, "stub-model"

    monkeypatch.setattr(llm, "generate", fake_generate)
    return fake_generate


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_health_reports_ok_when_database_reachable(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

def test_list_documents_starts_empty(client):
    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.get_json() == []


def test_create_document_returns_201_and_the_stored_row(client, monkeypatch):
    stub_embed(monkeypatch)

    response = client.post("/api/documents", json=make_payload())

    assert response.status_code == 201
    body = response.get_json()
    assert body["title"] == "Understanding Dollar-Cost Averaging"
    assert body["doc_type"] == "guide"
    assert body["indexing"]["indexed"] is True
    assert body["indexing"]["chunk_count"] == 1


def test_create_document_rejects_invalid_payload(client):
    response = client.post("/api/documents", json=make_payload(doc_type="not-real"))

    assert response.status_code == 400
    assert "errors" in response.get_json()


def test_create_document_succeeds_even_when_embedding_model_unavailable(client, monkeypatch):
    def failing_embed(text):
        raise llm.LLMUnavailableError("model not pulled")

    monkeypatch.setattr(llm, "embed", failing_embed)

    response = client.post("/api/documents", json=make_payload())

    assert response.status_code == 201
    body = response.get_json()
    assert body["indexing"]["indexed"] is False
    assert "model not pulled" in body["indexing"]["error"]


def test_get_document_returns_full_body_text(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()

    response = client.get(f"/api/documents/{created['id']}")

    assert response.status_code == 200
    assert response.get_json()["body_text"] == make_payload()["body_text"]


def test_get_document_404_when_missing(client):
    response = client.get("/api/documents/999")

    assert response.status_code == 404


def test_update_document_replaces_metadata_and_body(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()

    response = client.put(
        f"/api/documents/{created['id']}",
        json=make_payload(title="Updated Title", body_text="Completely new body text."),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["title"] == "Updated Title"

    fetched = client.get(f"/api/documents/{created['id']}").get_json()
    assert fetched["body_text"] == "Completely new body text."


def test_update_document_404_when_missing(client):
    response = client.put("/api/documents/999", json=make_payload())

    assert response.status_code == 404


def test_delete_document_removes_it(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()

    delete_response = client.delete(f"/api/documents/{created['id']}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/documents/{created['id']}")
    assert get_response.status_code == 404


def test_delete_document_404_when_missing(client):
    response = client.delete("/api/documents/999")

    assert response.status_code == 404


def test_list_documents_filters_by_doc_type(client, monkeypatch):
    stub_embed(monkeypatch)
    client.post("/api/documents", json=make_payload(title="Guide A", doc_type="guide"))
    client.post("/api/documents", json=make_payload(title="News A", doc_type="news"))

    response = client.get("/api/documents?doc_type=news")

    body = response.get_json()
    assert len(body) == 1
    assert body[0]["title"] == "News A"


def test_list_documents_filters_by_title_substring(client, monkeypatch):
    stub_embed(monkeypatch)
    client.post("/api/documents", json=make_payload(title="Inflation Outlook"))
    client.post("/api/documents", json=make_payload(title="ETF Guide"))

    response = client.get("/api/documents?q=inflation")

    body = response.get_json()
    assert len(body) == 1
    assert body[0]["title"] == "Inflation Outlook"


# --------------------------------------------------------------------------
# summarize
# --------------------------------------------------------------------------

def test_summarize_stores_and_returns_summary(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()
    stub_generate(monkeypatch)

    response = client.post(f"/api/documents/{created['id']}/summarize")

    assert response.status_code == 201
    body = response.get_json()
    assert body["adapt"]["summary_text"] == "A concise summary."
    assert body["adapt"]["key_points"] == ["First point", "Second point"]
    assert body["document"]["summary_text"] == "A concise summary."


def test_summarize_404_when_document_missing(client):
    response = client.post("/api/documents/999/summarize")

    assert response.status_code == 404


def test_summarize_503_when_model_unavailable(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()

    def failing_generate(prompt, system=None):
        raise llm.LLMUnavailableError("could not reach Ollama")

    monkeypatch.setattr(llm, "generate", failing_generate)

    response = client.post(f"/api/documents/{created['id']}/summarize")

    assert response.status_code == 503


def test_get_summary_before_summarizing_reports_not_summarized(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()

    response = client.get(f"/api/documents/{created['id']}/summary")

    assert response.status_code == 200
    body = response.get_json()
    assert body["summarized"] is False
    assert body["summary_text"] is None
    assert body["key_points"] == []


def test_get_summary_after_summarizing_returns_stored_result(client, monkeypatch):
    stub_embed(monkeypatch)
    created = client.post("/api/documents", json=make_payload()).get_json()
    stub_generate(monkeypatch)
    client.post(f"/api/documents/{created['id']}/summarize")

    response = client.get(f"/api/documents/{created['id']}/summary")

    body = response.get_json()
    assert body["summarized"] is True
    assert body["summary_text"] == "A concise summary."
    assert body["key_points"] == ["First point", "Second point"]


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def test_search_returns_indexed_chunks_ranked_by_relevance(client, monkeypatch):
    stub_embed(monkeypatch, vector=[1.0, 0.0])
    client.post("/api/documents", json=make_payload(title="Matches Well"))

    def query_embed(text):
        return [1.0, 0.0], "stub-embed-model"

    monkeypatch.setattr(llm, "embed", query_embed)

    response = client.post("/api/documents/search", json={"query": "dollar-cost averaging"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["observe"]["result_count"] == 1
    assert body["observe"]["results"][0]["title"] == "Matches Well"


def test_search_returns_empty_results_when_nothing_indexed(client, monkeypatch):
    def query_embed(text):
        return [1.0, 0.0], "stub-embed-model"

    monkeypatch.setattr(llm, "embed", query_embed)

    response = client.post("/api/documents/search", json={"query": "anything"})

    assert response.status_code == 200
    assert response.get_json()["observe"]["result_count"] == 0


def test_search_rejects_empty_query(client):
    response = client.post("/api/documents/search", json={"query": ""})

    assert response.status_code == 400


def test_search_503_when_embedding_model_unavailable(client, monkeypatch):
    def failing_embed(text):
        raise llm.LLMUnavailableError("model not pulled")

    monkeypatch.setattr(llm, "embed", failing_embed)

    response = client.post("/api/documents/search", json={"query": "anything"})

    assert response.status_code == 503
