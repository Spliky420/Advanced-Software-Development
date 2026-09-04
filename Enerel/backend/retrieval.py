"""RAG retrieval: Plan -> Act -> Observe.

Used both by POST /api/documents/search directly, and (per the feature spec)
as the retrieval primitive other services can call over the compose network
to pull relevant document chunks for their own use.

This loop has no ADAPT phase and never asks the model to write anything: the
job here is retrieval, not narration, so there is nothing for the model to
adapt. The one model call in the whole loop is embedding the query text in
ACT -- a vector lookup, not text generation -- after which everything is
pure-Python cosine similarity and ranking. That keeps the same guarantee the
rest of the codebase relies on: the model never performs arithmetic, and
every score returned traces back to a Python computation over vectors the
model produced.
"""

import math

import db
import llm

DEFAULT_TOP_K = 5
MIN_SIMILARITY_SCORE = 0.0  # cosine similarity floor; negative scores are noise, not signal


def plan(query, top_k=None):
    """PLAN: decide how many results to return and with which embedding model."""
    return {
        "phase": "plan",
        "description": (
            "Read the search query and decide how many chunks to return and "
            "which embedding model to score them with."
        ),
        "query": query,
        "top_k": top_k if top_k is not None else DEFAULT_TOP_K,
        "embedding_model": llm.OLLAMA_EMBED_MODEL,
    }


def _cosine_similarity(a, b):
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def act(plan_result, candidate_chunks, embed_fn=None):
    """ACT: embed the query, then score every candidate chunk against it.

    candidate_chunks: db.list_all_embeddings(user_id) output -- one dict per
    stored chunk, each already carrying its own embedding_vector.
    """
    embed = embed_fn if embed_fn is not None else llm.embed
    query_vector, model_name = embed(plan_result["query"])

    scored = []
    for chunk in candidate_chunks:
        score = _cosine_similarity(query_vector, chunk["embedding_vector"])
        scored.append({**chunk, "score": score})

    return {
        "phase": "act",
        "description": (
            "Embed the query and compute cosine similarity, in Python, "
            "between the query vector and every stored chunk vector."
        ),
        "model_name": model_name,
        "scored_chunks": scored,
    }


def observe(act_result, top_k):
    """OBSERVE: rank by score, drop noise, keep the top_k."""
    ranked = sorted(act_result["scored_chunks"], key=lambda c: c["score"], reverse=True)
    ranked = [c for c in ranked if c["score"] > MIN_SIMILARITY_SCORE]
    top = ranked[:top_k]

    results = [
        {
            "document_id": c["document_id"],
            "title": c["title"],
            "source": c["source"],
            "doc_type": c["doc_type"],
            "published_on": c["published_on"],
            "chunk_index": c["chunk_index"],
            "chunk_text": c["chunk_text"],
            "score": round(c["score"], 4),
        }
        for c in top
    ]

    return {
        "phase": "observe",
        "description": "Rank scored chunks and keep the top_k most relevant.",
        "result_count": len(results),
        "results": results,
    }


def search(query, user_id, top_k=None, embed_fn=None, list_embeddings_fn=None):
    """Run the full Plan -> Act -> Observe loop and return everything, so an
    HTTP handler can expose each phase the way joshua/backend/app.py exposes
    drift.py's phases.
    """
    list_embeddings = list_embeddings_fn if list_embeddings_fn is not None else db.list_all_embeddings

    plan_result = plan(query, top_k)
    candidates = list_embeddings(user_id)
    act_result = act(plan_result, candidates, embed_fn=embed_fn)
    observe_result = observe(act_result, plan_result["top_k"])

    return plan_result, act_result, observe_result
