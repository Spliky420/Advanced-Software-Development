import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


SUPPORTED = [
    ("How do I cancel Netflix?", "HyunWoo_provider_Netflix_cancel.txt"),
    ("Where can I find my Netflix billing date?", "HyunWoo_provider_Netflix_billing.txt"),
    ("Why is the Netflix cancel option missing?", "HyunWoo_provider_Netflix_partner.txt"),
    ("Will I keep my Spotify playlists after cancelling?", "HyunWoo_provider_Spotify_cancel.txt"),
    ("What happens if I cancel a Spotify free trial?", "HyunWoo_provider_Spotify_trial.txt"),
    ("How can I change my Spotify billing date?", "HyunWoo_provider_Spotify_billing.txt"),
]
UNSUPPORTED = [
    "What is Netflix's current price in Australia?",
    "What is Spotify's student discount?",
    "What is Netflix's cancellation fee?",
]


def main():
    parser = argparse.ArgumentParser(description="Check the live provider RAG answers.")
    parser.add_argument("--base-url", default="http://localhost:8041")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = {"captured_at": datetime.now(timezone.utc).isoformat(), "checks": []}

    for query, source in SUPPORTED + [(query, None) for query in UNSUPPORTED]:
        response = requests.post(args.base_url + "/api/bills/rag", json={"query": query, "k": 5},
                                 timeout=(3, 150))
        response.raise_for_status()
        result = response.json()
        if source:
            assert result["status"] == "success", (query, result)
            assert result["llm_called"] is True
            assert any(item["source_id"] == source for item in result["citations"]), (query, result)
            assert all(item.get("source_url", "").startswith("https://")
                       and item.get("checked_on") == "2026-10-02" for item in result["citations"])
        else:
            assert result["status"] == "insufficient_context", (query, result)
            assert result["llm_called"] is False and result["citations"] == []
        evidence["checks"].append({"query": query, "http_status": response.status_code, "response": result})
        print(f"PASS: {query}", flush=True)

    evidence["result"] = "passed"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence saved: {args.output}")


if __name__ == "__main__":
    main()
