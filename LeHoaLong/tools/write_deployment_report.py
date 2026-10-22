"""Write docs/cloud/deployment-report.json for the deployed Goals and Budgeting.

The team deploys every feature to Azure Container Apps with
scripts/deploy/ and .github/workflows/cloud-deployment.yml. This records
what that deployment is for this feature, in the format the agentic loop's
cloud review mode reads (ai-services/agentic-loop/core/cloud_collector.py),
which then checks it live and asks for the release decision.

    python LeHoaLong/tools/write_deployment_report.py --domain <environment default domain>

The domain is the part after "lehoalong-frontend." in the URL the
deployment run prints in its summary.

Nothing here is typed in by hand except the domain:

- **commit and run**: the newest successful cloud-deployment run, from the
  GitHub API.
- **settings**: what lehoalong-backend actually runs with, resolved the way
  the container resolves it. The env list in 03-deploy-apps.sh comes first,
  then the backend Dockerfile's ENV default, then config.py's default, all
  read at the deployed commit. A switch the deployed code does not have is
  recorded as null, because setting it changes nothing.
- **services**: from `az containerapp show` when the Azure CLI is
  available; otherwise from the deployment run's "Update container apps"
  step, with the source recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

REPO = "Spliky420/Advanced-Software-Development"
WORKFLOW = "cloud-deployment.yml"
DEPLOY_SCRIPT = "scripts/deploy/03-deploy-apps.sh"
DEPLOY_CONFIG = "scripts/deploy/config.sh"
BACKEND_APP = "lehoalong-backend"
FRONTEND_APP = "lehoalong-frontend"
SWITCHES = ("AI_MODE_ENABLED", "MCP_ENABLED", "RAG_ENABLED", "MULTI_AGENT_ENABLED")

# Each AI service's own status endpoint, all reachable through the frontend.
AI_HEALTH = {
    "AI-Mode": "/health",
    "MCP": "/api/mcp/health",
    "RAG": "/api/rag/health",
    "Multi-Agent": "/api/agents/health",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "LeHoaLong" / "docs" / "cloud" / "deployment-report.json"


def git_show(sha: str, path: str) -> str | None:
    """A file at a commit, or None if it does not exist there."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell; sha comes from the GitHub API
        ["git", "show", f"{sha}:{path}"],  # noqa: S607 -- git from PATH, as every developer runs it
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def latest_successful_run() -> dict:
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"
    runs = requests.get(url, params={"status": "success", "per_page": 1}, timeout=15).json()["workflow_runs"]
    if not runs:
        raise SystemExit(f"{WORKFLOW} has no successful run yet.")
    run = runs[0]
    jobs = requests.get(f"{run['jobs_url']}?per_page=100", timeout=15).json()["jobs"]
    deploy = next((j for j in jobs if j["name"] == "deploy"), {})
    step = next((s for s in deploy.get("steps", []) if s["name"] == "Update container apps"), {})
    return {
        "id": run["id"],
        "url": run["html_url"],
        "sha": run["head_sha"],
        "branch": run["head_branch"],
        "finished_at": run["updated_at"],
        "update_step": step.get("conclusion"),
    }


# --------------------------------------------------------------------------
# What the backend actually runs with
# --------------------------------------------------------------------------


def deploy_env(script: str, config: str) -> dict[str, str]:
    """The KEY=VALUE env list 03-deploy-apps.sh gives lehoalong-backend."""
    block = re.search(rf"^deploy {BACKEND_APP} .*?(?=^\s*$)", script, re.M | re.S)
    if not block:
        raise SystemExit(f"{DEPLOY_SCRIPT} has no 'deploy {BACKEND_APP}' block at the deployed commit.")
    # Only the app's env, after the "--" that ends the init container's list.
    app_part = block.group(0).split(" -- ", 1)[-1]
    tokens = re.findall(r'"([A-Z_]+=[^"]*)"', app_part)
    if '"${NO_AI[@]}"' in app_part:
        no_ai = re.search(r"^NO_AI=\((.*)\)", script, re.M)
        tokens += re.findall(r'"([A-Z_]+=[^"]*)"', no_ai.group(1)) if no_ai else []
    env = dict(token.split("=", 1) for token in tokens)
    for key, value in env.items():
        variable = re.fullmatch(r"\$\{?(\w+)\}?", value)
        if variable:
            default = re.search(rf'^{variable.group(1)}="\$\{{{variable.group(1)}:-([^}}]*)\}}"', config, re.M)
            env[key] = default.group(1) if default else ""
    return env


def dockerfile_defaults(dockerfile: str) -> dict[str, str]:
    return dict(re.findall(r"\b([A-Z_]+)=(\S+)", "\n".join(
        line for line in dockerfile.splitlines() if not line.lstrip().startswith("#")
    )))


def config_default(config_py: str, switch: str) -> bool | None:
    """config.py's default for a switch, or None if the code has no such switch."""
    match = re.search(rf'_bool_env\("{switch}",\s*(True|False)\)', config_py)
    return None if not match else match.group(1) == "True"


def as_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def resolve_settings(env: dict, dockerfile: dict, config_py: str) -> dict:
    """Each switch's effective value, and where it came from."""
    settings, sources = {}, {}
    for switch in SWITCHES:
        if config_default(config_py, switch) is None:
            settings[switch], sources[switch] = None, "not a switch in the deployed code"
        elif switch in env:
            settings[switch], sources[switch] = as_bool(env[switch]), DEPLOY_SCRIPT
        elif switch in dockerfile:
            settings[switch], sources[switch] = as_bool(dockerfile[switch]), "backend Dockerfile ENV default"
        else:
            settings[switch], sources[switch] = config_default(config_py, switch), "config.py default"
    return {"settings": settings, "settings_source": sources}


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------


def services(resource_group: str, run: dict) -> list[dict]:
    az = shutil.which("az")
    if az:
        found = []
        for name in (FRONTEND_APP, BACKEND_APP):
            result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
                [az, "containerapp", "show", "-n", name, "-g", resource_group, "-o", "json"],
                capture_output=True, text=True, check=False,
            )
            props = json.loads(result.stdout).get("properties", {}) if result.returncode == 0 else {}
            found.append({"name": name, "kind": "containerapp",
                          "state": props.get("runningStatus") or props.get("provisioningState") or "not found",
                          "state_source": "az containerapp show"})
        found.append({"name": "lehoalong-database", "kind": f"init container in {BACKEND_APP}",
                      "state": found[1]["state"], "state_source": "runs inside the backend's replica"})
        return found
    state = "Succeeded" if run["update_step"] == "success" else str(run["update_step"])
    source = f"deployment run {run['id']}, step 'Update container apps' (Azure CLI not available here)"
    return [
        {"name": FRONTEND_APP, "kind": "containerapp", "state": state, "state_source": source},
        {"name": BACKEND_APP, "kind": "containerapp", "state": state, "state_source": source},
        {"name": "lehoalong-database", "kind": f"init container in {BACKEND_APP}", "state": state,
         "state_source": source},
    ]


def build_report(domain: str, resource_group: str, region: str, run: dict, today: date) -> dict:
    sha = run["sha"]
    script, config = git_show(sha, DEPLOY_SCRIPT), git_show(sha, DEPLOY_CONFIG)
    dockerfile = git_show(sha, "LeHoaLong/backend/Dockerfile") or ""
    config_py = git_show(sha, "LeHoaLong/backend/config.py") or ""
    if script is None or config is None:
        raise SystemExit(f"Commit {sha[:7]} is not available locally: run `git fetch origin` first.")
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": sha[:7],
        "deployment_run": run["url"],
        "deployed_from_branch": run["branch"],
        "deployed_at": run["finished_at"],
        "profile": "baseline",
        "resource_group": resource_group,
        "region": region,
        "frontend_url": f"https://{FRONTEND_APP}.{domain}",
        "backend_ingress": "internal",
        "backend_public_probe": f"https://{BACKEND_APP}.{domain}",
        "services": services(resource_group, run),
        **resolve_settings(deploy_env(script, config), dockerfile_defaults(dockerfile), config_py),
        "ai_health": AI_HEALTH,
        "crud_smoke": {
            "collection": "/api/goals",
            "id_field": "goal_id",
            "create": {
                "name": "Release check -- safe to delete",
                "target_amount": 100,
                "target_date": (today + timedelta(days=365)).isoformat(),
                "priority": "low",
            },
            "update": {"name": "Release check (updated) -- safe to delete"},
        },
        "data_note": "SQLite is seeded by an init container onto an EmptyDir volume: data resets "
                     "to the seed whenever the backend replica restarts (scripts/deploy/README.md).",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--domain", required=True, help="the Container Apps environment's default domain")
    parser.add_argument("--resource-group", default="rg-asd2026", help="default matches scripts/deploy/config.sh")
    parser.add_argument("--region", default="australiaeast", help="default matches scripts/deploy/config.sh")
    args = parser.parse_args()

    domain = args.domain.removeprefix("https://").removeprefix(f"{FRONTEND_APP}.").strip("/")
    report = build_report(domain, args.resource_group, args.region, latest_successful_run(), date.today())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} for run {report['deployment_run']}")
    for switch, value in report["settings"].items():
        print(f"  {switch:20} {value!s:5}  ({report['settings_source'][switch]})")


if __name__ == "__main__":
    main()
