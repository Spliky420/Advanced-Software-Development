import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_ruff_scan_passes():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--select",
            "S",
            "--output-format=concise",
            "hyunwoo/backend",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
