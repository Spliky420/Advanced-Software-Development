from pathlib import Path


def collect(repo_root: Path, student: str) -> str:
    """
    Collect repository evidence for a student's RAG integration.

    Evidence is collected from:
    - the selected student's feature
    - the shared local RAG server
    - docker-compose.yml

    This collector only gathers evidence. The agentic review model
    determines whether the integration passes or fails.
    """

    sections = []

    # -------------------------------------
    # Student feature
    # -------------------------------------

    student_dir = repo_root / student

    sections.append(
        f"RAG EVIDENCE FOR: {student}\n"
        f"Student directory: {student_dir}"
    )

    if student_dir.exists():
        student_evidence = []

        interesting_terms = (
            "rag",
            "rag_server",
            "rag_server_url",
            "/answer",
            "/retrieve",
            "/refresh",
            "confidence",
            "citation",
            "host.docker.internal:5003",
        )

        for path in student_dir.rglob("*"):
            if not path.is_file():
                continue

            # Only inspect useful text/source files
            if path.suffix.lower() not in {
                ".py", ".js", ".ts", ".html",
                ".yml", ".yaml", ".json",
                ".md", ".txt"
            }:
                continue

            try:
                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )
            except Exception:
                continue

            matches = []

            for line_number, line in enumerate(
                text.splitlines(),
                start=1
            ):
                if any(
                    term.lower() in line.lower()
                    for term in interesting_terms
                ):
                    matches.append(
                        f"{line_number}: {line.strip()}"
                    )

            if matches:
                relative = path.relative_to(repo_root)

                student_evidence.append(
                    f"\nFILE: {relative}\n"
                    + "\n".join(matches[:30])
                )

        if student_evidence:
            sections.append(
                "\nSTUDENT RAG INTEGRATION:\n"
                + "\n".join(student_evidence)
            )
        else:
            sections.append(
                "\nSTUDENT RAG INTEGRATION:\n"
                "No RAG-related evidence found."
            )

    else:
        sections.append(
            "\nStudent directory does not exist."
        )

    # -------------------------------------
    # Shared RAG server
    # -------------------------------------

    possible_rag_dirs = [
        repo_root / "rag-server",
        repo_root / "ai-services" / "rag-server",
    ]

    rag_dir = next(
        (path for path in possible_rag_dirs if path.exists()),
        None
    )

    if rag_dir:
        rag_files = []

        for path in rag_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {
                ".py", ".json", ".md", ".txt"
            }:
                rag_files.append(
                    str(path.relative_to(repo_root))
                )

        sections.append(
            "\nSHARED RAG SERVER:\n"
            f"Directory: {rag_dir.relative_to(repo_root)}\n"
            "Files:\n"
            + "\n".join(rag_files[:50])
        )

    else:
        sections.append(
            "\nSHARED RAG SERVER:\n"
            "No shared RAG server directory found."
        )

    # -------------------------------------
    # Docker Compose evidence
    # -------------------------------------

    compose_file = repo_root / "docker-compose.yml"

    if compose_file.exists():
        try:
            compose_text = compose_file.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            compose_matches = []

            for line_number, line in enumerate(
                compose_text.splitlines(),
                start=1
            ):
                if (
                    "rag" in line.lower()
                    or "5003" in line
                ):
                    compose_matches.append(
                        f"{line_number}: {line.strip()}"
                    )

            sections.append(
                "\nDOCKER COMPOSE RAG EVIDENCE:\n"
                + (
                    "\n".join(compose_matches)
                    if compose_matches
                    else "No RAG-related Docker Compose entries found."
                )
            )

        except Exception as exc:
            sections.append(
                f"\nCould not inspect docker-compose.yml: {exc}"
            )

    return "\n\n".join(sections)