import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return {"ids": [["netflix_1"]], "documents": [["Netflix reference"]],
                "metadatas": [[{"source_id": "netflix.txt"}]], "distances": [[0.2]]}

    class Handler:
        def do_POST(self):
            self.sent = (200, "shared handler")

    pipeline = SimpleNamespace(
        OLLAMA_MODEL="test-model", embed_texts=lambda texts: [[1.0]],
        get_collection=lambda: SimpleNamespace(query=query),
        retrieve_context=lambda *args: {"shared": True},
    )
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setitem(sys.modules, "rag_pipeline", pipeline)
    monkeypatch.setitem(sys.modules, "rag_http_server", SimpleNamespace(
        RAGHandler=Handler, ThreadingHTTPServer=object,
    ))
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_rag.py"
    spec = importlib.util.spec_from_file_location("test_rag_launcher_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, pipeline, calls


def test_unfiltered_requests_keep_shared_retrieval(launcher):
    module, _, calls = launcher
    assert module.retrieve_context("bills") == {"shared": True}
    assert calls == []


def test_provider_filter_is_applied_before_retrieval(launcher):
    module, _, calls = launcher
    token = module.source_filter.set(["netflix.txt"])
    try:
        result = module.retrieve_context("cancel Netflix")
    finally:
        module.source_filter.reset(token)
    assert calls[0]["where"] == {"source_id": {"$in": ["netflix.txt"]}}
    assert result["results"][0]["source_id"] == "netflix.txt"
    assert module.retrieve_context("other feature") == {"shared": True}


def test_empty_filter_does_not_search_other_sources(launcher):
    module, _, calls = launcher
    token = module.source_filter.set([])
    try:
        assert module.retrieve_context("price")["results"] == []
    finally:
        module.source_filter.reset(token)
    assert calls == []


@pytest.mark.parametrize("sources", ["netflix.txt", ["../netflix.txt"], [123], ["file.txt"] * 11])
def test_invalid_source_filters_are_rejected(launcher, sources):
    module, _, _ = launcher
    handler = module.FilteredRAGHandler()
    handler.path = "/retrieve"
    handler.read_json = lambda: {"source_ids": sources}
    handler.send_json = lambda status, body: setattr(handler, "sent", (status, body))
    handler.do_POST()
    assert handler.sent[0] == 400


def test_answer_errors_do_not_leak_filter_to_next_request(launcher):
    module, pipeline, _ = launcher

    def fail(*args):
        assert module.source_filter.get() == ["netflix.txt"]
        raise RuntimeError("Model unavailable")

    pipeline.answer_question = fail
    handler = module.FilteredRAGHandler()
    handler.path = "/answer"
    handler.read_json = lambda: {"source_ids": ["netflix.txt"]}
    handler.send_json = lambda status, body: setattr(handler, "sent", (status, body))
    handler.do_POST()
    assert handler.sent[0] == 500
    assert module.source_filter.get() is None


def test_other_paths_keep_shared_handler(launcher):
    module, _, _ = launcher
    handler = module.FilteredRAGHandler()
    handler.path = "/refresh"
    handler.do_POST()
    assert handler.sent == (200, "shared handler")
