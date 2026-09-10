"""
test_analysis.py — the multi-phase analyzer.

Runs against a graph built without a vector index, which is both the cheap
path and the interesting one: exactly one phase needs the index, and the run
has to degrade to a complete report plus an explicit notice rather than
aborting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from swift_kg.extractor import _HAS_TREE_SITTER
from swift_kg.kg import SwiftKG
from swift_kg.swiftkg_thorough_analysis import SwiftKGAnalyzer

pytestmark = pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")


@pytest.fixture
def analyzer(tmp_repo: Path, tmp_path: Path):
    kg = SwiftKG(
        repo_root=tmp_repo,
        db_path=tmp_path / "graph.sqlite",
        vectors_path=tmp_path / "vectors.sqlite",
    )
    kg.build_graph(wipe=True)
    instance = SwiftKGAnalyzer(kg, console=Console(quiet=True))
    instance.run_analysis()
    yield instance
    kg.close()


class TestDegradedRun:
    """A missing vector index must cost one phase, not the whole report."""

    def test_the_run_completes(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.to_markdown().startswith("# SwiftKG Repository Analysis")

    def test_only_the_semantic_phase_is_skipped(self, analyzer: SwiftKGAnalyzer) -> None:
        assert len(analyzer.phase_failures) <= 1

    def test_the_report_says_what_is_missing(self, analyzer: SwiftKGAnalyzer) -> None:
        report = analyzer.to_markdown()
        if analyzer.phase_failures:
            assert "Incomplete Analysis" in report
            assert "swiftkg build" in report, "the notice must name the fix"

    def test_the_notice_is_absent_when_nothing_failed(self, analyzer: SwiftKGAnalyzer) -> None:
        if not analyzer.phase_failures:
            assert "Incomplete Analysis" not in analyzer.to_markdown()


class TestPhasesThatNeedNoIndex:
    def test_baseline_metrics_are_collected(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.stats["total_nodes"] > 0

    def test_coderank_ran(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.coderank_scores

    def test_fan_in_metrics_exist(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.function_metrics

    def test_doc_coverage_counts_swift_kinds(self, analyzer: SwiftKGAnalyzer) -> None:
        by_kind = analyzer.doc_comment_coverage["by_kind"]
        assert "protocol" in by_kind or "struct" in by_kind

    def test_module_coupling_ran(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.module_metrics

    def test_centrality_ran(self, analyzer: SwiftKGAnalyzer) -> None:
        assert analyzer.centrality_modules


class TestPublicApiPhase:
    """Read from declared access levels, not grepped from the source."""

    def test_public_declarations_are_found(self, analyzer: SwiftKGAnalyzer) -> None:
        names = {api.name for api in analyzer.public_apis}
        assert {"Point", "Counter"} <= names

    def test_private_declarations_are_not_public_api(self, analyzer: SwiftKGAnalyzer) -> None:
        publics = {
            api.name
            for api in analyzer.public_apis
            if api.fan_in == 0  # only the visibility-sourced entries
        }
        assert "items" not in publics


class TestTypeHierarchyPhase:
    def test_inheritance_and_conformance_are_counted_separately(
        self, analyzer: SwiftKGAnalyzer
    ) -> None:
        inh = analyzer.inheritance_analysis
        assert inh["total_inherits_edges"] > 0
        assert inh["total_conforms_edges"] > 0

    def test_conformance_rows_use_swift_vocabulary(self, analyzer: SwiftKGAnalyzer) -> None:
        rows = analyzer.inheritance_analysis["conforms"]
        assert rows and set(rows[0]) == {"type", "protocol", "module"}

    def test_depth_counts_only_inheritance(self, analyzer: SwiftKGAnalyzer) -> None:
        """A struct conforming to two protocols is not two levels deep."""
        assert analyzer.inheritance_analysis["max_depth"] <= 2

    def test_report_section_is_swift_titled(self, analyzer: SwiftKGAnalyzer) -> None:
        assert "Type Hierarchy and Conformance" in analyzer.to_markdown()


class TestOrphanPhase:
    def test_swiftui_and_lifecycle_members_are_not_orphans(self, analyzer: SwiftKGAnalyzer) -> None:
        orphan_names = {o.name for o in analyzer.orphaned_functions}
        assert not ({"init", "deinit", "body", "description"} & orphan_names)

    def test_a_public_declaration_is_not_an_orphan(self, analyzer: SwiftKGAnalyzer) -> None:
        """A library's callers are outside the repository being indexed.

        `_is_swift_entry_point` has always tested visibility, but the phase
        built its node dict without metadata, so the test read its "internal"
        default and filed the entire public API as possible dead code.
        """
        orphan_names = {o.name for o in analyzer.orphaned_functions}
        assert not ({"audit", "distance", "increment", "measure", "scaled"} & orphan_names)

    def test_visibility_inherited_from_a_public_extension_is_honoured(
        self, analyzer: SwiftKGAnalyzer
    ) -> None:
        """`inverted()` declares no access level; its `public extension` confers one."""
        assert "inverted" not in {o.name for o in analyzer.orphaned_functions}

    def test_an_uncalled_internal_declaration_is_still_an_orphan(
        self, analyzer: SwiftKGAnalyzer
    ) -> None:
        """The filter must not swallow the dead code the phase exists to find."""
        assert "debugDump" in {o.name for o in analyzer.orphaned_functions}

    def test_a_called_internal_declaration_is_not_an_orphan(
        self, analyzer: SwiftKGAnalyzer
    ) -> None:
        assert "logAccess" not in {o.name for o in analyzer.orphaned_functions}


class TestReportVocabulary:
    def test_no_typescript_relations_leak_into_the_report(self, analyzer: SwiftKGAnalyzer) -> None:
        report = analyzer.to_markdown()
        assert "IMPLEMENTS" not in report

    def test_swift_relations_are_reported(self, analyzer: SwiftKGAnalyzer) -> None:
        assert "CONFORMS" in analyzer.to_markdown()

    def test_swift_kinds_are_reported(self, analyzer: SwiftKGAnalyzer) -> None:
        report = analyzer.to_markdown()
        for label in ("Structs", "Protocols", "Actors", "Extensions"):
            assert label in report

    def test_the_public_api_section_does_not_claim_an_export_keyword(
        self, analyzer: SwiftKGAnalyzer
    ) -> None:
        """Swift has no `export`; the surface is read from access levels.

        The sibling modules greps for `export`, and that vocabulary followed the
        report template over into SwiftKG.
        """
        assert "export" not in analyzer.to_markdown().lower()

    def test_the_written_report_names_the_swift_keywords(
        self, analyzer: SwiftKGAnalyzer, tmp_path: Path
    ) -> None:
        """The full report describes the surface; `to_markdown` only tabulates it."""
        out = tmp_path / "report.md"
        analyzer._write_report(str(out))
        report = out.read_text()
        assert "## Public API Surface" in report
        assert "`public` or `open`" in report
        assert "export" not in report.lower()


class TestCompiledResults:
    def test_results_are_serialisable(self, analyzer: SwiftKGAnalyzer) -> None:
        import json

        json.dumps(analyzer._compile_results())


class TestMainEntryPoint:
    """`main()` is the single entry behind the CLI, the `__main__` guard and
    any programmatic caller, mirroring `pycodekg_thorough_analysis.main`."""

    def test_it_takes_pycodekgs_parameter_set(self) -> None:
        import inspect

        from swift_kg.swiftkg_thorough_analysis import main

        assert list(inspect.signature(main).parameters) == [
            "repo_root",
            "db_path",
            "vectors_path",
            "report_path",
            "json_path",
            "quiet",
            "include",
            "exclude",
            "persist_centrality",
        ]

    def test_a_missing_graph_returns_empty_rather_than_raising(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A traceback here says nothing actionable; the fix is one command."""
        from swift_kg.swiftkg_thorough_analysis import main

        assert main(repo_root=str(tmp_path)) == {}
        assert "swiftkg build" in capsys.readouterr().out

    def test_it_returns_the_compiled_results(self, tmp_repo: Path) -> None:
        from swift_kg.kg import SwiftKG
        from swift_kg.swiftkg_thorough_analysis import main

        kg = SwiftKG(repo_root=tmp_repo)
        kg.build_graph(wipe=True)
        kg.close()

        results = main(repo_root=str(tmp_repo), quiet=True, report_path=str(tmp_repo / "r.md"))
        assert results["statistics"]
        assert results["quality"]["grade"]

    def test_json_output_carries_the_quality_grade(self, tmp_repo: Path) -> None:
        """The report's headline number, so a JSON consumer need not recompute it."""
        import json

        from swift_kg.kg import SwiftKG
        from swift_kg.swiftkg_thorough_analysis import main

        kg = SwiftKG(repo_root=tmp_repo)
        kg.build_graph(wipe=True)
        kg.close()

        out = tmp_repo / "results.json"
        main(
            repo_root=str(tmp_repo),
            quiet=True,
            report_path=str(tmp_repo / "r.md"),
            json_path=str(out),
        )
        quality = json.loads(out.read_text())["quality"]
        assert set(quality) == {"score", "grade", "label"}

    def test_no_json_is_written_without_a_path(self, tmp_repo: Path) -> None:
        from swift_kg.kg import SwiftKG
        from swift_kg.swiftkg_thorough_analysis import main

        kg = SwiftKG(repo_root=tmp_repo)
        kg.build_graph(wipe=True)
        kg.close()

        main(repo_root=str(tmp_repo), quiet=True, report_path=str(tmp_repo / "r.md"))
        assert not list(tmp_repo.glob("*.json"))
