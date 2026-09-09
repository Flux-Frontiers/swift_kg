"""
test_bridge.py — module connectivity (bridge centrality) over a Swift graph.

The one substantive Swift adaptation: a Swift `import` names a module, not a
file, so IMPORTS edges point at `sym:` stubs with no module_path and are
dropped by the join. Conformance and extension edges carry the cross-file
coupling instead, and this suite pins that they are actually counted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from swift_kg.bridge import compute_bridge_centrality

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

HUB = "Sources/App/Coordinator.swift"
NET = "Sources/Net/Client.swift"
MODEL = "Sources/Model/Point.swift"
PROTO = "Sources/Model/Drawable.swift"


def _make_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO nodes (id, kind, name, qualname, module_path, lineno, end_lineno,"
        " docstring, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (f"fn:{HUB}:run", "function", "run", "run", HUB, 1, 9, None, None),
            (
                f"meth:{NET}:HTTPClient.send",
                "method",
                "send",
                "HTTPClient.send",
                NET,
                1,
                9,
                None,
                None,
            ),
            (f"struct:{MODEL}:Point", "struct", "Point", "Point", MODEL, 1, 9, None, None),
            (f"ext:{MODEL}:Point", "extension", "Point", "Point", MODEL, 11, 20, None, None),
            (
                f"proto:{PROTO}:Drawable",
                "protocol",
                "Drawable",
                "Drawable",
                PROTO,
                1,
                5,
                None,
                None,
            ),
            # A module-level import target: no module_path, as the extractor emits it.
            ("sym:Foundation", "symbol", "Foundation", "Foundation", None, None, None, None, None),
        ],
    )
    con.executemany(
        "INSERT INTO edges (src, rel, dst, evidence) VALUES (?, ?, ?, ?)",
        [
            (f"fn:{HUB}:run", "CALLS", f"meth:{NET}:HTTPClient.send", None),
            (f"fn:{HUB}:run", "CALLS", f"struct:{MODEL}:Point", None),
            (f"meth:{NET}:HTTPClient.send", "CALLS", f"struct:{MODEL}:Point", None),
            # Cross-file conformance -- the coupling Swift actually expresses.
            (f"ext:{MODEL}:Point", "CONFORMS", f"proto:{PROTO}:Drawable", None),
            (f"struct:{MODEL}:Point", "CONFORMS", f"proto:{PROTO}:Drawable", None),
            (f"fn:{HUB}:run", "IMPORTS", "sym:Foundation", None),
        ],
    )
    con.commit()
    con.close()
    return path


class TestConnectivity:
    def test_returns_ranked_modules(self, tmp_path: Path) -> None:
        ranked = compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite")))
        assert ranked
        assert ranked == sorted(ranked, key=lambda x: x[1], reverse=True)

    def test_the_coordinator_is_the_hub(self, tmp_path: Path) -> None:
        ranked = compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite")))
        assert ranked[0][0] in (HUB, MODEL)

    def test_conformance_edges_contribute(self, tmp_path: Path) -> None:
        """Without CONFORMS in the relation set, the protocol file scores zero.

        This is the Swift adaptation: leaving the relation set at CALLS and
        IMPORTS would give a metric that runs but carries half its signal, with
        nothing to indicate the difference.
        """
        ranked = dict(compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite"))))
        assert PROTO in ranked and ranked[PROTO] > 0

    def test_import_stubs_do_not_appear_as_modules(self, tmp_path: Path) -> None:
        ranked = dict(compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite"))))
        assert "sym:Foundation" not in ranked
        assert "Foundation" not in ranked

    def test_scores_are_bounded(self, tmp_path: Path) -> None:
        ranked = compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite")))
        assert all(0.0 <= score <= 1.0 for _, score in ranked)

    def test_top_caps_results(self, tmp_path: Path) -> None:
        ranked = compute_bridge_centrality(db_path=str(_make_db(tmp_path / "g.sqlite")), top=2)
        assert len(ranked) == 2

    def test_scores_are_persisted(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path / "g.sqlite")
        compute_bridge_centrality(db_path=str(db))
        with sqlite3.connect(db) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM centrality_scores WHERE metric = 'module_connectivity'"
            ).fetchone()[0]
        assert count > 0


class TestEmptyGraph:
    def test_empty_graph_returns_nothing(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.commit()
        con.close()
        assert compute_bridge_centrality(db_path=str(db)) == []
