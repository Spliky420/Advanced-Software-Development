"""tools/write_deployment_report.py: resolving what the deployed backend runs with.

Fixture text stands in for the files at the deployed commit, so no git,
network or Azure is needed.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import write_deployment_report as tool  # noqa: E402

CONFIG_SH = 'AI_MODE_ENABLED="${AI_MODE_ENABLED:-false}"\n'

SCRIPT = """NO_AI=( "AI_MODE_ENABLED=$AI_MODE_ENABLED" "OLLAMA_BASE_URL=" "MCP_SERVER_URL=" "RAG_SERVER_URL=" )

deploy hyunwoo-backend 5000 external 1 1 \\
  --db hyunwoo-database /entrypoint.sh "DB_FILE=/data/bills.db" -- \\
  "MCP_ENABLED=false" "RAG_ENABLED=false" "${NO_AI[@]}"

deploy lehoalong-backend 5000 internal 1 1 \\
  --db lehoalong-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/goals.db" "INIT_DB_FORCE=0" -- \\
  "DB_PATH=/data/goals.db" "OLLAMA_MODEL=qwen2.5:0.5b" "${NO_AI[@]}"

deploy joshua-frontend 80 external 0 1 --
"""

DOCKERFILE = """# MCP_ENABLED=false in a comment must not count
ENV DB_PATH=/data/goals.db \\
    AI_MODE_ENABLED=true \\
    MULTI_AGENT_ENABLED=true \\
    MCP_ENABLED=true \\
    RAG_ENABLED=true
"""

RELEASE_2_CONFIG = "\n".join(f'    {s} = _bool_env("{s}", True)' for s in tool.SWITCHES)
RELEASE_1_CONFIG = '    MCP_ENABLED = _bool_env("MCP_ENABLED", True)\n    RAG_ENABLED = _bool_env("RAG_ENABLED", True)'


def test_only_this_feature_s_env_is_read_including_the_shared_no_ai_list():
    env = tool.deploy_env(SCRIPT, CONFIG_SH)
    assert env["DB_PATH"] == "/data/goals.db"
    assert env["AI_MODE_ENABLED"] == "false"  # $AI_MODE_ENABLED resolved from config.sh's default
    assert env["MCP_SERVER_URL"] == ""
    assert "MCP_ENABLED" not in env  # HyunWoo's line sets it; ours does not
    assert "DB_FILE" not in env  # the init container's env, not the app's


def test_switches_left_unset_fall_back_to_the_dockerfile_default():
    result = tool.resolve_settings(tool.deploy_env(SCRIPT, CONFIG_SH), tool.dockerfile_defaults(DOCKERFILE),
                                   RELEASE_2_CONFIG)
    assert result["settings"] == {
        "AI_MODE_ENABLED": False, "MCP_ENABLED": True, "RAG_ENABLED": True, "MULTI_AGENT_ENABLED": True,
    }
    assert result["settings_source"]["MCP_ENABLED"] == "backend Dockerfile ENV default"


def test_a_switch_the_deployed_code_does_not_have_is_recorded_as_null():
    # Release 1 has no AI_MODE_ENABLED: setting it in the deploy script changes nothing.
    result = tool.resolve_settings(tool.deploy_env(SCRIPT, CONFIG_SH), {}, RELEASE_1_CONFIG)
    assert result["settings"]["AI_MODE_ENABLED"] is None
    assert result["settings"]["MULTI_AGENT_ENABLED"] is None
    assert result["settings"]["MCP_ENABLED"] is True  # config.py default


def test_the_deploy_script_wins_once_it_sets_the_switches():
    script = SCRIPT.replace(
        '"OLLAMA_MODEL=qwen2.5:0.5b" "${NO_AI[@]}"',
        '"OLLAMA_MODEL=qwen2.5:0.5b" \\\n'
        '  "MCP_ENABLED=false" "RAG_ENABLED=false" "MULTI_AGENT_ENABLED=false" "${NO_AI[@]}"',
    )
    result = tool.resolve_settings(tool.deploy_env(script, CONFIG_SH), tool.dockerfile_defaults(DOCKERFILE),
                                   RELEASE_2_CONFIG)
    assert set(result["settings"].values()) == {False}


def test_the_report_names_an_internal_backend_and_a_future_dated_smoke_goal(monkeypatch):
    files = {tool.DEPLOY_SCRIPT: SCRIPT, tool.DEPLOY_CONFIG: CONFIG_SH,
             "LeHoaLong/backend/Dockerfile": DOCKERFILE, "LeHoaLong/backend/config.py": RELEASE_2_CONFIG}
    monkeypatch.setattr(tool, "git_show", lambda sha, path: files.get(path))
    monkeypatch.setattr(tool.shutil, "which", lambda name: None)
    run = {"id": 1, "url": "u", "sha": "d2dff07abc", "branch": "main", "finished_at": "t", "update_step": "success"}
    report = tool.build_report("x.australiaeast.azurecontainerapps.io", "rg", "australiaeast", run, date(2026, 10, 23))
    assert report["frontend_url"] == "https://lehoalong-frontend.x.australiaeast.azurecontainerapps.io"
    assert report["backend_ingress"] == "internal" and "backend_url" not in report
    assert report["crud_smoke"]["create"]["target_date"] == "2027-10-23"
    assert {s["state"] for s in report["services"]} == {"Succeeded"}
    assert "Azure CLI not available" in report["services"][0]["state_source"]
