import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_detect_secrets_scan_passes():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--exclude-files",
            r"(^|/)(__pycache__|\.pytest_cache|\.venv|venv)/",
            "hyunwoo/backend",
            "hyunwoo/frontend",
            "hyunwoo/tests",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    findings = json.loads(result.stdout)
    assert findings["results"] == {}, (
        "Potential secrets detected: "
        + json.dumps(findings["results"], indent=2)
    )
