from pathlib import Path

from core.collectors import collect_database


def collect(repo_root: Path, student: str) -> str:
    return collect_database(repo_root, student)
