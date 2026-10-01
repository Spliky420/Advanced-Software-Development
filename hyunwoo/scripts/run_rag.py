import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "rag-server"))

import rag_pipeline
from rag_http_server import RAGHandler, ThreadingHTTPServer


# Use the shared code and corpus with a local runtime index.
data_dir = Path(os.getenv("RAG_DATA_DIR", str(Path(tempfile.gettempdir()) / "asd-release1-rag")))
data_dir.mkdir(parents=True, exist_ok=True)
rag_pipeline.CHROMA_DIR = data_dir / "chroma"
rag_pipeline.CORPUS_JSON = data_dir / "corpus.jsonl"
rag_pipeline.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", rag_pipeline.OLLAMA_MODEL)
rag_pipeline.OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/generate"

if __name__ == "__main__":
    print(rag_pipeline.refresh_corpus("hyunwoo-startup"), flush=True)
    print("Shared RAG server: http://127.0.0.1:5003", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 5003), RAGHandler).serve_forever()
