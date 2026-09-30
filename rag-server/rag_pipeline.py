import json
import hashlib
from pathlib import Path

import chromadb
import requests


BASE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BASE_DIR / "corpus"
CHROMA_DIR = BASE_DIR / "chroma"
CORPUS_JSON = CORPUS_DIR / "corpus.jsonl"

COLLECTION_NAME = "personal_finance_context"
EMBED_SIZE = 256

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:0.5b"

_collection = None


def chunk_text(text, max_words=80):
    words = text.split()

    return [
        " ".join(words[i:i + max_words])
        for i in range(0, len(words), max_words)
        if words[i:i + max_words]
    ]


def embed_texts(texts):
    vectors = []

    for text in texts:
        vector = [0.0] * EMBED_SIZE

        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()

            for i, byte in enumerate(digest):
                vector[i % EMBED_SIZE] += (byte / 255.0) - 0.5

        norm = sum(x * x for x in vector) ** 0.5

        if norm:
            vector = [x / norm for x in vector]

        vectors.append(vector)

    return vectors


def get_collection():
    global _collection

    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))

        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME
        )

    return _collection


def refresh_corpus(caller="student"):
    global _collection

    chunks = []

    for file in CORPUS_DIR.glob("*.txt"):

        text = file.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        for number, chunk in enumerate(chunk_text(text), start=1):

            chunks.append({
                "chunk_id": f"{file.stem}_{number}",
                "source_id": file.name,
                "text": chunk
            })

    CORPUS_JSON.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with CORPUS_JSON.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR)
    )

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    _collection = client.get_or_create_collection(
        name=COLLECTION_NAME
    )

    if chunks:

        _collection.add(
            ids=[c["chunk_id"] for c in chunks],

            documents=[
                c["text"] for c in chunks
            ],

            metadatas=[
                {"source_id": c["source_id"]}
                for c in chunks
            ],

            embeddings=embed_texts(
                [c["text"] for c in chunks]
            )
        )

    return {
        "status": "success",
        "caller": caller,
        "chunk_count": len(chunks),
        "collection": COLLECTION_NAME
    }


def retrieve_context(query, k=5, caller="student"):

    collection = get_collection()

    if collection.count() == 0:
        refresh_corpus("auto_refresh")

    results = collection.query(
        query_embeddings=embed_texts([query]),
        n_results=k
    )

    retrieved = []

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadata = results["metadatas"][0]
    distances = results["distances"][0]

    for i in range(len(ids)):

        retrieved.append({
            "rank": i + 1,
            "chunk_id": ids[i],
            "source_id": metadata[i]["source_id"],
            "text": documents[i],
            "distance": distances[i]
        })

    return {
        "status": "success",
        "query": query,
        "k": k,
        "results": retrieved
    }


def answer_question(query, k=5, caller="student"):

    retrieval = retrieve_context(
        query,
        k,
        caller
    )

    results = retrieval["results"]

    context = "\n\n".join(
        result["text"]
        for result in results
    )

    prompt = f"""
You are the Personal Finance Assistant.

Answer the QUESTION using ONLY facts explicitly stated in the
RETRIEVED CONTEXT.

Rules:
- Do not use outside knowledge.
- Do not infer relationships that the context does not explicitly state.
- Do not treat nearby sentences as related unless the context says they are.
- Do not invent examples.
- If the context does not contain enough evidence, respond exactly:
  Insufficient evidence.
- Keep the answer concise and factual.

QUESTION:
{query}

RETRIEVED CONTEXT:
{context}

ANSWER:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    response.raise_for_status()

    answer = response.json().get(
        "response",
        "Insufficient evidence."
    )

    citations = [
        {
            "chunk_id": result["chunk_id"],
            "source_id": result["source_id"]
        }
        for result in results
    ]

    confidence = "High" if len(results) >= 3 else "Medium"

    return {
        "status": "success",
        "query": query,
        "answer": answer,
        "citations": citations,
        "confidence_category": confidence,
        "retrieval_summary": {
            "k": k,
            "retrieved_count": len(results)
        }
    }