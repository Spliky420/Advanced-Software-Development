from core.review_file_collector import collect_files


def collect(repo_root, student):
    return collect_files(
        repo_root,
        student,
        (
            "**/*agent*.py",
            "**/*orchestrat*.py",
            "**/*multi_agent*.py",
        ),
    )