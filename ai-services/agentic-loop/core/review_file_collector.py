from pathlib import Path


MAX_FILE_CHARS = 12000
MAX_TOTAL_CHARS = 90000


def collect_files(repo_root, student, patterns):
    root = Path(repo_root).resolve()

    if student == "all":
        target = root
    else:
        target = (root / student).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Invalid student directory")

    if not target.is_dir():
        return f"Evidence target not found: {target}"

    output = []
    total = 0
    seen = set()

    for pattern in patterns:
        for path in sorted(target.glob(pattern)):
            if not path.is_file():
                continue

            resolved = path.resolve()

            if not resolved.is_relative_to(root):
                continue

            if resolved in seen:
                continue

            if any(
                part in {
                    ".git", "venv", ".venv",
                    "__pycache__", "node_modules"
                }
                for part in path.parts
            ):
                continue

            seen.add(resolved)

            try:
                content = path.read_text(
                    encoding="utf-8",
                    errors="replace"
                )
            except OSError as exc:
                output.append(f"Could not read {path}: {exc}")
                continue

            remaining = MAX_TOTAL_CHARS - total

            if remaining <= 0:
                output.append("Evidence collection truncated.")
                return "\n\n".join(output)

            content = content[:min(MAX_FILE_CHARS, remaining)]
            total += len(content)

            output.append(
                f"FILE: {path.relative_to(root)}\n"
                f"```\n{content}\n```"
            )

    if not output:
        return "No matching repository evidence found."

    return "\n\n".join(output)