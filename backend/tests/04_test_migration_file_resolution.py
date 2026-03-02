#!/usr/bin/env python3
"""
验证迁移文件路径解析逻辑，兼容 Linux 下大小写敏感文件系统。
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.migration_files import resolve_migration_file


def test_falls_back_to_lowercase_filename():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        migrations_dir = root / "migrations"
        migrations_dir.mkdir(parents=True, exist_ok=True)

        lower_file = migrations_dir / "alexmanus.sql"
        lower_file.write_text("-- test", encoding="utf-8")

        resolved = resolve_migration_file(root)
        assert resolved == lower_file, f"Expected {lower_file}, got {resolved}"


def test_prefers_exact_filename_when_both_exist():
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        migrations_dir = root / "migrations"
        migrations_dir.mkdir(parents=True, exist_ok=True)

        exact_file = migrations_dir / "AlexManus.sql"
        lower_file = migrations_dir / "alexmanus.sql"
        exact_file.write_text("-- exact", encoding="utf-8")
        lower_file.write_text("-- lower", encoding="utf-8")

        resolved = resolve_migration_file(root)
        assert resolved == exact_file, f"Expected {exact_file}, got {resolved}"


def main():
    test_falls_back_to_lowercase_filename()
    test_prefers_exact_filename_when_both_exist()
    print("PASS: migration file resolution tests")


if __name__ == "__main__":
    main()
