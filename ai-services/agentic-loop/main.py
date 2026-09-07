from pathlib import Path

from core.ai_runner import AIRunner
from core.orchestrator import run_agentic_review


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


def print_main_menu():
    print()
    print("======================================")
    print("PERSONAL FINANCE ASSISTANT AI REVIEW")
    print("======================================")
    print("1. Review Database")
    print("2. Review Implementation")
    print("3. Review Microservices Architecture")
    print("4. Review DevOps Pipeline")
    print("5. Review Everything")
    print("0. Exit")
    print()


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
        "Implementation, Architecture and DevOps "
        "should be reviewed."
    )

    target = choose_student(
        "implementation"
    )

    if target is None:
        return

    student, student_label = target

    modes = (
        "database",
        "implementation",
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


def main():
    app_dir, repo_root = get_paths()

    ai = AIRunner()

    modes = {
        "1": "database",
        "2": "implementation",
        "3": "architecture",
        "4": "devops",
    }

    while True:
        print_main_menu()

        choice = input(
            "Choose a review target: "
        ).strip()

        # ----------------------------
        # EXIT
        # ----------------------------

        if choice == "0":
            print()
            print("Agentic loop closed.")
            break

        # ----------------------------
        # REVIEW EVERYTHING
        # ----------------------------

        if choice == "5":
            run_everything(
                app_dir,
                repo_root,
                ai
            )

            continue

        # ----------------------------
        # SINGLE REVIEW CATEGORY
        # ----------------------------

        mode = modes.get(choice)

        if not mode:
            print("Invalid selection.")
            continue

        run_single_review(
            mode,
            app_dir,
            repo_root,
            ai
        )


if __name__ == "__main__":
    main()