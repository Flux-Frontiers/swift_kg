"""
test_coderank.py — CodeRank graph construction and ranking over a Swift graph.

Two Swift adaptations are pinned here: CONFORMS carries a structural edge
weight, and test-path exclusion recognises SwiftPM's `Tests/` layout and the
`…Tests.swift` filename convention rather than TypeScript's `.test.ts` infix.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from swift_kg.coderank import (
    DEFAULT_EDGE_WEIGHTS,
    DEFAULT_GLOBAL_RELS,
    DEFAULT_KIND_PRIORS,
    build_code_graph,
    compute_coderank,
    persist_metric_scores,
    rank_query_hybrid,
)

SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, qualname TEXT,
    module_path TEXT, lineno INTEGER, end_lineno INTEGER, docstring TEXT, metadata TEXT
);
CREATE TABLE edges (
    src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, evidence TEXT,
    PRIMARY KEY (src, rel, dst)
);
"""

STORE = "Sources/Store/Store.swift"
APP = "Sources/App/App.swift"
TESTS = "Tests/StoreTests/StorageTests.swift"

NODES = [
    (f"proto:{STORE}:Repository", "protocol", "Repository", "Repository", STORE),
    (f"struct:{STORE}:MemoryStore", "struct", "MemoryStore", "MemoryStore", STORE),
    (f"struct:{STORE}:DiskStore", "struct", "DiskStore", "DiskStore", STORE),
    (f"fn:{APP}:run", "function", "run", "run", APP),
    (
        f"meth:{TESTS}:StorageTests.testFetch",
        "method",
        "testFetch",
        "StorageTests.testFetch",
        TESTS,
    ),
]

EDGES = [
    (f"struct:{STORE}:MemoryStore", "CONFORMS", f"proto:{STORE}:Repository"),
    (f"struct:{STORE}:DiskStore", "CONFORMS", f"proto:{STORE}:Repository"),
    (f"fn:{APP}:run", "CALLS", f"struct:{STORE}:MemoryStore"),
    (f"meth:{TESTS}:StorageTests.testFetch", "CALLS", f"struct:{STORE}:DiskStore"),
]


def _make_db(path: Path) -> str:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO nodes (id, kind, name, qualname, module_path, lineno, end_lineno,"
        " docstring, metadata) VALUES (?, ?, ?, ?, ?, 1, 9, NULL, NULL)",
        NODES,
    )
    con.executemany("INSERT INTO edges (src, rel, dst, evidence) VALUES (?, ?, ?, NULL)", EDGES)
    con.commit()
    con.close()
    return str(path)


class TestDefaults:
    def test_conformance_is_a_weighted_relation(self) -> None:
        """CONFORMS replaces IMPLEMENTS; leaving it out drops it from the graph."""
        assert DEFAULT_EDGE_WEIGHTS["CONFORMS"] > 0
        assert "IMPLEMENTS" not in DEFAULT_EDGE_WEIGHTS

    def test_conformance_is_traversed_globally(self) -> None:
        assert "CONFORMS" in DEFAULT_GLOBAL_RELS

    def test_swift_kinds_have_priors(self) -> None:
        for kind in ("struct", "protocol", "actor", "extension", "typealias", "property"):
            assert kind in DEFAULT_KIND_PRIORS


class TestGraphConstruction:
    def test_builds_a_graph(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        assert graph.number_of_nodes() == len(NODES)
        assert graph.number_of_edges() == len(EDGES)

    def test_edges_carry_weights(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        for _, _, data in graph.edges(data=True):
            assert data["weight"] > 0

    def test_conformance_edges_survive_the_default_relation_filter(self, tmp_path: Path) -> None:
        graph = build_code_graph(
            _make_db(tmp_path / "g.sqlite"),
            include_relations=DEFAULT_GLOBAL_RELS,
            exclude_test_paths=False,
        )
        assert graph.has_edge(f"struct:{STORE}:MemoryStore", f"proto:{STORE}:Repository")

    def test_kind_filter(self, tmp_path: Path) -> None:
        graph = build_code_graph(
            _make_db(tmp_path / "g.sqlite"),
            include_kinds={"protocol", "struct"},
            exclude_test_paths=False,
        )
        assert f"fn:{APP}:run" not in graph


class TestTestPathExclusion:
    """SwiftPM uses `Tests/<Target>/` and a `…Tests.swift` filename suffix."""

    def test_swiftpm_tests_directory_is_excluded(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=True)
        assert f"meth:{TESTS}:StorageTests.testFetch" not in graph

    def test_production_code_is_kept(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=True)
        assert f"fn:{APP}:run" in graph

    def test_exclusion_can_be_disabled(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        assert f"meth:{TESTS}:StorageTests.testFetch" in graph


class TestRanking:
    def test_coderank_sums_to_one(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        scores = compute_coderank(graph)
        assert abs(sum(scores.values()) - 1.0) < 1e-6

    def test_the_protocol_ranks_highest(self, tmp_path: Path) -> None:
        """Two conformers point at it; nothing points at them."""
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        scores = compute_coderank(graph)
        assert max(scores, key=lambda k: scores[k]) == f"proto:{STORE}:Repository"

    def test_empty_graph_returns_no_scores(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.commit()
        con.close()
        assert compute_coderank(build_code_graph(str(db))) == {}

    def test_hybrid_ranking_returns_explanations(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        results = rank_query_hybrid(graph, {f"struct:{STORE}:MemoryStore": 0.9}, top_k=5)
        assert results
        assert all(isinstance(r.why, tuple) for r in results)

    def test_hybrid_ranking_mentions_conformance(self, tmp_path: Path) -> None:
        graph = build_code_graph(_make_db(tmp_path / "g.sqlite"), exclude_test_paths=False)
        results = rank_query_hybrid(graph, {f"struct:{STORE}:MemoryStore": 0.9}, top_k=5)
        proto = next((r for r in results if r.node_id.startswith("proto:")), None)
        assert proto is not None
        assert any("conformed to" in reason for reason in proto.why)


class TestPersistence:
    def test_scores_round_trip(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        graph = build_code_graph(db, exclude_test_paths=False)
        scores = compute_coderank(graph)
        persist_metric_scores(db, "coderank", scores)
        with sqlite3.connect(db) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM node_metrics WHERE metric = 'coderank'"
            ).fetchone()[0]
        assert count == len(scores) > 0

    def test_rewriting_does_not_duplicate_rows(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        scores = compute_coderank(build_code_graph(db, exclude_test_paths=False))
        persist_metric_scores(db, "coderank", scores)
        persist_metric_scores(db, "coderank", scores)
        with sqlite3.connect(db) as con:
            count = con.execute("SELECT COUNT(*) FROM node_metrics").fetchone()[0]
        assert count == len(scores)
