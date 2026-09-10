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


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")
class TestDirectoryScoping:
    """`--include-dir` / `--exclude-dir`, matching `pycodekg`.

    A Swift repository almost never has a `pyproject.toml`, so these flags are
    the only reachable way to scope a build on most repositories -- without
    them, test and example sources land in the graph and skew every metric the
    report computes.
    """

    def _modules(self, repo: Path) -> set[str]:
        import sqlite3

        con = sqlite3.connect(repo / ".swiftkg" / "graph.sqlite")
        try:
            rows = con.execute("SELECT module_path FROM nodes WHERE kind = 'module'")
            return {row[0] for row in rows}
        finally:
            con.close()

    def test_without_flags_every_directory_is_indexed(
        self, runner: CliRunner, tmp_repo: Path
    ) -> None:
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        assert len(self._modules(tmp_repo)) == 2

    def test_exclude_dir_drops_a_directory_at_any_depth(
        self, runner: CliRunner, tmp_repo: Path
    ) -> None:
        result = runner.invoke(
            cli, ["build-sqlite", "--repo", str(tmp_repo), "--exclude-dir", "SampleApp"]
        )
        assert result.exit_code == 0, result.output
        modules = self._modules(tmp_repo)
        assert modules == {"Sources/SampleKit/Storage.swift"}

    def test_include_dir_names_a_top_level_directory(
        self, runner: CliRunner, tmp_repo: Path
    ) -> None:
        result = runner.invoke(
            cli, ["build-sqlite", "--repo", str(tmp_repo), "--include-dir", "Sources"]
        )
        assert result.exit_code == 0, result.output
        assert len(self._modules(tmp_repo)) == 2

    def test_build_accepts_the_same_flags(self, runner: CliRunner, tmp_repo: Path) -> None:
        result = runner.invoke(
            cli,
            ["build", "--repo", str(tmp_repo), "--graph-only", "--exclude-dir", "SampleKit"],
        )
        assert result.exit_code == 0, result.output
        assert self._modules(tmp_repo) == {"Sources/SampleApp/Geometry.swift"}

    @pytest.mark.parametrize("command", ["analyze", "build", "build-sqlite", "update"])
    def test_the_flags_are_documented(self, runner: CliRunner, command: str) -> None:
        result = runner.invoke(cli, [command, "--help"])
        assert "--include-dir" in result.output
        assert "--exclude-dir" in result.output


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")
class TestAnalyzeSnapshotHistory:
    """`analyze` has to see the snapshots `init` and `snapshot save` wrote.

    Without a SnapshotManager the phase reports "skipped", which the report
    renders as "No snapshots" -- indistinguishable from a repository that has
    never captured one.
    """

    def test_snapshot_history_is_loaded(
        self, runner: CliRunner, tmp_repo: Path, tmp_path: Path
    ) -> None:
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        saved = runner.invoke(cli, ["snapshot", "save", "0.1.0", "--repo", str(tmp_repo)])
        assert saved.exit_code == 0, saved.output

        report = tmp_path / "report.md"
        result = runner.invoke(cli, ["analyze", str(tmp_repo), "-o", str(report)])
        assert result.exit_code == 0, result.output
        assert "Snapshot history  1 snapshot(s)" in result.output
        assert "No snapshots." not in report.read_text()

    def test_no_snapshot_dir_is_still_reported_honestly(
        self, runner: CliRunner, tmp_repo: Path, tmp_path: Path
    ) -> None:
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        report = tmp_path / "report.md"
        result = runner.invoke(cli, ["analyze", str(tmp_repo), "-o", str(report)])
        assert result.exit_code == 0, result.output
        assert "No snapshots." in report.read_text()

    def test_the_written_report_is_announced_once(
        self, runner: CliRunner, tmp_repo: Path, tmp_path: Path
    ) -> None:
        """Both the analyzer and the CLI used to print the same line."""
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        report = tmp_path / "report.md"
        result = runner.invoke(cli, ["analyze", str(tmp_repo), "-o", str(report)])
        assert result.output.count("Report written to") == 1


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")
class TestAnalyzeOutputs:
    """`-j/--json` and `-q/--quiet`, matching `pycodekg analyze`."""

    def test_json_snapshot_is_written(self, runner: CliRunner, tmp_repo: Path) -> None:
        import json

        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        out = tmp_repo / "results.json"
        result = runner.invoke(
            cli,
            ["analyze", str(tmp_repo), "-o", str(tmp_repo / "r.md"), "-j", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())["quality"]["grade"]

    def test_quiet_suppresses_phase_progress(self, runner: CliRunner, tmp_repo: Path) -> None:
        runner.invoke(cli, ["build-sqlite", "--repo", str(tmp_repo)])
        noisy = runner.invoke(cli, ["analyze", str(tmp_repo), "-o", str(tmp_repo / "a.md")])
        quiet = runner.invoke(
            cli, ["analyze", str(tmp_repo), "-o", str(tmp_repo / "b.md"), "--quiet"]
        )
        assert "Phase" in noisy.output
        assert "Phase" not in quiet.output

    def test_a_missing_graph_exits_nonzero(self, runner: CliRunner, tmp_path: Path) -> None:
        """Scripting needs a failed analysis distinguishable from a clean one."""
        result = runner.invoke(cli, ["analyze", str(tmp_path)])
        assert result.exit_code == 1
        assert "swiftkg build" in result.output

    def test_the_flags_are_documented(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["analyze", "--help"])
        for flag in ("--json", "--quiet", "--report", "--include-dir"):
            assert flag in result.output
