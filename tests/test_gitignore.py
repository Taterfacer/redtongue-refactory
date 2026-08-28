"""Regression tests for the repository's ignore rules."""

from pathlib import Path
import subprocess
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def is_ignored(path: str) -> bool:
    """Return whether Git's configured rules ignore a repository-relative path."""
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "--", path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed with status {result.returncode}")
    return result.returncode == 0


class GitIgnoreTests(unittest.TestCase):
    def test_compiled_python_files_are_ignored_at_any_depth(self) -> None:
        """Verify that compiled Python files and cache contents are ignored at every directory depth."""
        ignored_paths = (
            "module.pyc",
            "package/module.pyc",
            "package/__pycache__/module.cpython-312.pyc",
            "package/__pycache__/metadata.txt",
        )

        for path in ignored_paths:
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path))

    def test_log_files_and_log_directories_are_ignored(self) -> None:
        ignored_paths = (
            "application.log",
            "var/application.log",
            "logs/application.txt",
            "services/logs/archive/application.txt",
        )

        for path in ignored_paths:
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path))

    def test_similarly_named_source_paths_remain_visible(self) -> None:
        visible_paths = (
            "module.py",
            "module.pyc.tmp",
            "logs.md",
            "logs-archive/application.txt",
        )

        for path in visible_paths:
            with self.subTest(path=path):
                self.assertFalse(is_ignored(path))

    def test_removed_exclusions_no_longer_hide_project_state(self) -> None:
        visible_paths = (
            ".red_tongue_index/index.json",
            ".env",
            ".env.local",
            "development.env.example",
        )

        for path in visible_paths:
            with self.subTest(path=path):
                self.assertFalse(is_ignored(path))


if __name__ == "__main__":
    unittest.main()
