import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description="Capture Bills Multi-Agent evidence without deciding for you.")
    parser.add_argument("--base-url", default="http://localhost:8041")
    parser.add_argument("--review-date")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--run-id", help="Inspect an existing review instead of starting another.")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    if args.run_id:
        response = requests.get(
            f"{base_url}/api/bills/workflows/{args.run_id}", timeout=(5, 15),
        )
    else:
        response = requests.post(
            f"{base_url}/api/bills/workflows",
            json={"review_date": args.review_date, "window_days": args.window_days},
            timeout=(5, 210),
        )
    if not response.ok:
        try:
            problem = response.json()
        except ValueError:
            problem = {"error": "The backend returned an unreadable response."}
        failure = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "base_url": base_url,
            "http_status": response.status_code,
            "response": problem,
            "result": "failed",
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(f"HTTP {response.status_code}: {problem.get('error', 'Workflow request failed.')}")
        if problem.get("run_id"):
            print(f"Failed review saved: {problem['run_id']}")
        raise SystemExit(1)
    run = response.json()
    assert run["status"] in {"awaiting_human", "complete"}, run
    assert run["plan"] and run["work"] and run["review"]
    assert isinstance(run["review"]["risks"], list)
    assert isinstance(run["review"]["recommendations"], list)
    assert "cost_summary" in run["evidence"]

    saved_response = requests.get(
        f"{base_url}/api/bills/workflows/{run['run_id']}", timeout=(5, 15),
    )
    saved_response.raise_for_status()
    saved = saved_response.json()
    assert saved["run_id"] == run["run_id"]
    assert saved["evidence"] == run["evidence"]
    if args.require_complete:
        assert saved["status"] == "complete", "Record your human decision in the dashboard first."
    if saved["status"] == "complete":
        assert saved["human_review"]["decision"] in {"approve", "correct", "partial", "reject"}
    else:
        assert saved["human_review"] is None

    evidence = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "workflow": saved,
        "result": "complete" if saved["status"] == "complete" else "awaiting_human",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence saved: {args.output}")
    print(f"Review: {saved['run_id']}")
    print(f"Status: {saved['status']}")
    print("Agent mode: " + ("STUB — no model was called" if saved["stub"] else saved["model"]))
    if saved["status"] == "awaiting_human":
        print("Reopen this review in the dashboard and record your decision.")
    else:
        print(f"Human decision recorded: {saved['human_review']['decision']}")


if __name__ == "__main__":
    main()
