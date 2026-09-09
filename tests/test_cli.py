"""
test_cli.py — the swiftkg command group.

Covers what the group promises rather than what each command computes: that
every subcommand is registered and importable, that the deferred visualizers
answer instead of erroring, and that the graph-building path works end to end
from the CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from swift_kg.cli.main import cli
from swift_kg.extractor import _HAS_TREE_SITTER

#: Every subcommand the group is expected to expose, named rather than counted
#: so a rename or a dropped registration fails readably.
EXPECTED_COMMANDS = {
    "analyze",
    "bridges",
    "build",
    "build-index",
    "build-sqlite",
    "centrality",
    "download-model",
    "explain",
    "framework-nodes",
    "init",
    "install-hooks",
    "mcp",
    "pack",
    "query",
    "snapshot",
    "update",
    "viz",
    "viz-timeline",
    "viz3d",
}

#: Commands deferred to a later release. They are registered deliberately:
#: a user arriving from `pycodekg` or `tscodekg` will type these, and an
#: answer naming what is missing beats "Error: No such command".
DEFERRED_COMMANDS = {"viz", "viz3d", "viz-timeline"}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCommandGroup:
    def test_help_lists_every_expected_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert EXPECTED_COMMANDS <= set(cli.commands)

    def test_no_unexpected_commands(self) -> None:
        assert set(cli.commands) <= EXPECTED_COMMANDS

    @pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
    def test_each_command_has_help(self, runner: CliRunner, name: str) -> None:
        """Catches a lazy import that only fails when the command is invoked."""
        result = runner.invoke(cli, [name, "--help"])
        assert result.exit_code == 0, result.output


class TestDeferredVisualizers:
    @pytest.mark.parametrize("name", sorted(DEFERRED_COMMANDS))
    def test_deferred_command_explains_itself(self, runner: CliRunner, name: str) -> None:
        result = runner.invoke(cli, [name])
        assert result.exit_code == 2
        assert "not yet available" in result.output

    @pytest.mark.parametrize("name", sorted(DEFERRED_COMMANDS))
    def test_deferred_command_points_at_what_does_work(self, runner: CliRunner, name: str) -> None:
        result = runner.invoke(cli, [name])
        assert "swiftkg analyze" in result.output


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")
class TestBuildCommand:
    def test_build_sqlite_writes_a_graph(self, runner: CliRunner, tmp_repo: Path) -> None:
        result = runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        assert result.exit_code == 0, result.output
        assert (tmp_repo / ".swiftkg" / "graph.sqlite").exists()

    def test_build_reports_swift_node_kinds(self, runner: CliRunner, tmp_repo: Path) -> None:
        result = runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        for kind in ("struct", "protocol", "actor", "extension"):
            assert kind in result.output

    def test_missing_repo_exits_nonzero(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_path / "nope")])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_explain_on_a_missing_node_exits_nonzero(
        self, runner: CliRunner, tmp_repo: Path
    ) -> None:
        """Scripting needs missing-node distinguishable from rendered output."""
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        result = runner.invoke(cli, ["explain", "cls:nope.swift:Nope", "--repo", str(tmp_repo)])
        assert result.exit_code == 1
