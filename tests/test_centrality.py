"""
test_centrality.py — Structural Importance Ranking over a Swift graph.

Two behaviours here are Swift-specific rather than ported: CONFORMS is
weighted alongside INHERITS, and the private-symbol penalty reads the declared
access level out of node metadata instead of guessing from a leading
underscore.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from swift_kg.centrality import (
    CentralityConfig,
    StructuralImportanceRanker,
    aggregate_module_scores,
)

SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT,
    module_path TEXT,
    lineno INTEGER,
    end_lineno INTEGER,
    docstring TEXT,
    metadata TEXT
);
CREATE TABLE edges (
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL,
    evidence TEXT,
    PRIMARY KEY (src, rel, dst)
);
"""

CLIENT = "Sources/Net/Client.swift"
STORE = "Sources/Store/Store.swift"


def _meta(visibility: str = "internal") -> str:
    return json.dumps({"visibility": visibility})


def _make_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO nodes (id, kind, name, qualname, module_path, lineno, end_lineno,"
        " docstring, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"proto:{STORE}:Repository",
                "protocol",
                "Repository",
                "Repository",
                STORE,
                1,
                9,
                None,
                _meta("public"),
            ),
            (
                f"cls:{STORE}:Storage",
                "class",
                "Storage",
                "Storage",
                STORE,
                11,
                30,
                None,
                _meta("open"),
            ),
            (
                f"cls:{STORE}:DiskStorage",
                "class",
                "DiskStorage",
                "DiskStorage",
                STORE,
                32,
                50,
                None,
                _meta("public"),
            ),
            (
                f"meth:{CLIENT}:HTTPClient.send",
                "method",
                "send",
                "HTTPClient.send",
                CLIENT,
                5,
                20,
                None,
                _meta("public"),
            ),
            (
                f"fn:{CLIENT}:secretHelper",
                "function",
                "secretHelper",
                "secretHelper",
                CLIENT,
                22,
                25,
                None,
                _meta("private"),
            ),
            (
                f"fn:{CLIENT}:openHelper",
                "function",
                "openHelper",
                "openHelper",
                CLIENT,
                27,
                30,
                None,
                _meta("internal"),
            ),
            (f"mod:{STORE}", "module", "Store.swift", STORE, STORE, 1, 60, None, _meta()),
            (f"mod:{CLIENT}", "module", "Client.swift", CLIENT, CLIENT, 1, 40, None, _meta()),
            ("sym:Repository", "symbol", "Repository", "Repository", None, None, None, None, None),
        ],
    )
    con.executemany(
        "INSERT INTO edges (src, rel, dst, evidence) VALUES (?, ?, ?, ?)",
        [
            (f"cls:{STORE}:Storage", "CONFORMS", f"proto:{STORE}:Repository", None),
            (f"cls:{STORE}:DiskStorage", "INHERITS", f"cls:{STORE}:Storage", None),
            (f"cls:{STORE}:DiskStorage", "CONFORMS", "sym:Repository", None),
            ("sym:Repository", "RESOLVES_TO", f"proto:{STORE}:Repository", None),
            (f"meth:{CLIENT}:HTTPClient.send", "CALLS", f"fn:{CLIENT}:secretHelper", None),
            (f"meth:{CLIENT}:HTTPClient.send", "CALLS", f"fn:{CLIENT}:openHelper", None),
            (f"mod:{STORE}", "CONTAINS", f"cls:{STORE}:Storage", None),
            (f"mod:{CLIENT}", "CONTAINS", f"meth:{CLIENT}:HTTPClient.send", None),
        ],
    )
    con.commit()
    con.close()
    return path


def _scores(records: list) -> dict[str, float]:
    return {r.node_id: r.score for r in records}


class TestConformanceWeighting:
    def test_conforms_edges_are_counted(self, tmp_path: Path) -> None:
        """CONFORMS is a first-class structural relation in Swift, not noise."""
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        proto = next(r for r in records if r.node_id.startswith("proto:"))
        assert "CONFORMS" in proto.rel_breakdown

    def test_symbol_stub_conformance_resolves_to_the_protocol(self, tmp_path: Path) -> None:
        """`DiskStorage: Repository` via a sym: stub must reach the real node."""
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        proto = next(r for r in records if r.node_id.startswith("proto:"))
        assert proto.rel_breakdown["CONFORMS"] == 2

    def test_protocol_outranks_its_conformers(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        scores = _scores(records)
        assert scores[f"proto:{STORE}:Repository"] > scores[f"cls:{STORE}:DiskStorage"]

    def test_scores_are_normalised(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        assert abs(sum(_scores(records).values()) - 1.0) < 1e-9


class TestAccessLevelPenalty:
    """Swift states visibility with a keyword, so this is read, not guessed."""

    def test_private_declaration_is_penalised(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        scores = _scores(StructuralImportanceRanker(db).compute())
        # Both helpers have exactly one inbound CALLS from the same source.
        assert scores[f"fn:{CLIENT}:secretHelper"] < scores[f"fn:{CLIENT}:openHelper"]

    def test_underscore_name_is_not_penalised_by_itself(self, tmp_path: Path) -> None:
        """The Python and TypeScript modules infer this from a `_` prefix.

        Swift does not use that convention for access control, so a name is
        not evidence either way -- only the declared level is.
        """
        db = tmp_path / "underscore.sqlite"
        _make_db(db)
        con = sqlite3.connect(db)
        con.execute("UPDATE nodes SET name = '_openHelper' WHERE name = 'openHelper'")
        con.commit()
        con.close()
        scores = _scores(StructuralImportanceRanker(db).compute())
        # Renaming changes `name`, not the node ID, so the same key still works.
        assert scores[f"fn:{CLIENT}:openHelper"] > scores[f"fn:{CLIENT}:secretHelper"]

    def test_penalty_is_configurable(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        strict = StructuralImportanceRanker(db, CentralityConfig(private_penalty=0.1)).compute()
        lenient = StructuralImportanceRanker(db, CentralityConfig(private_penalty=1.0)).compute()
        assert (
            _scores(strict)[f"fn:{CLIENT}:secretHelper"]
            < (_scores(lenient)[f"fn:{CLIENT}:secretHelper"])
        )


class TestFiltering:
    def test_kind_filter(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute(
            kinds={"protocol"}
        )
        assert records and {r.kind for r in records} == {"protocol"}

    def test_top_caps_results(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute(top=2)
        assert len(records) == 2

    def test_symbol_stubs_are_excluded_from_results(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        assert not [r for r in records if r.node_id.startswith("sym:")]


class TestPersistence:
    def test_write_scores_round_trips(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        ranker = StructuralImportanceRanker(db)
        written = ranker.write_scores(ranker.compute())
        with sqlite3.connect(db) as con:
            rows = con.execute(
                "SELECT COUNT(*) FROM centrality_scores WHERE metric = 'sir_pagerank'"
            ).fetchone()
        assert rows[0] == written > 0

    def test_rewriting_does_not_duplicate_rows(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        ranker = StructuralImportanceRanker(db)
        ranker.write_scores(ranker.compute())
        ranker.write_scores(ranker.compute())
        with sqlite3.connect(db) as con:
            count = con.execute("SELECT COUNT(*) FROM centrality_scores").fetchone()[0]
        assert count == len(ranker.compute())


class TestModuleAggregation:
    def test_rolls_scores_up_to_modules(self, tmp_path: Path) -> None:
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        modules = aggregate_module_scores(records)
        assert {m["module_path"] for m in modules} == {STORE, CLIENT}

    def test_protocols_weigh_most(self, tmp_path: Path) -> None:
        """A module declaring the abstractions others conform to ranks first."""
        records = StructuralImportanceRanker(_make_db(tmp_path / "g.sqlite")).compute()
        modules = aggregate_module_scores(records)
        assert modules[0]["module_path"] == STORE


class TestEmptyGraph:
    def test_empty_graph_returns_no_records(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.commit()
        con.close()
        assert StructuralImportanceRanker(db).compute() == []
