
import subprocess
import sys


def test_ruff_scan_passes():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "S",
            "--output-format=concise",
            "Thomas/backend",
            "Thomas/frontend",
            "Thomas/tests",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
