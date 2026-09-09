"""
conftest.py — shared pytest fixtures for SwiftKG tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_repo() -> Path:
    """Return the path to the checked-in Swift fixture repository."""
    return FIXTURE_DIR


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Copy the Swift fixture repository into a temporary directory.

    The fixture is a two-target SwiftPM-shaped tree rather than a single file,
    because the extractor's whole resolution model is repo-wide: a
    single-file fixture could not exercise cross-file calls, which is the
    behaviour most likely to regress.
    """
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE_DIR / "Sources", dest / "Sources")
    return dest
