from pathlib import Path

from core import reporter
from core.ai_runner import AIRunner
from core.orchestrator import run_agentic_review, MODE_CONFIG
from core.mcp_pipeline import (
    run_mcp_review,
    run_boundary_analysis,
    run_tool_validation,
    run_mcp_integration_review,
)


# Folder names must match the repository exactly
STUDENTS = {
    "1": ("joshua", "Joshua"),
    "2": ("Maxwell", "Maxwell"),
    "3": ("Enerel", "Enerel"),
    "4": ("hyunwoo", "HyunWoo"),
    "5": ("Thomas", "Thomas"),
    "6": ("LeHoaLong", "Le Hoa Long"),
}


def get_paths():
    """
    Resolve the agentic-loop folder and repository root.

    Expected structure:

    Advanced-Software-Development/
    ├── ai-services/
    │   └── agentic-loop/
    │       └── app.py
    ├── Thomas/
    ├── Maxwell/
    └── docker-compose.yml
    """

    app_dir = Path(__file__).resolve().parent

    repo_root = app_dir.parent.parent

    return app_dir, repo_root


def _menu_choice_to_key(choice: str) -> str | None:
    return {
        "1": "db",
        "2": "endpoints",
        "3": "architecture",
        "4": "devops",
        "5": "mcp",
    }.get(choice)


def _print_mode_mapping(app_dir: Path) -> None:
    """Diagnostic: which real prompt files feed each mode. Not
    prompts/{family}/ folders -- this repo organises prompts by role
    (implementation/, review/), not by family, so this reads the actual
    paths out of MODE_CONFIG instead of a directory naming convention
    that doesn't exist here.
    """
    prompt_map = {
        config.label: ", ".join(
            str(app_dir / "prompts" / relative_path)
            for relative_path in (
                *config.implementation_prompts,
                *config.review_prompts,
            )
        )
        for config in MODE_CONFIG.values()
    }
    reporter.print_prompt_map(prompt_map)


def choose_student(mode):
    """
    Allow the user to choose one student's files
    or review the integrated team application.
    """

    while True:
        print()
        print("======================================")
        print("SELECT REVIEW TARGET")
        print("======================================")
        print("1. Joshua")
        print("2. Maxwell")
        print("3. Enerel")
        print("4. HyunWoo")
        print("5. Thomas")
        print("6. Le Hoa Long")

        if mode == "architecture":
            print("7. Integrated Team Application")
        elif mode == "mcp":
            print("7. Personal Finance Assistant")
        else:
            print("7. All Students")

        print("0. Back")
        print()

        choice = input(
            "Choose a review target: "
        ).strip()

        if choice == "0":
            return None

        if choice == "7":
            if mode == "architecture":
                return (
                    "all",
                    "Integrated Team Application"
                )

            if mode == "mcp":
                return (
                    "all",
                    "Personal Finance Assistant"
                )

            return (
                "all",
                "All Students"
            )

        student = STUDENTS.get(choice)

        if student:
            return student

        print("Invalid selection.")


def run_single_review(
    mode,
    app_dir,
    repo_root,
    ai
):
    """
    Ask which student/application should be reviewed,
    then execute the Plan -> Act -> Observe -> Adapt loop.
    """

    target = choose_student(mode)

    if target is None:
        return

    student, student_label = target

    run_agentic_review(
        mode=mode,
        app_dir=app_dir,
        repo_root=repo_root,
        ai=ai,
        student=student,
        student_label=student_label,
    )


def run_everything(
    app_dir,
    repo_root,
    ai
):
    """
    Run all four review categories.

    The user selects one target first so Review Everything
    does not automatically send the entire six-person
    repository to Ollama.
    """

    print()
    print("======================================")
    print("REVIEW EVERYTHING")
    print("======================================")
    print()
    print(
        "Select the student whose Database, "
        "Endpoints, Architecture and DevOps "
        "should be reviewed."
    )

    target = choose_student(
        "endpoints"
    )

    if target is None:
        return

    student, student_label = target

    modes = (
        "db",
        "endpoints",
        "architecture",
        "devops",
    )

    for mode in modes:
        run_agentic_review(
            mode=mode,
            app_dir=app_dir,
            repo_root=repo_root,
            ai=ai,
            student=student,
            student_label=student_label,
        )


def run_mcp_assistant(app_dir, ai):
    """Ask a finance question; Ollama picks one of the six MCP tools,
    Python calls it for real data, and the integration is validated
    against the evidence it actually returned.
    """
    print()
    print("======================================")
    print("MCP TOOL ASSISTANT")
    print("======================================")
    print(
        "Tools: portfolio_snapshot, glossary_lookup, document_search, "
        "bill_summary, transaction_summary, goal_progress"
    )
    print()

    user_request = input("Your question: ").strip()

    if not user_request:
        print("No question entered.")
        return

    result = run_mcp_review(user_request, app_dir, ai)

    print()
    print("======================================")
    print("MCP INTEGRATION REVIEW")
    print("======================================")
    print(result.get("integration_review", "(no tool was selected)"))


def run_mcp_tool_validation(app_dir, repo_root):
    """Automates tool validation: proves every documented MCP tool is both
    implemented and actually runnable, with no human clicking through the
    UI and no model call involved.
    """
    print()
    print("======================================")
    print("MCP TOOL VALIDATION")
    print("======================================")

    passed, message = run_tool_validation(app_dir, repo_root)

    print(f"Result: {'PASS' if passed else 'FAIL'}")
    print(message)
    print()
    print("Written to reports/mcp-evidence.md")


def run_mcp_integration_review_menu(app_dir, repo_root, ai):
    """Runs the model-facing half of MCP validation: the automated
    evidence (mcp_evidence.collect + boundary analysis) is fed to two
    Ollama calls -- an implementation assessment, then a review pass that
    cross-checks it against the same evidence.
    """
    print()
    print("======================================")
    print("MCP TOOL INTEGRATION REVIEW")
    print("======================================")

    result = run_mcp_integration_review(app_dir, repo_root, ai)

    print()
    print("======================================")
    print("REVIEW")
    print("======================================")
    print(result["review_output"])
    print()
    print("Written to reports/mcp-integration-review.md")


def run_mcp_boundary_analysis(app_dir):
    """No model call: confirms tool_selection_prompt.txt and
    core/mcp_collector.py's MCP_TOOLS registry actually agree.
    """
    print()
    print("======================================")
    print("MCP TOOL BOUNDARY ANALYSIS")
    print("======================================")

    analysis = run_boundary_analysis(app_dir)

    print(f"In sync: {', '.join(analysis['in_sync']) or '(none)'}")
    print(
        "Documented but not implemented: "
        f"{', '.join(analysis['documented_only']) or '(none)'}"
    )
    print(
        "Implemented but not documented: "
        f"{', '.join(analysis['implemented_only']) or '(none)'}"
    )
    print(f"Boundaries match: {analysis['boundaries_match']}")
    print()
    print("Written to reports/boundary-analysis.md")


def main():
    app_dir, repo_root = get_paths()

    ai = AIRunner()

    _print_mode_mapping(app_dir)

    while True:
        reporter.print_menu()

        choice = input(
            "Choose a review target: "
        ).strip()

        if choice == "0":
            print()
            print("Agentic loop closed.")
            break

        mode_key = _menu_choice_to_key(choice)

        if not mode_key:
            print("Invalid choice. Select 0, 1, 2, 3, 4, or 5.")
            continue

        run_single_review(
            mode_key,
            app_dir,
            repo_root,
            ai
        )


if __name__ == "__main__":
    main()