from pathlib import Path

from core.ai_runner import AIRunner
from core.orchestrator import run_agentic_review


STUDENTS = {
    "1": ("joshua", "Joshua"),
    "2": ("Maxwell", "Maxwell"),
    "3": ("Enerel", "Enerel"),
    "4": ("hyunwoo", "HyunWoo"),
    "5": ("Thomas", "Thomas"),
    "6": ("LeHoaLong", "Le Hoa Long"),
}


def get_paths():
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


def choose_student():
    while True:
        print()
        print("======================================")
        print("SELECT STUDENT")
        print("======================================")

        print("1. Joshua")
        print("2. Maxwell")
        print("3. Enerel")
        print("4. HyunWoo")
        print("5. Thomas")
        print("6. Le Hoa Long")
        print("7. All Students")
        print("0. Back")

        choice = input(
            "Choose a student: "
        ).strip()

        if choice == "0":
            return None

        if choice == "7":
            return ("all", "All Students")

        student = STUDENTS.get(choice)

        if student:
            return student

        print("Invalid selection.")


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

        if choice == "0":
            print("Agentic loop closed.")
            break

        if choice == "5":
            print()
            print("Running complete project review...")

            for mode in (
                "database",
                "implementation",
                "architecture",
                "devops",
            ):
                run_agentic_review(
                    mode=mode,
                    app_dir=app_dir,
                    repo_root=repo_root,
                    ai=ai,
                    student="all",
                    student_label="All Students",
                )

            continue

        mode = modes.get(choice)

        if not mode:
            print("Invalid selection.")
            continue

        # Architecture is primarily a group-level review
        if mode == "architecture":
            run_agentic_review(
                mode=mode,
                app_dir=app_dir,
                repo_root=repo_root,
                ai=ai,
                student="all",
                student_label="Integrated Team Application",
            )

            continue

        student_choice = choose_student()

        if student_choice is None:
            continue

        student, student_label = student_choice

        run_agentic_review(
            mode=mode,
            app_dir=app_dir,
            repo_root=repo_root,
            ai=ai,
            student=student,
            student_label=student_label,
        )


if __name__ == "__main__":
    main()