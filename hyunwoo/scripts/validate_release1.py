import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description="Check the live Bills MCP and RAG integration.")
    parser.add_argument("--base-url", default="http://localhost:8041")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    evidence = {"captured_at": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url}

    def call(name, path, payload=None):
        response = requests.get(args.base_url + path, timeout=10) if payload is None else requests.post(
            args.base_url + path, json=payload, timeout=150
        )
        response.raise_for_status()
        body = response.json()
        evidence[name] = {"http_status": response.status_code, "request": payload, "response": body}
        print(f"{name}: HTTP {response.status_code}")
        return body

    health = call("health", "/health")
    assert health["status"] == "healthy"
    summary = call("summary", "/api/summary")
    mcp = call("mcp", "/api/bills/mcp", {})
    assert mcp["tool"] == "bill_summary"
    assert mcp["result"]["summary"] == summary
    assert len(mcp["result"]["bills"]) == health["bill_count"]

    rag = call("rag", "/api/bills/rag", {
        "query": "How are fortnightly bills converted to a monthly cost?", "k": 5,
    })
    assert rag["status"] == "success"
    assert rag["llm_called"] is True
    assert rag["citations"] and rag["confidence_category"] in {"High", "Medium"}
    assert any(item["source_id"] == "HyunWoo_bills_knowledge.txt" for item in rag["citations"])

    unknown = call("insufficient_context", "/api/bills/rag", {
        "query": "Who won the lunar football tournament?", "k": 5,
    })
    assert unknown["status"] == "insufficient_context"
    assert unknown["citations"] == [] and unknown["confidence_category"] == "Low"
    assert unknown["llm_called"] is False

    review = call("existing_ai_review", "/api/bills/review", {
        "review_date": "2026-09-01", "window_days": 30,
    })
    assert all(phase in review for phase in ("plan", "act", "observe", "adapt"))
    assert review["act"]["monthly_cost"] == summary["monthly_cost"]
    if review["act"]["active_bill_count"]:
        assert review["adapt"]["llm_called"] is True
    evidence["result"] = "passed"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence saved: {args.output}")
    print("Live health, summary, MCP, sourced RAG, insufficient context and AI review passed.")


if __name__ == "__main__":
    main()
