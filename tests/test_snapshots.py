"""
test_snapshots.py — SwiftKG's snapshot layer.

The module configures the shared ``kg_utils`` base rather than overriding it
(FLEET_STANDARDS, settled 2026-09-08): a ``package_name`` class attribute and a
``_domain_metrics()`` hook, no ``capture()`` override and no ``Snapshot``
subclass. Several tests here exist to keep it that way, because the defect
that motivated the standard -- a ``capture()`` override swallowing ``key=``
into ``**extra_metrics`` -- shipped in four packages without failing anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swift_kg.snapshots import PruneResult, Snapshot, SnapshotManager, SnapshotManifest


def _stats(
    *,
    classes: int = 4,
    structs: int = 10,
    protocols: int = 6,
    actors: int = 2,
    enums: int = 3,
    extensions: int = 15,
    conforms: int = 30,
    inherits: int = 3,
) -> dict:
    types = classes + structs + protocols + actors + enums
    return {
        "total_nodes": types + extensions + 40,
        "meaningful_nodes": types + extensions + 35,
        "total_edges": conforms + inherits + 80,
        "docstring_coverage": 0.62,
        "node_counts": {
            "class": classes,
            "struct": structs,
            "protocol": protocols,
            "actor": actors,
            "enum": enums,
            "extension": extensions,
            "function": 25,
            "method": 15,
            "module": 8,
        },
        "edge_counts": {
            "CONFORMS": conforms,
            "INHERITS": inherits,
            "CALLS": 60,
            "CONTAINS": 20,
        },
    }


@pytest.fixture
def manager(tmp_path: Path) -> SnapshotManager:
    return SnapshotManager(tmp_path / "snapshots")


class TestPackageIdentity:
    def test_tool_field_names_this_package(self, manager: SnapshotManager) -> None:
        """Against kgmodule-utils <0.20 this would read "kg-utils"."""
        snap = manager.capture(
            version="0.1.0", branch="main", key="0.1.0", graph_stats_dict=_stats()
        )
        assert snap.tool == "swift-kg"

    def test_package_name_is_a_class_attribute(self) -> None:
        """Not an __init__ that forwards to super() -- that is the retired shape."""
        assert SnapshotManager.package_name == "swift-kg"
        assert "__init__" not in SnapshotManager.__dict__


class TestBaseIsNotOverridden:
    """FLEET_STANDARDS names these explicitly: configure, never reimplement."""

    @pytest.mark.parametrize(
        "method",
        [
            "save_snapshot",
            "load_snapshot",
            "get_previous",
            "get_baseline",
            "_compute_delta",
            "to_dict",
            "from_dict",
            "capture",
        ],
    )
    def test_method_is_inherited(self, method: str) -> None:
        assert method not in SnapshotManager.__dict__, (
            f"{method} must come from the kg_utils base -- reimplementing it is "
            "what let a real bug ship in two sibling repos"
        )

    def test_snapshot_type_is_the_shared_one(self) -> None:
        from kg_utils.snapshots import Snapshot as BaseSnapshot

        assert Snapshot is BaseSnapshot


class TestDomainMetrics:
    def test_swift_type_counts_are_recorded(self, manager: SnapshotManager) -> None:
        snap = manager.capture(version="0.1.0", branch="main", key="k", graph_stats_dict=_stats())
        assert snap.metrics["swift_structs"] == 10
        assert snap.metrics["swift_protocols"] == 6
        assert snap.metrics["swift_actors"] == 2
        assert snap.metrics["swift_extensions"] == 15

    def test_total_type_count_sums_the_kinds(self, manager: SnapshotManager) -> None:
        snap = manager.capture(version="0.1.0", branch="main", key="k", graph_stats_dict=_stats())
        assert snap.metrics["swift_types"] == 4 + 10 + 6 + 2 + 3

    def test_extension_ratio_is_derived(self, manager: SnapshotManager) -> None:
        """How much behaviour is declared away from the type it belongs to."""
        snap = manager.capture(
            version="0.1.0", branch="main", key="k", graph_stats_dict=_stats(extensions=25)
        )
        assert snap.metrics["swift_extension_ratio"] == pytest.approx(25 / 25)

    def test_extension_ratio_survives_an_empty_graph(self, manager: SnapshotManager) -> None:
        snap = manager.capture(
            version="0.1.0",
            branch="main",
            key="k",
            graph_stats_dict={"node_counts": {}, "edge_counts": {}},
        )
        assert snap.metrics["swift_extension_ratio"] == 0.0

    def test_conformance_counts_come_from_edges(self, manager: SnapshotManager) -> None:
        snap = manager.capture(
            version="0.1.0", branch="main", key="k", graph_stats_dict=_stats(conforms=42)
        )
        assert snap.metrics["swift_conformances"] == 42

    def test_missing_stats_do_not_raise(self, manager: SnapshotManager) -> None:
        snap = manager.capture(version="0.1.0", branch="main", key="k", graph_stats_dict={})
        assert snap.metrics["swift_types"] == 0


class TestRoundTrip:
    def test_capture_save_and_load(self, manager: SnapshotManager) -> None:
        snap = manager.capture(
            version="0.1.0",
            branch="develop",
            key="v0.1.0",
            subject="repo:swift-kg",
            tree_hash="a" * 40,
            graph_stats_dict=_stats(),
        )
        path = manager.save_snapshot(snap)
        assert path is not None and path.exists()

        loaded = manager.load_snapshot("v0.1.0")
        assert loaded is not None
        assert loaded.subject == "repo:swift-kg"
        assert loaded.metrics["swift_protocols"] == 6

    def test_key_is_honoured_not_swallowed(self, manager: SnapshotManager) -> None:
        """The four-package defect: `key=` falling into **extra_metrics.

        A capture() override has to restate the base signature, and restating
        it is how the keyword goes missing -- the snapshot then keys on a git
        tree hash while the code reads correctly.
        """
        snap = manager.capture(
            version="0.1.0",
            branch="main",
            key="explicit-key",
            tree_hash="b" * 40,
            graph_stats_dict=_stats(),
        )
        assert snap.key == "explicit-key"
        assert "key" not in snap.metrics

    def test_manifest_tracks_saved_snapshots(self, manager: SnapshotManager) -> None:
        for version in ("0.1.0", "0.2.0"):
            manager.save_snapshot(
                manager.capture(
                    version=version, branch="main", key=version, graph_stats_dict=_stats()
                )
            )
        manifest = manager.load_manifest()
        assert isinstance(manifest, SnapshotManifest)
        assert len(manifest.snapshots) == 2


class TestDiff:
    def test_diff_reports_swift_metric_movement(self, manager: SnapshotManager) -> None:
        a = manager.capture(
            version="0.1.0", branch="main", key="a", graph_stats_dict=_stats(protocols=6)
        )
        manager.save_snapshot(a)
        b = manager.capture(
            version="0.2.0", branch="main", key="b", graph_stats_dict=_stats(protocols=9)
        )
        manager.save_snapshot(b)

        diff = manager.diff_snapshots("a", "b")
        assert "error" not in diff
        assert b.metrics["swift_protocols"] - a.metrics["swift_protocols"] == 3

    def test_diff_of_a_missing_snapshot_reports_an_error(self, manager: SnapshotManager) -> None:
        assert "error" in manager.diff_snapshots("nope", "also-nope")


class TestPrune:
    def test_prune_returns_a_result(self, manager: SnapshotManager) -> None:
        manager.save_snapshot(
            manager.capture(version="0.1.0", branch="main", key="a", graph_stats_dict=_stats())
        )
        result = manager.prune_snapshots(dry_run=True)
        assert isinstance(result, PruneResult)
