from pathlib import Path

from core.collectors import collect_devops


def collect(repo_root: Path, student: str) -> str:
    return collect_devops(repo_root, student)
