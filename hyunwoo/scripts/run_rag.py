import os
import sys
import tempfile
from contextvars import ContextVar
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "rag-server"))

import rag_pipeline
import rag_http_server
from rag_http_server import RAGHandler, ThreadingHTTPServer


# Use the shared code and corpus with a local runtime index.
data_dir = Path(os.getenv("RAG_DATA_DIR", str(Path(tempfile.gettempdir()) / "asd-release1-rag")))
data_dir.mkdir(parents=True, exist_ok=True)
rag_pipeline.CHROMA_DIR = data_dir / "chroma"
rag_pipeline.CORPUS_JSON = data_dir / "corpus.jsonl"
rag_pipeline.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", rag_pipeline.OLLAMA_MODEL)
rag_pipeline.OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/generate"

# Keep a provider filter local to each request.
source_filter = ContextVar("source_filter", default=None)
shared_retrieve = rag_pipeline.retrieve_context


def retrieve_context(query, k=5, caller="student"):
    sources = source_filter.get()
    if sources is None:
        return shared_retrieve(query, k, caller)
    if not sources:
        return {"status": "success", "query": query, "k": k, "results": []}
    result = rag_pipeline.get_collection().query(
        query_embeddings=rag_pipeline.embed_texts([query]), n_results=k,
        where={"source_id": {"$in": sources}},
    )
    return {"status": "success", "query": query, "k": k, "results": [
        {"rank": index + 1, "chunk_id": chunk,
         "source_id": result["metadatas"][0][index]["source_id"],
         "text": result["documents"][0][index], "distance": result["distances"][0][index]}
        for index, chunk in enumerate(result["ids"][0])
    ]}


rag_pipeline.retrieve_context = retrieve_context
rag_http_server.retrieve_context = retrieve_context


class FilteredRAGHandler(RAGHandler):
    def do_POST(self):
        if self.path not in {"/retrieve", "/answer"}:
            return super().do_POST()
        try:
            payload = self.read_json()
            sources = payload.get("source_ids")
            if sources is not None and (
                not isinstance(sources, list) or len(sources) > 10
                or any(not isinstance(source, str) or not source.endswith(".txt")
                       or Path(source).name != source for source in sources)
            ):
                return self.send_json(400, {"status": "error", "error": "Invalid source filter."})
            token = source_filter.set(sources)
            try:
                action = retrieve_context if self.path == "/retrieve" else rag_pipeline.answer_question
                result = action(payload.get("query", ""), int(payload.get("k", 5)),
                                payload.get("caller", "student"))
            finally:
                source_filter.reset(token)
            self.send_json(200, result)
        except Exception as error:
            self.send_json(500, {"status": "error", "error": str(error)})


if __name__ == "__main__":
    print(rag_pipeline.refresh_corpus("hyunwoo-startup"), flush=True)
    print("Shared RAG server: http://127.0.0.1:5003", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 5003), FilteredRAGHandler).serve_forever()
