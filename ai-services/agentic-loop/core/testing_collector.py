from pathlib import Path

from core.testing_evidence import summarise_log
from core.review_file_collector import collect_files


def collect(repo_root: Path, student: str) -> str:
    repo_root = Path(repo_root).resolve()

    sections = []

    sections.append("=== TEST IMPLEMENTATION ===")
    sections.append(
        collect_files(
            repo_root,
            student,
            (
                "tests/**/*.py",
                "**/pytest.ini",
                "**/ruff.toml",
                "**/pyproject.toml",
            ),
        )
    )

    sections.append("=== CI/CD CONFIGURATION ===")
    sections.append(
        collect_files(
            repo_root,
            "all",
            (
                ".github/workflows/*.yml",
                ".github/workflows/*.yaml",
                ".pre-commit-config.yaml",
            ),
        )
    )

    sections.append("=== PRE-COMMIT TEST RESULTS ===")

    pre_commit_logs = sorted(
        repo_root.glob("*/tests/pre_commit/*.log")
    )

    if pre_commit_logs:
        for path in pre_commit_logs:
            sections.append(summarise_log(path))
    else:
        sections.append("No pre-commit execution logs found.")

    sections.append("=== POST-COMMIT CI/CD RESULTS ===")

    ci_dir = (
        repo_root
        / "ai-services"
        / "agentic-loop"
        / "evidence"
        / "post-commit"
    )

    ci_logs = (
        sorted(ci_dir.rglob("*.log"))
        + sorted(ci_dir.rglob("*.txt"))
        if ci_dir.is_dir()
        else []
    )

    if ci_logs:
        for path in ci_logs:
            sections.append(summarise_log(path))
    else:
        sections.append("No post-commit execution logs found.")

    return "\n\n".join(sections)