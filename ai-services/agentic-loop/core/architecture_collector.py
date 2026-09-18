from pathlib import Path

from core.collectors import collect_architecture


def collect(repo_root: Path, student: str) -> str:
    return collect_architecture(repo_root, student)
