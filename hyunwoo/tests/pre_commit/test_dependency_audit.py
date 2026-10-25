import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_pip_audit_passes():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--strict",
            "--progress-spinner",
            "off",
            "--cache-dir",
            str(ROOT / "hyunwoo" / ".security-cache" / "pip-audit"),
            "-r",
            "hyunwoo/backend/requirements.txt",
            "-r",
            "hyunwoo/tests/requirements.txt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
