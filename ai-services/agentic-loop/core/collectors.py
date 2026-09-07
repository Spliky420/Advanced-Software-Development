from pathlib import Path


STUDENT_FOLDERS = [
    "joshua",
    "Maxwell",
    "Enerel",
    "hyunwoo",
    "Thomas",
    "LeHoaLong",
]


def read_file(path: Path) -> str:
    if not path.exists():
        return f"FILE NOT FOUND: {path}"

    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace"
        )

    except Exception as error:
        return f"ERROR READING {path}: {error}"


def collect_single_database(
    repo_root: Path,
    student: str
) -> str:

    database_dir = repo_root / student / "database"

    return f"""
========================================
{student.upper()} DATABASE
========================================

--- Dockerfile ---
{read_file(database_dir / "Dockerfile")}

--- init.sql ---
{read_file(database_dir / "init.sql")}

--- seed.sql ---
{read_file(database_dir / "seed.sql")}

--- entrypoint.sh ---
{read_file(database_dir / "entrypoint.sh")}
"""


def collect_database(
    repo_root: Path,
    student: str
) -> str:

    if student != "all":
        return collect_single_database(
            repo_root,
            student
        )

    evidence = []

    for folder in STUDENT_FOLDERS:
        evidence.append(
            collect_single_database(
                repo_root,
                folder
            )
        )

    return "\n".join(evidence)


def collect_single_implementation(
    repo_root: Path,
    student: str
) -> str:

    return f"""
========================================
{student.upper()} IMPLEMENTATION
========================================

--- Backend app.py ---
{read_file(
    repo_root
    / student
    / "backend"
    / "app.py"
)}

--- Frontend app.py ---
{read_file(
    repo_root
    / student
    / "frontend"
    / "app.py"
)}
"""


def collect_implementation(
    repo_root: Path,
    student: str
) -> str:

    if student != "all":
        return collect_single_implementation(
            repo_root,
            student
        )

    evidence = []

    for folder in STUDENT_FOLDERS:
        evidence.append(
            collect_single_implementation(
                repo_root,
                folder
            )
        )

    return "\n".join(evidence)


def collect_architecture(
    repo_root: Path,
    student: str
) -> str:

    return f"""
========================================
INTEGRATED MICROSERVICES ARCHITECTURE
========================================

--- docker-compose.yml ---
{read_file(
    repo_root
    / "docker-compose.yml"
)}

--- README.md ---
{read_file(
    repo_root
    / "README.md"
)}
"""


def collect_single_devops(
    repo_root: Path,
    student: str
) -> str:

    workflow_dir = (
        repo_root
        / ".github"
        / "workflows"
    )

    evidence = []

    if workflow_dir.exists():

        for workflow in workflow_dir.glob("*.yml"):

            content = read_file(workflow)

            # Only include workflows mentioning this student
            if student.lower() in content.lower():
                evidence.append(
                    f"""
========================================
WORKFLOW: {workflow.name}
========================================

{content}
"""
                )

    if not evidence:
        return (
            f"No workflow could be automatically "
            f"identified for {student}."
        )

    return "\n".join(evidence)


def collect_devops(
    repo_root: Path,
    student: str
) -> str:

    if student != "all":
        return collect_single_devops(
            repo_root,
            student
        )

    workflow_dir = (
        repo_root
        / ".github"
        / "workflows"
    )

    evidence = []

    if workflow_dir.exists():

        for workflow in workflow_dir.glob("*.yml"):

            evidence.append(
                f"""
========================================
WORKFLOW: {workflow.name}
========================================

{read_file(workflow)}
"""
            )

    return "\n".join(evidence)