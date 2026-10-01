import asyncio
import json
import os
import re

import httpx
import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8071/mcp")
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:5003").rstrip("/")
MCP_TIMEOUT = 25
RAG_TIMEOUT = 130


class ServiceError(RuntimeError):
    pass


def enabled(mode):
    return os.getenv(f"{mode}_ENABLED", "true").lower() in {"true", "1", "yes"}


# Call only the shared bills tool.
async def _call_bill_tool():
    async with httpx.AsyncClient(timeout=MCP_TIMEOUT) as http_client:
        async with streamable_http_client(
            MCP_SERVER_URL, http_client=http_client
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await session.call_tool("bill_summary", arguments={})


async def _timed_bill_tool():
    return await asyncio.wait_for(_call_bill_tool(), timeout=MCP_TIMEOUT)


def bill_tool():
    if not enabled("MCP"):
        raise ServiceError("MCP mode is disabled in this environment.")

    try:
        result = asyncio.run(_timed_bill_tool())
    except Exception as error:
        raise ServiceError("Could not reach the shared MCP server.") from error

    if result.isError:
        raise ServiceError("The shared MCP bills tool could not complete the request.")

    data = result.structuredContent
    if data is None:
        for block in result.content:
            if block.type == "text":
                try:
                    data = json.loads(block.text)
                    break
                except ValueError:
                    continue

    if not isinstance(data, dict) or data.get("error"):
        raise ServiceError("The shared MCP bills tool returned an error.")
    if not isinstance(data.get("bills"), list) or not isinstance(data.get("summary"), dict):
        raise ServiceError("The shared MCP bills tool returned an invalid result.")

    summary = data["summary"]
    for key in ("active_bill_count", "auto_renew_count", "monthly_cost", "annual_cost"):
        if not isinstance(summary.get(key), (int, float)):
            raise ServiceError("The shared MCP bills tool returned an invalid summary.")

    return {"status": "success", "tool": "bill_summary", "result": data}


def _rag_request(path, payload):
    try:
        response = requests.post(
            f"{RAG_SERVER_URL}{path}", json=payload,
            timeout=15 if path == "/retrieve" else RAG_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as error:
        raise ServiceError("Could not complete the request to the shared RAG server.") from error
    if not isinstance(result, dict) or result.get("status") == "error":
        raise ServiceError("The shared RAG server returned an invalid response.")
    return result


STOP_WORDS = set(
    "a an the what which how why when where who is are does do can could should "
    "would will i my me we our you your it its this that these those to of in on "
    "for from with about and or please explain tell get have has be much".split()
)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP_WORDS


def insufficient(query, contexts):
    return {
        "status": "insufficient_context",
        "query": query,
        "answer": "There is not enough relevant source information to answer this question.",
        "citations": [],
        "confidence_category": "Low",
        "retrieval_summary": {"retrieved_count": len(contexts)},
        "llm_called": False,
    }


# Check for relevant sources before asking for an answer.
def rag_answer(query, k):
    if not enabled("RAG"):
        raise ServiceError("RAG mode is disabled in this environment.")

    payload = {"query": query, "k": k, "caller": "hyunwoo"}
    retrieval = _rag_request("/retrieve", payload)
    contexts = retrieval.get("results")
    if not isinstance(contexts, list):
        raise ServiceError("The shared RAG server returned invalid retrieval results.")

    terms = _words(query)
    relevant = {}
    for context in contexts:
        if not isinstance(context, dict):
            continue
        text = context.get("text")
        source = context.get("source_id")
        chunk = context.get("chunk_id")
        if not all(isinstance(value, str) and value for value in (text, source, chunk)):
            continue
        overlap = terms & _words(text)
        # This is a relevance check, not a probability of correctness.
        coverage = len(overlap) / len(terms) if terms else 0
        if coverage >= 0.5 and len(overlap) >= min(2, len(terms)) and terms:
            relevant[(source, chunk)] = {**context, "coverage": coverage}

    if not relevant:
        return insufficient(query, contexts)

    result = _rag_request("/answer", payload)
    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ServiceError("The shared RAG server returned an empty answer.")
    if result.get("status") == "insufficient_context" or re.search(
        r"insufficient (evidence|context)|not enough (evidence|context)|cannot answer",
        answer, re.IGNORECASE,
    ):
        output = insufficient(query, contexts)
        output["llm_called"] = True
        return output

    # Keep citations that refer to the sources actually retrieved.
    citations = result.get("citations")
    if not isinstance(citations, list) or not citations:
        raise ServiceError("The shared RAG answer did not include source citations.")
    retrieved_keys = {
        (item.get("source_id"), item.get("chunk_id"))
        for item in contexts if isinstance(item, dict)
        and isinstance(item.get("source_id"), str)
        and isinstance(item.get("chunk_id"), str)
    }
    verified = []
    for citation in citations:
        if not isinstance(citation, dict):
            raise ServiceError("The shared RAG answer returned an invalid citation.")
        key = (citation.get("source_id"), citation.get("chunk_id"))
        if not all(isinstance(value, str) for value in key) or key not in retrieved_keys:
            raise ServiceError("The shared RAG answer cited a source that was not retrieved.")
        if key in relevant:
            verified.append({
                "source_id": key[0], "chunk_id": key[1],
                "excerpt": relevant[key]["text"],
            })

    if not verified:
        output = insufficient(query, contexts)
        output["llm_called"] = True
        return output
    confidence = "High" if any(
        relevant[(item["source_id"], item["chunk_id"])]["coverage"] == 1
        for item in verified
    ) else "Medium"

    # Quote the source if numerical wording cannot be matched to it.
    source_text = "\n\n".join(item["excerpt"] for item in verified)
    normalised_answer = " ".join(answer.lower().split())
    normalised_source = " ".join(source_text.lower().split())
    source_fallback = bool(re.search(r"\d", answer)) and normalised_answer not in normalised_source
    if source_fallback:
        answer = "The retrieved reference states:\n\n" + source_text

    return {
        "status": "success", "query": query, "answer": answer.strip(),
        "citations": verified, "confidence_category": confidence,
        "confidence_basis": "Question terms covered by the cited source excerpts; not a probability.",
        "retrieval_summary": {"retrieved_count": len(contexts), "relevant_count": len(relevant)},
        "llm_called": True,
        "source_excerpt_fallback_used": source_fallback,
    }
