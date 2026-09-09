"""
test_config.py — pyproject.toml configuration loading.

Every function here is defined to return an empty set rather than raise: most
Swift repositories have no pyproject.toml at all, and a missing one must mean
"index everything", not "fail".
"""

from __future__ import annotations

from pathlib import Path

from swift_kg.config import load_exclude_dirs, load_include_dirs


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(body)
    return tmp_path


class TestLoadIncludeDirs:
    def test_reads_the_include_list(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\ninclude = ["Sources", "App"]\n')
        assert load_include_dirs(repo) == {"Sources", "App"}

    def test_strips_trailing_slashes(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\ninclude = ["Sources/"]\n')
        assert load_include_dirs(repo) == {"Sources"}

    def test_missing_pyproject_means_index_everything(self, tmp_path: Path) -> None:
        assert load_include_dirs(tmp_path) == set()

    def test_missing_section_means_index_everything(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[project]\nname = "app"\n')
        assert load_include_dirs(repo) == set()

    def test_malformed_toml_does_not_raise(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, "[tool.swiftkg\ninclude = broken")
        assert load_include_dirs(repo) == set()

    def test_wrong_type_is_ignored(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\ninclude = "Sources"\n')
        assert load_include_dirs(repo) == set()

    def test_non_string_entries_are_dropped(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\ninclude = ["Sources", 3]\n')
        assert load_include_dirs(repo) == {"Sources"}


class TestLoadExcludeDirs:
    def test_reads_the_exclude_list(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\nexclude = ["Vendor", "Generated"]\n')
        assert load_exclude_dirs(repo) == {"Vendor", "Generated"}

    def test_independent_of_include(self, tmp_path: Path) -> None:
        repo = _write(tmp_path, '[tool.swiftkg]\ninclude = ["Sources"]\n')
        assert load_exclude_dirs(repo) == set()
