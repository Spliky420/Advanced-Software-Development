import pytest

from retrieval import _cosine_similarity, act, observe, plan, search


def make_chunk(document_id, chunk_index, vector, **overrides):
    chunk = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "chunk_text": f"chunk {chunk_index} of document {document_id}",
        "embedding_vector": vector,
        "title": f"Document {document_id}",
        "source": "Test Source",
        "doc_type": "article",
        "published_on": "2026-01-01",
    }
    chunk.update(overrides)
    return chunk


class StubEmbed:
    def __init__(self, vector, model_name="stub-embed-model"):
        self.vector = vector
        self.model_name = model_name
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return self.vector, self.model_name


# --------------------------------------------------------------------------
# cosine similarity
# --------------------------------------------------------------------------

def test_cosine_similarity_of_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_of_opposite_vectors_is_negative_one():
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_handles_zero_vector_without_dividing_by_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_mismatched_length_returns_zero():
    assert _cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


# --------------------------------------------------------------------------
# PLAN / ACT / OBSERVE
# --------------------------------------------------------------------------

def test_plan_defaults_top_k_to_5():
    result = plan("inflation outlook")

    assert result["phase"] == "plan"
    assert result["top_k"] == 5
    assert result["query"] == "inflation outlook"


def test_plan_honours_explicit_top_k():
    result = plan("inflation outlook", top_k=2)

    assert result["top_k"] == 2


def test_act_scores_every_candidate_against_the_query_vector():
    plan_result = plan("query")
    candidates = [
        make_chunk(1, 0, [1.0, 0.0]),
        make_chunk(2, 0, [0.0, 1.0]),
    ]
    stub = StubEmbed([1.0, 0.0])

    act_result = act(plan_result, candidates, embed_fn=stub)

    assert act_result["phase"] == "act"
    assert act_result["model_name"] == "stub-embed-model"
    assert len(act_result["scored_chunks"]) == 2
    scores = {c["document_id"]: c["score"] for c in act_result["scored_chunks"]}
    assert scores[1] == pytest.approx(1.0)
    assert scores[2] == pytest.approx(0.0)


def test_observe_ranks_by_score_and_respects_top_k():
    act_result = {
        "scored_chunks": [
            {**make_chunk(1, 0, []), "score": 0.2},
            {**make_chunk(2, 0, []), "score": 0.9},
            {**make_chunk(3, 0, []), "score": 0.5},
        ]
    }

    observe_result = observe(act_result, top_k=2)

    assert observe_result["result_count"] == 2
    assert [r["document_id"] for r in observe_result["results"]] == [2, 3]


def test_observe_drops_non_positive_scores():
    act_result = {
        "scored_chunks": [
            {**make_chunk(1, 0, []), "score": -0.1},
            {**make_chunk(2, 0, []), "score": 0.0},
            {**make_chunk(3, 0, []), "score": 0.4},
        ]
    }

    observe_result = observe(act_result, top_k=5)

    assert observe_result["result_count"] == 1
    assert observe_result["results"][0]["document_id"] == 3


def test_search_runs_the_full_plan_act_observe_loop():
    stub = StubEmbed([1.0, 0.0])
    candidates = [make_chunk(1, 0, [1.0, 0.0]), make_chunk(2, 0, [0.0, 1.0])]

    plan_result, act_result, observe_result = search(
        "query", user_id=1, top_k=1, embed_fn=stub, list_embeddings_fn=lambda user_id: candidates
    )

    assert plan_result["phase"] == "plan"
    assert act_result["phase"] == "act"
    assert observe_result["phase"] == "observe"
    assert observe_result["result_count"] == 1
    assert observe_result["results"][0]["document_id"] == 1
