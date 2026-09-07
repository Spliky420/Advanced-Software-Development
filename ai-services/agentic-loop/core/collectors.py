from pathlib import Path

import yaml


STUDENT_FOLDERS = [
    "joshua",
    "Maxwell",
    "Enerel",
    "hyunwoo",
    "Thomas",
    "LeHoaLong",
]


SERVICE_PREFIXES = {
    "joshua": "joshua",
    "Maxwell": "maxwell",
    "Enerel": "enerel",
    "hyunwoo": "hyunwoo",
    "Thomas": "thomas",
    "LeHoaLong": "lehoalong",
}


def read_file(
    path: Path,
    max_chars: int = 12000
) -> str:
    """
    Read a text file safely.

    Large files are truncated so small local LLMs
    are not overloaded with excessive prompt content.
    """

    if not path.exists():
        return f"FILE NOT FOUND: {path}"

    try:
        content = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        if len(content) > max_chars:
            return (
                content[:max_chars]
                + "\n\n[FILE TRUNCATED FOR AI REVIEW]"
            )

        return content

    except Exception as error:
        return f"ERROR READING {path}: {error}"


# ============================================================
# DATABASE REVIEW
# ============================================================

def collect_single_database(
    repo_root: Path,
    student: str
) -> str:

    database_dir = (
        repo_root
        / student
        / "database"
    )

    return f"""
========================================
DATABASE REVIEW TARGET
========================================

Student: {student}

----------------------------------------
Dockerfile
----------------------------------------

{read_file(database_dir / "Dockerfile")}

----------------------------------------
init.sql
----------------------------------------

{read_file(database_dir / "init.sql")}

----------------------------------------
seed.sql
----------------------------------------

{read_file(database_dir / "seed.sql")}

----------------------------------------
entrypoint.sh
----------------------------------------

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


# ============================================================
# IMPLEMENTATION REVIEW
# ============================================================

def collect_single_implementation(
    repo_root: Path,
    student: str
) -> str:

    backend_file = (
        repo_root
        / student
        / "backend"
        / "app.py"
    )

    frontend_file = (
        repo_root
        / student
        / "frontend"
        / "app.py"
    )

    return f"""
========================================
IMPLEMENTATION REVIEW TARGET
========================================

Student: {student}

----------------------------------------
Backend app.py
----------------------------------------

{read_file(
    backend_file,
    max_chars=16000
)}

----------------------------------------
Frontend app.py
----------------------------------------

{read_file(
    frontend_file,
    max_chars=12000
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


# ============================================================
# ARCHITECTURE REVIEW
# ============================================================

def load_compose(
    repo_root: Path
) -> dict:
    """
    Load docker-compose.yml as structured YAML.
    """

    compose_path = (
        repo_root
        / "docker-compose.yml"
    )

    if not compose_path.exists():
        return {}

    try:
        content = compose_path.read_text(
            encoding="utf-8"
        )

        data = yaml.safe_load(
            content
        )

        if not isinstance(data, dict):
            return {}

        return data

    except Exception:
        return {}


def collect_architecture(
    repo_root: Path,
    student: str
) -> str:

    compose_data = load_compose(
        repo_root
    )

    if not compose_data:
        return (
            "ERROR: docker-compose.yml could "
            "not be loaded or parsed."
        )

    services = compose_data.get(
        "services",
        {}
    )

    volumes = compose_data.get(
        "volumes",
        {}
    )

    networks = compose_data.get(
        "networks",
        {}
    )

    # --------------------------------------------------------
    # INTEGRATED TEAM ARCHITECTURE
    # --------------------------------------------------------

    if student == "all":

        architecture_data = {
            "services": services,
        }

        if volumes:
            architecture_data[
                "volumes"
            ] = volumes

        if networks:
            architecture_data[
                "networks"
            ] = networks

        return f"""
========================================
INTEGRATED RELEASE 0 ARCHITECTURE
========================================

Review target:
Integrated Team Application

----------------------------------------
docker-compose.yml architecture
----------------------------------------

{yaml.safe_dump(
    architecture_data,
    sort_keys=False,
    default_flow_style=False
)}
"""

    # --------------------------------------------------------
    # INDIVIDUAL STUDENT ARCHITECTURE
    # --------------------------------------------------------

    prefix = SERVICE_PREFIXES.get(
        student
    )

    if not prefix:
        return (
            f"ERROR: No Docker service prefix "
            f"is configured for {student}."
        )

    selected_services = {}

    for (
        service_name,
        service_config
    ) in services.items():

        lower_name = service_name.lower()

        if (
            lower_name.startswith(
                prefix.lower()
            )
            or service_name == "ollama"
        ):
            selected_services[
                service_name
            ] = service_config

    selected_volumes = {}

    for (
        volume_name,
        volume_config
    ) in volumes.items():

        lower_volume = (
            volume_name.lower()
        )

        if (
            prefix.lower()
            in lower_volume
            or volume_name
            == "ollama-models"
        ):
            selected_volumes[
                volume_name
            ] = volume_config

    architecture_data = {
        "services": selected_services,
    }

    if selected_volumes:
        architecture_data[
            "volumes"
        ] = selected_volumes

    frontend_dockerfile = (
        repo_root
        / student
        / "frontend"
        / "Dockerfile"
    )

    backend_dockerfile = (
        repo_root
        / student
        / "backend"
        / "Dockerfile"
    )

    database_dockerfile = (
        repo_root
        / student
        / "database"
        / "Dockerfile"
    )

    return f"""
========================================
ARCHITECTURE REVIEW TARGET
========================================

Student: {student}

----------------------------------------
Selected Docker Compose Services
----------------------------------------

{yaml.safe_dump(
    architecture_data,
    sort_keys=False,
    default_flow_style=False
)}

----------------------------------------
Frontend Dockerfile
----------------------------------------

{read_file(
    frontend_dockerfile,
    max_chars=6000
)}

----------------------------------------
Backend Dockerfile
----------------------------------------

{read_file(
    backend_dockerfile,
    max_chars=6000
)}

----------------------------------------
Database Dockerfile
----------------------------------------

{read_file(
    database_dockerfile,
    max_chars=6000
)}
"""


# ============================================================
# DEVOPS REVIEW
# ============================================================

def get_workflow_files(
    repo_root: Path
) -> list[Path]:

    workflow_dir = (
        repo_root
        / ".github"
        / "workflows"
    )

    if not workflow_dir.exists():
        return []

    workflows = list(
        workflow_dir.glob("*.yml")
    )

    workflows.extend(
        workflow_dir.glob("*.yaml")
    )

    return sorted(
        workflows
    )


def collect_single_devops(
    repo_root: Path,
    student: str
) -> str:

    workflows = get_workflow_files(
        repo_root
    )

    matches = []

    student_lower = (
        student.lower()
    )

    prefix = SERVICE_PREFIXES.get(
        student,
        student
    ).lower()

    for workflow in workflows:

        content = read_file(
            workflow,
            max_chars=12000
        )

        workflow_name = (
            workflow.name.lower()
        )

        if (
            student_lower
            in workflow_name
            or prefix
            in workflow_name
            or student_lower
            in content.lower()
            or prefix
            in content.lower()
        ):
            matches.append(
                f"""
========================================
WORKFLOW: {workflow.name}
========================================

{content}
"""
            )

    if not matches:
        return f"""
========================================
DEVOPS REVIEW TARGET
========================================

Student: {student}

No matching GitHub Actions workflow
could be automatically identified.
"""

    return f"""
========================================
DEVOPS REVIEW TARGET
========================================

Student: {student}

{''.join(matches)}
"""


def collect_devops(
    repo_root: Path,
    student: str
) -> str:

    if student != "all":
        return collect_single_devops(
            repo_root,
            student
        )

    workflows = get_workflow_files(
        repo_root
    )

    evidence = []

    for workflow in workflows:
        evidence.append(
            f"""
========================================
WORKFLOW: {workflow.name}
========================================

{read_file(
    workflow,
    max_chars=12000
)}
"""
        )

    if not evidence:
        return (
            "No GitHub Actions workflows "
            "were found."
        )

    return "\n".join(
        evidence
    )