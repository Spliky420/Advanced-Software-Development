import json
import os
import re
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import db
import embeddings
import library_qa
import llm
import mcp_client
import multi_agent_client
import rag_client
import retrieval
import summarize
import workflow_evidence
from db import DEFAULT_USER_ID
from validation import (
    ValidationError,
    validate_document_payload,
    validate_glossary_payload,
    validate_search_payload,
)

GLOSSARY_TOOL = "glossary_lookup"

# Friendly message per Multi-Agent failure, for the UI; the key is the code
# clients branch on. Codes after "error" are the server's own error codes.
MULTI_AGENT_FAILURES = {
    "disabled": (503, "Multi-agent mode is switched off on this server, so the research "
                      "brief cannot run. The rest of the library still works."),
    "unreachable": (503, "The Multi-Agent Server is not running. Start it on the host "
                         "(multi-agent-server/run.sh) and try again."),
    "timeout": (504, "The Multi-Agent Server is not responding. It may be busy, so try "
                     "again in a moment."),
    "error": (502, "The Multi-Agent Server sent a response this app could not read."),
    "validation_failed": (400, "The Multi-Agent Server rejected the request."),
    "not_found": (404, "That run no longer exists on the Multi-Agent Server (its history may "
                       "have been cleared). Start a new review."),
    "conflict": (409, "This run has already been reviewed (or failed), so it cannot be "
                      "reviewed again."),
    "agent_unavailable": (503, "The agents could not run. Check Ollama is running on the host, "
                               "or start the Multi-Agent Server with STUB_AGENTS=true."),
}

# The Multi-Agent Server's run ids are uuid4().hex. Anything else is refused
# before it is looked up or forwarded.
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


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

    # -----------------------------------------------------------------
    # Release 1 -- shared MCP and RAG servers (both run on the host, outside
    # Docker; see mcp_client.py / rag_client.py)
    # -----------------------------------------------------------------

    @app.get("/api/library/integrations")
    def integrations():
        """Configuration only -- no network call -- so the UI and CI can show
        whether each mode is switched on and where it points."""
        return jsonify({
            "mcp": {
                "enabled": mcp_client.mcp_enabled(),
                "server_url": mcp_client.server_url(),
                "allowed_tools": list(mcp_client.ALLOWED_TOOLS),
            },
            "rag": {
                "enabled": rag_client.rag_enabled(),
                "server_url": rag_client.server_url(),
            },
            "multi_agent": {
                "enabled": multi_agent_client.multi_agent_enabled(),
                "server_url": multi_agent_client.server_url(),
            },
        }), 200

    @app.post("/api/documents/<int:document_id>/glossary")
    def glossary_lookup(document_id):
        """Look up a term found in a document via the shared MCP server's
        glossary_lookup tool, which in turn reads Maxwell's glossary."""
        document = db.get_document(document_id, DEFAULT_USER_ID)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        try:
            clean = validate_glossary_payload(request.get_json(silent=True), document["body_text"])
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400

        tool_input = {"term": clean["lookup_term"]}
        try:
            result = mcp_client.call_tool(GLOSSARY_TOOL, tool_input)
        except mcp_client.MCPDisabledError as exc:
            return jsonify({"error": str(exc), "mcp_enabled": False}), 503
        except mcp_client.MCPUnavailableError as exc:
            return jsonify({"error": f"glossary lookup is unavailable: {exc}"}), 503

        # tools.py reports a backend failure as {"error": ...} rather than
        # raising. A 4xx from Maxwell's backend means "not in the glossary"
        # (unknown or non-financial term) -- a valid tool result, not an
        # outage. Anything else means the glossary itself could not answer.
        tool_error = result.get("error")
        if tool_error and "returned 4" not in tool_error:
            return jsonify({"error": f"glossary lookup failed: {tool_error}", "result": result}), 502

        found = not tool_error and isinstance(result.get("definition"), str)
        definition = result.get("definition") if found else None

        entry = db.create_ai_log(
            {
                "document_id": document_id,
                "created_at": _now(),
                "request_type": "mcp_glossary_lookup",
                "prompt_sent": clean["lookup_term"],
                "model_name": f"mcp:{GLOSSARY_TOOL}",
                "response_text": definition or tool_error,
            },
            DEFAULT_USER_ID,
        )

        return jsonify({
            "tool": GLOSSARY_TOOL,
            "mcp_server": mcp_client.server_url(),
            "input": tool_input,
            "document_id": document_id,
            "term": clean["term"],
            "found": found,
            "definition": definition,
            "message": None if found else f"'{clean['lookup_term']}' is not in the financial glossary.",
            "result": result,
            "ai_log_id": entry["id"],
        }), 200

    @app.post("/api/library/ask")
    def ask_library():
        """Grounded Q&A over the shared RAG server -- Plan -> Act -> Observe
        -> Adapt; see library_qa.py for why Observe gates the model call."""
        data = request.get_json(silent=True)
        question = data.get("question") if isinstance(data, dict) else None

        try:
            plan_result, act_result, observe_result, adapt_result = library_qa.ask(question)
        except library_qa.QuestionError as exc:
            return jsonify({"error": str(exc)}), 400
        except rag_client.RAGDisabledError as exc:
            return jsonify({"error": str(exc), "rag_enabled": False}), 503
        except rag_client.RAGUnavailableError as exc:
            return jsonify({"error": f"library Q&A is unavailable: {exc}"}), 503

        answered = adapt_result["status"] == "answered"
        citations = [
            {key: chunk[key] for key in ("source_id", "chunk_id", "matched_terms", "snippet")}
            for chunk in observe_result["citations"]
        ] if answered else []
        confidence = observe_result["confidence_category"] if answered else "Insufficient"

        entry = db.create_ai_log(
            {
                "document_id": None,
                "created_at": _now(),
                "request_type": "rag_ask",
                "prompt_sent": plan_result["question"],
                "model_name": "rag-server",
                "response_text": adapt_result["answer"],
            },
            DEFAULT_USER_ID,
        )

        return jsonify({
            "status": adapt_result["status"],
            "question": plan_result["question"],
            "answer": adapt_result["answer"],
            "confidence_category": confidence,
            "citations": citations,
            "plan": plan_result,
            "act": {
                "phase": act_result["phase"],
                "description": act_result["description"],
                "rag_server": act_result["rag_server"],
                "retrieved_count": len(act_result["chunks"]),
            },
            "observe": {
                key: value for key, value in observe_result.items()
                if key not in ("supporting_chunks", "citations")
            },
            "adapt": adapt_result,
            "ai_log_id": entry["id"],
        }), 200

    # -----------------------------------------------------------------
    # Release 2 -- shared Multi-Agent Server (runs on the host, outside
    # Docker; see multi_agent_client.py). Planner -> Worker -> Reviewer run
    # on the server; the human decision is made here, in the Research
    # Library UI, and forwarded.
    # -----------------------------------------------------------------

    def _multi_agent_error(exc, own_request=False):
        """A failed Multi-Agent Server call as (body, status): error is the
        message for people, code is for the UI to branch on, detail keeps
        the technical reason.

        own_request: True when this backend built the whole request body
        (starting a workflow), so a 400 from the server is this backend's
        fault, not the user's, and is reported as 502 rather than 400.
        """
        if isinstance(exc, multi_agent_client.MultiAgentDisabledError):
            return jsonify({
                "error": MULTI_AGENT_FAILURES["disabled"][1],
                "code": "disabled",
                "detail": str(exc),
                "multi_agent_enabled": False,
            }), 503

        code = exc.code if exc.code in MULTI_AGENT_FAILURES else "error"
        status, message = MULTI_AGENT_FAILURES[code]
        if code == "validation_failed" and own_request:
            status = 502
        body = {"error": message, "code": code, "detail": str(exc)}
        if isinstance(exc, multi_agent_client.MultiAgentRequestError):
            body["multi_agent"] = exc.body
            if exc.body.get("fields"):
                body["fields"] = exc.body["fields"]
        return jsonify(body), status

    def _owned_run(run_id):
        """The log row for a run this backend started for DEFAULT_USER_ID,
        or None -- so the API never proxies another feature's run."""
        if not RUN_ID_RE.match(run_id):
            return None
        return db.find_ai_log("multi_agent_workflow", run_id, DEFAULT_USER_ID)

    @app.post("/api/documents/<int:document_id>/multi-agent")
    def start_multi_agent_workflow(document_id):
        """Start a research-brief workflow on the shared Multi-Agent Server.
        Returns 202 at status 'planning'; poll GET /api/multi-agent/runs/<id>."""
        document = db.get_document(document_id, DEFAULT_USER_ID)
        if document is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        task = workflow_evidence.build_task(document)
        evidence = workflow_evidence.build_evidence(document)
        try:
            run = multi_agent_client.start_workflow(task, evidence)
        except (
            multi_agent_client.MultiAgentDisabledError,
            multi_agent_client.MultiAgentUnavailableError,
            multi_agent_client.MultiAgentRequestError,
        ) as exc:
            return _multi_agent_error(exc, own_request=True)

        entry = db.create_ai_log(
            {
                "document_id": document_id,
                "created_at": _now(),
                "request_type": "multi_agent_workflow",
                "prompt_sent": json.dumps({"task": task, "evidence": evidence}),
                "model_name": f"multi-agent:{run.get('model') or 'unknown'}",
                "response_text": run["run_id"],
            },
            DEFAULT_USER_ID,
        )

        return jsonify({
            **run,
            "document_id": document_id,
            "task": task,
            "evidence": evidence,
            "sent": workflow_evidence.sent_summary(document),
            "multi_agent_server": multi_agent_client.server_url(),
            "ai_log_id": entry["id"],
        }), 202

    @app.get("/api/multi-agent/runs/<run_id>")
    def get_multi_agent_run(run_id):
        owned = _owned_run(run_id)
        if owned is None:
            return jsonify({"error": f"workflow run {run_id} not found"}), 404

        try:
            run = multi_agent_client.get_workflow(run_id)
        except (
            multi_agent_client.MultiAgentDisabledError,
            multi_agent_client.MultiAgentUnavailableError,
            multi_agent_client.MultiAgentRequestError,
        ) as exc:
            return _multi_agent_error(exc)

        # The agents' raw output stays untouched in the Multi-Agent Server's
        # workflow history; only what is shown here has the loops removed.
        work, repeated = workflow_evidence.remove_repeated_lines(run.get("work"))
        return jsonify({
            **run,
            "work": work,
            "work_repeated_lines_removed": repeated,
            "document_id": owned["document_id"],
        }), 200

    @app.post("/api/multi-agent/runs/<run_id>/review")
    def review_multi_agent_run(run_id):
        """Human review: approve, correct, partially accept or reject."""
        owned = _owned_run(run_id)
        if owned is None:
            return jsonify({"error": f"workflow run {run_id} not found"}), 404

        try:
            review = workflow_evidence.validate_review_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400

        # The Worker's text is read from the server before deciding, so the
        # brief this backend keeps is exactly what the agents produced (or the
        # person's correction of it), never something the client sent as "work".
        try:
            run = multi_agent_client.get_workflow(run_id)
            result = multi_agent_client.review_workflow(run_id, review)
        except (
            multi_agent_client.MultiAgentDisabledError,
            multi_agent_client.MultiAgentUnavailableError,
            multi_agent_client.MultiAgentRequestError,
        ) as exc:
            return _multi_agent_error(exc)

        brief = workflow_evidence.accepted_brief(review, run.get("work") or "")
        decided_at = result.get("decided_at") or _now()
        entry = db.create_ai_log(
            {
                "document_id": owned["document_id"],
                "created_at": decided_at,
                "request_type": "multi_agent_review",
                "prompt_sent": run_id,
                "model_name": "human",
                "response_text": json.dumps({**review, "brief_text": brief}),
            },
            DEFAULT_USER_ID,
        )

        return jsonify({
            **result,
            "document_id": owned["document_id"],
            "brief_text": brief,
            "ai_log_id": entry["id"],
        }), 200

    @app.get("/api/documents/<int:document_id>/brief")
    def get_research_brief(document_id):
        """The latest research brief a person accepted for this document
        (approved, corrected or partially accepted). Read from the local log,
        so it shows even when the Multi-Agent Server is not running."""
        if db.get_document(document_id, DEFAULT_USER_ID) is None:
            return jsonify({"error": f"document {document_id} not found"}), 404

        for row in db.list_ai_logs(document_id, "multi_agent_review", DEFAULT_USER_ID):
            try:
                decision = json.loads(row["response_text"] or "")
            except ValueError:
                continue
            if isinstance(decision, dict) and decision.get("brief_text"):
                # Briefs saved before repeats were removed on save.
                decision["brief_text"] = workflow_evidence.remove_repeated_lines(decision["brief_text"])[0]
                return jsonify({
                    "document_id": document_id,
                    "run_id": row["prompt_sent"],
                    "decision": decision["decision"],
                    "note": decision.get("note") or "",
                    "brief_text": decision["brief_text"],
                    "takeaways": workflow_evidence.takeaways(decision["brief_text"]),
                    "decided_at": row["created_at"],
                }), 200

        return jsonify({"error": "no research brief has been accepted for this document yet"}), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
