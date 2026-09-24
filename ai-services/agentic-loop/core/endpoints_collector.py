from pathlib import Path

from core.collectors import collect_implementation


def collect(repo_root: Path, student: str) -> str:
    return collect_implementation(repo_root, student)
