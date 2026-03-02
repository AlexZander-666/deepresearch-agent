from pathlib import Path


def resolve_migration_file(project_root: Path) -> Path:
    """
    Resolve migration file path with filename case fallback for Linux.

    Preference order:
    1. migrations/AlexManus.sql
    2. migrations/alexmanus.sql
    """
    candidates = [
        project_root / "migrations" / "AlexManus.sql",
        project_root / "migrations" / "alexmanus.sql",
    ]

    for file_path in candidates:
        if file_path.exists():
            return file_path

    candidate_list = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"迁移文件不存在，候选路径: {candidate_list}")
