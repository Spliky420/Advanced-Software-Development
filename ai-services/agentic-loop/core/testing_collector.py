from pathlib import Path

from core.review_file_collector import collect_files


def collect(repo_root: Path, student: str) -> str:
    """
    Collect testing evidence for a student or the whole team.
    """

    evidence = []

    # Student-specific testing evidence
    student_evidence = collect_files(
        repo_root,
        student,
        (
            "tests/**/*.py",
            "**/pytest.ini",
            "**/pyproject.toml",
            "**/ruff.toml",
            "**/requirements*.txt",
        ),
    )

    evidence.append("=== STUDENT TESTING EVIDENCE ===")
    evidence.append(student_evidence)

    # Shared CI/CD and pre-commit configuration
    shared_evidence = collect_files(
        repo_root,
        "all",
        (
            ".pre-commit-config.yaml",
            ".github/workflows/*ci*.yml",
            ".github/workflows/*ci*.yaml",
        ),
    )

    evidence.append("=== SHARED TESTING CONFIGURATION ===")
    evidence.append(shared_evidence)

    return "\n\n".join(evidence)