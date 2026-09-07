from pathlib import Path

from core.collectors import (
    collect_database,
    collect_implementation,
    collect_architecture,
    collect_devops,
)


def load_prompt(
    app_dir: Path,
    mode: str
) -> str:

    prompt_path = (
        app_dir
        / "prompts"
        / f"{mode}.txt"
    )

    return prompt_path.read_text(
        encoding="utf-8"
    )


def collect_evidence(
    mode: str,
    repo_root: Path,
    student: str
) -> str:

    collectors = {
        "database": collect_database,
        "implementation": collect_implementation,
        "architecture": collect_architecture,
        "devops": collect_devops,
    }

    collector = collectors[mode]

    return collector(
        repo_root,
        student
    )


def run_agentic_review(
    mode: str,
    app_dir: Path,
    repo_root: Path,
    ai,
    student: str = "all",
    student_label: str = "All Students",
):
    print()
    print("======================================")
    print(f"REVIEW TARGET: {mode.upper()}")
    print(f"TARGET: {student_label}")
    print("======================================")

    # =====================================
    # PLAN
    # =====================================

    print()
    print("[PLAN]")

    print(
        f"Plan a {mode} review for "
        f"{student_label}."
    )

    review_prompt = load_prompt(
        app_dir,
        mode
    )

    # =====================================
    # ACT
    # =====================================

    print()
    print("[ACT]")

    print(
        f"Collecting {mode} evidence "
        f"for {student_label}..."
    )

    evidence = collect_evidence(
        mode,
        repo_root,
        student
    )

    full_prompt = f"""
{review_prompt}

========================================
REVIEW TARGET
========================================

{student_label}

========================================
PROJECT EVIDENCE
========================================

{evidence}
"""

    # =====================================
    # OBSERVE
    # =====================================

    print()
    print("[OBSERVE]")

    print(
        "Sending repository evidence "
        "to Ollama for review..."
    )

    result = ai.run(
        full_prompt
    )

    print(result)

    # =====================================
    # ADAPT
    # =====================================

    print()
    print("[ADAPT]")

    print(
        "Use the findings and recommendations "
        "to determine whether changes are required."
    )

    return result