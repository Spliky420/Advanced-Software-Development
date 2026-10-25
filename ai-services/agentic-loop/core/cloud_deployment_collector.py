from core.review_file_collector import collect_files


def collect(repo_root, student):
    return collect_files(
        repo_root,
        student,
        (
            "**/Dockerfile",
            "**/Dockerfile.*",
            "**/docker-compose*.yml",
            "**/docker-compose*.yaml",
            "**/.dockerignore",
        ),
    )