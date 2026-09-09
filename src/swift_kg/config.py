"""
config.py — Configuration utilities for SwiftKG.

Reads include/exclude directory lists from pyproject.toml ``[tool.swiftkg]``.

A Swift repository need not have a ``pyproject.toml`` at all — most do not —
so every function here is defined to return an empty set rather than to fail
when one is missing or malformed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

__all__ = ["load_include_dirs", "load_exclude_dirs"]


def _load_dir_list(repo_root: Path | str, key: str) -> set[str]:
    repo_root = Path(repo_root)
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return set()
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return set()
    value = data.get("tool", {}).get("swiftkg", {}).get(key, [])
    if isinstance(value, list):
        return {d.rstrip("/") for d in value if isinstance(d, str)}
    return set()


def load_include_dirs(repo_root: Path | str) -> set[str]:
    """Return top-level dirs to include (empty = all).

    :param repo_root: Repository root holding the optional ``pyproject.toml``.
    :return: Set of top-level directory names, or an empty set for "index all".
    """
    return _load_dir_list(repo_root, "include")


def load_exclude_dirs(repo_root: Path | str) -> set[str]:
    """Return extra dir names to exclude at every depth.

    :param repo_root: Repository root holding the optional ``pyproject.toml``.
    :return: Set of directory names to exclude in addition to the defaults.
    """
    return _load_dir_list(repo_root, "exclude")
