from pathlib import Path
import re


KEYWORDS = re.compile(
    r"passed|failed|failure|error|warning|"
    r"vulnerabilit|ruff|pip.audit|detect.secrets|"
    r"pytest|test session|exit code|"
    r"process completed|conclusion",
    re.IGNORECASE,
)


def summarise_log(path: Path, max_lines=100):
    if not path.is_file():
        return f"Missing evidence: {path}"

    lines = path.read_text(
        encoding="utf-8",
        errors="replace"
    ).splitlines()

    matches = [
        line for line in lines
        if KEYWORDS.search(line)
    ]

    if not matches:
        return f"No testing results identified in {path.name}"

    selected = matches[-max_lines:]

    return (
        f"LOG: {path.name}\n"
        f"Matched lines: {len(matches)}\n"
        f"Selected evidence:\n"
        + "\n".join(selected)
    )