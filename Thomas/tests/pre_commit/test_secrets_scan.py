
import json
import subprocess
import sys


def test_detect_secrets_scan_passes():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--exclude-files",
            r"(^|/)(venv|\.venv|__pycache__)/",
            "Thomas/backend",
            "Thomas/frontend",
            "Thomas/tests",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    findings = json.loads(result.stdout)

    assert findings.get("results", {}) == {}, (
        "Potential secrets detected: " + json.dumps(findings["results"], indent=2)
    )
