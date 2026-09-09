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

from swift_kg.analysis import SwiftKGAnalyzer
from swift_kg.extractor import _HAS_TREE_SITTER
from swift_kg.kg import SwiftKG

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


class TestCompiledResults:
    def test_results_are_serialisable(self, analyzer: SwiftKGAnalyzer) -> None:
        import json

        json.dumps(analyzer._compile_results())
