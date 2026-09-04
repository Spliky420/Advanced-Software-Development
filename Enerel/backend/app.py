import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import db
import embeddings
import llm
import retrieval
import summarize
from db import DEFAULT_USER_ID
from validation import ValidationError, validate_document_payload, validate_search_payload


def _now():
    return datetime.now(timezone.utc).isoformat()


def _index_document(document_id, body_text):
    """Run indexing and never let a model-unavailable failure bubble up to
    the caller -- create/update must succeed regardless of Ollama's state.
    """
    return embeddings.index_document(document_id, body_text)


def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception as exc:
            return jsonify({"status": "error", "database": "unreachable", "detail": str(exc)}), 503
        return jsonify({"status": "ok", "database": "reachable"}), 200

    # -----------------------------------------------------------------
    # documents
    # -----------------------------------------------------------------

    @app.get("/api/documents")
    def list_documents():
        filters = {
            "q": request.args.get("q"),
            "doc_type": request.args.get("doc_type"),
            "date_from": request.args.get("date_from"),
            "date_to": request.args.get("date_to"),
        }
        return jsonify(db.list_documents(DEFAULT_USER_ID, filters)), 200

    @app.get("/api/documents/<int:document_id>")
    def get_document(document_id):
        document = db.get_document(document_id, DEFAULT_USER_ID)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404
        return jsonify(document), 200

    @app.post("/api/documents")
    def create_document():
        try:
            clean = validate_document_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400

        now = _now()
        document = db.create_document(clean, DEFAULT_USER_ID, now)
        indexing = _index_document(document["id"], clean["body_text"])
        return jsonify({**document, "indexing": indexing}), 201

    @app.put("/api/documents/<int:document_id>")
    def update_document(document_id):
        try:
            clean = validate_document_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400

        now = _now()
        document = db.update_document(document_id, clean, DEFAULT_USER_ID, now)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        indexing = _index_document(document_id, clean["body_text"])
        return jsonify({**document, "indexing": indexing}), 200

    @app.delete("/api/documents/<int:document_id>")
    def delete_document(document_id):
        if not db.delete_document(document_id, DEFAULT_USER_ID):
            return jsonify({"error": f"document {document_id} not found"}), 404
        return "", 204

    # -----------------------------------------------------------------
    # summarization -- Plan -> Act -> Observe -> Adapt
    # -----------------------------------------------------------------

    @app.post("/api/documents/<int:document_id>/summarize")
    def create_summary(document_id):
        document = db.get_document(document_id, DEFAULT_USER_ID)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        plan_result, act_result, observe_result, adapt_result = None, None, None, None
        try:
            plan_result, act_result, observe_result, adapt_result = summarize.summarize_document(
                document["body_text"]
            )
        except llm.LLMUnavailableError as exc:
            return jsonify({"error": f"summarization is unavailable: {exc}"}), 503

        now = _now()
        updated = db.store_summary(
            document_id,
            DEFAULT_USER_ID,
            adapt_result["summary_text"],
            adapt_result["key_points"],
            adapt_result["model_name"],
            now,
        )

        ai_log_id = None
        if adapt_result["llm_called"]:
            entry = db.create_ai_log(
                {
                    "document_id": document_id,
                    "created_at": now,
                    "request_type": "summarize",
                    "prompt_sent": adapt_result["prompt_sent"],
                    "model_name": adapt_result["model_name"],
                    "response_text": adapt_result["summary_text"],
                },
                DEFAULT_USER_ID,
            )
            ai_log_id = entry["id"]

        return jsonify({
            "plan": plan_result,
            "act": {
                "phase": act_result["phase"],
                "description": act_result["description"],
                "strategy": act_result["strategy"],
                "segment_count": act_result["segment_count"],
                "truncated": act_result["truncated"],
            },
            "observe": {
                "phase": observe_result["phase"],
                "description": observe_result["description"],
                "needs_reduce": observe_result["needs_reduce"],
            },
            "adapt": {
                "phase": adapt_result["phase"],
                "description": adapt_result["description"],
                "llm_called": adapt_result["llm_called"],
                "llm_call_count": adapt_result["llm_call_count"],
                "model_name": adapt_result["model_name"],
                "summary_text": adapt_result["summary_text"],
                "key_points": adapt_result["key_points"],
            },
            "document": updated,
            "ai_log_id": ai_log_id,
        }), 201

    @app.get("/api/documents/<int:document_id>/summary")
    def get_summary(document_id):
        document = db.get_document(document_id, DEFAULT_USER_ID)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        return jsonify({
            "document_id": document_id,
            "summarized": document["summary_text"] is not None,
            "summary_text": document["summary_text"],
            "key_points": document["key_points"],
            "model_name": document["summary_model"],
            "summarized_at": document["summarized_at"],
        }), 200

    # -----------------------------------------------------------------
    # RAG retrieval -- Plan -> Act -> Observe (no Adapt; see retrieval.py)
    # -----------------------------------------------------------------

    @app.post("/api/documents/search")
    def search_documents():
        try:
            clean = validate_search_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400

        try:
            plan_result, act_result, observe_result = retrieval.search(
                clean["query"], DEFAULT_USER_ID, top_k=clean["top_k"]
            )
        except llm.LLMUnavailableError as exc:
            return jsonify({"error": f"search is unavailable: {exc}"}), 503

        now = _now()
        db.create_ai_log(
            {
                "document_id": None,
                "created_at": now,
                "request_type": "search",
                "prompt_sent": clean["query"],
                "model_name": act_result["model_name"],
                "response_text": f"{observe_result['result_count']} chunk(s) returned",
            },
            DEFAULT_USER_ID,
        )

        return jsonify({
            "plan": plan_result,
            "act": {
                "phase": act_result["phase"],
                "description": act_result["description"],
                "model_name": act_result["model_name"],
                "candidates_scored": len(act_result["scored_chunks"]),
            },
            "observe": observe_result,
        }), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
