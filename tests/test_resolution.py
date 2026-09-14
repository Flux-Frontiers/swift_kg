"""
test_resolution.py — symbol stubs and the prunes applied after resolution.

The extractor's two-pass resolver pins down every reference it can and refuses
to guess between candidates, so what reaches resolution is what it could not
resolve: framework names with no first-party declaration, and calls through a
receiver of unknown type.  Resolving those by bare name is only safe once the
ambiguous matches are dropped, which is what most of this file is about.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swift_kg.extractor import _HAS_TREE_SITTER
from swift_kg.kg import SwiftKG
from swift_kg.resolution import (
    SWIFT_STDLIB_MEMBER_NAMES,
    prune_ambiguous_resolutions,
    prune_extension_self_resolutions,
    prune_stdlib_member_resolutions,
    resolve_symbols_pruned,
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

AMBIGUOUS = '{"resolution_mode": "name_fallback_ambiguous", "confidence": "low"}'
UNIQUE = '{"resolution_mode": "name_fallback", "confidence": "medium"}'


# ---------------------------------------------------------------------------
# Prunes, over a synthetic graph
# ---------------------------------------------------------------------------


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    return con


def _add_node(con: sqlite3.Connection, node_id: str, kind: str, name: str) -> None:
    con.execute(
        "INSERT INTO nodes (id, kind, name, qualname) VALUES (?, ?, ?, ?)",
        (node_id, kind, name, name),
    )


def _add_edge(con: sqlite3.Connection, src: str, rel: str, dst: str, evidence: str = "") -> None:
    con.execute(
        "INSERT INTO edges (src, rel, dst, evidence) VALUES (?, ?, ?, ?)",
        (src, rel, dst, evidence or None),
    )


def test_prune_ambiguous_drops_only_ambiguous_resolutions() -> None:
    con = _con()
    _add_edge(con, "sym:cancel", "RESOLVES_TO", "m:a.swift:A.cancel", AMBIGUOUS)
    _add_edge(con, "sym:cancel", "RESOLVES_TO", "m:b.swift:B.cancel", AMBIGUOUS)
    _add_edge(con, "sym:recordEntry", "RESOLVES_TO", "m:c.swift:Ledger.recordEntry", UNIQUE)
    con.commit()

    assert prune_ambiguous_resolutions(con) == 2
    survivors = [r[0] for r in con.execute("SELECT src FROM edges WHERE rel = 'RESOLVES_TO'")]
    assert survivors == ["sym:recordEntry"]


def test_prune_stdlib_members_drops_resolutions_for_library_names() -> None:
    con = _con()
    _add_node(con, "sym:append", "symbol", "append")
    _add_node(con, "sym:recordEntry", "symbol", "recordEntry")
    _add_edge(con, "sym:append", "RESOLVES_TO", "m:a.swift:FormData.append", UNIQUE)
    _add_edge(con, "sym:recordEntry", "RESOLVES_TO", "m:c.swift:Ledger.recordEntry", UNIQUE)
    con.commit()

    assert prune_stdlib_member_resolutions(con) == 1
    survivors = [r[0] for r in con.execute("SELECT src FROM edges WHERE rel = 'RESOLVES_TO'")]
    assert survivors == ["sym:recordEntry"]


def test_prune_extension_self_resolutions_breaks_the_self_link() -> None:
    """``extension Array`` is the only node named ``Array``; it must not resolve to itself."""
    con = _con()
    _add_node(con, "ext:a.swift:Array", "extension", "Array")
    _add_node(con, "sym:Array", "symbol", "Array")
    _add_edge(con, "ext:a.swift:Array", "EXTENDS", "sym:Array")
    _add_edge(con, "sym:Array", "RESOLVES_TO", "ext:a.swift:Array", UNIQUE)
    # A resolution to some *other* node is not self-referential and stays.
    _add_edge(con, "sym:Array", "RESOLVES_TO", "cls:b.swift:Array", UNIQUE)
    con.commit()

    assert prune_extension_self_resolutions(con) == 1
    survivors = [r[0] for r in con.execute("SELECT dst FROM edges WHERE rel = 'RESOLVES_TO'")]
    assert survivors == ["cls:b.swift:Array"]


def test_stdlib_member_names_cover_the_common_collisions() -> None:
    for name in ("append", "map", "count", "encode", "init", "removeAll"):
        assert name in SWIFT_STDLIB_MEMBER_NAMES


# ---------------------------------------------------------------------------
# End-to-end, over real Swift source
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")


def _build(repo: Path) -> SwiftKG:
    kg = SwiftKG(repo_root=repo)
    kg.build_graph(wipe=True)
    return kg


def _write(repo: Path, name: str, source: str) -> None:
    path = repo / "Sources" / "Pkg" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def test_every_stub_target_has_a_node(tmp_repo: Path) -> None:
    """No edge may point at an ID that no row defines."""
    kg = _build(tmp_repo)
    dangling = kg.store.con.execute(
        "SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON e.dst = n.id WHERE n.id IS NULL"
    ).fetchone()[0]
    kg.store.close()
    assert dangling == 0


def test_stub_records_the_relations_that_reference_it(tmp_repo: Path) -> None:
    kg = _build(tmp_repo)
    rows = dict(
        kg.store.con.execute("SELECT id, metadata FROM nodes WHERE kind = 'symbol'").fetchall()
    )
    kg.store.close()

    assert "CONFORMS" in rows["sym:AnyObject"]
    assert "IMPORTS" in rows["sym:Foundation"]
    assert "EXTENDS" in rows["sym:Result"]


def test_ambiguous_bare_name_stays_unresolved(tmp_repo: Path) -> None:
    """``extension Result`` extends the stdlib type, not the fixture's ``PathMonitor.Result``.

    Both are named ``Result``, so a bare-name match cannot separate them and
    must not pick one.  The fixture documents this invariant in its source.
    """
    kg = _build(tmp_repo)
    targets = kg.store.con.execute(
        "SELECT dst FROM edges WHERE rel = 'RESOLVES_TO' AND src = 'sym:Result'"
    ).fetchall()
    kg.store.close()
    assert targets == []


def test_unique_name_through_an_unknown_receiver_resolves(tmp_path: Path) -> None:
    """``ledger.recordEntry()`` has no receiver type, but only one such method exists."""
    repo = tmp_path / "repo"
    _write(
        repo,
        "Ledger.swift",
        "public struct Ledger {\n    public func recordEntry() {}\n}\n",
    )
    _write(
        repo,
        "Bookkeeper.swift",
        "public struct Bookkeeper {\n"
        "    func run() {\n"
        "        let ledger = makeLedger()\n"
        "        ledger.recordEntry()\n"
        "    }\n"
        "}\n",
    )
    kg = _build(repo)
    targets = [
        row[0]
        for row in kg.store.con.execute(
            "SELECT dst FROM edges WHERE rel = 'RESOLVES_TO' AND src = 'sym:recordEntry'"
        )
    ]
    kg.store.close()
    assert [t for t in targets if t.endswith("Ledger.recordEntry")]


def test_closure_parameter_call_emits_no_stub(tmp_path: Path) -> None:
    """``$0(...)`` invokes a closure parameter, which names no declaration."""
    repo = tmp_path / "repo"
    _write(
        repo,
        "Apply.swift",
        "public struct Apply {\n"
        "    func run(_ handlers: [() -> Void]) {\n"
        "        handlers.forEach { $0() }\n"
        "    }\n"
        "}\n",
    )
    kg = _build(repo)
    stubs = [row[0] for row in kg.store.con.execute("SELECT id FROM nodes WHERE kind = 'symbol'")]
    kg.store.close()
    assert not [s for s in stubs if "$" in s]


def test_build_hook_writes_resolutions(tmp_path: Path) -> None:
    """``SwiftKG.build_graph`` must run resolution, not just extraction."""
    repo = tmp_path / "repo"
    _write(repo, "Ledger.swift", "public struct Ledger {\n    public func recordEntry() {}\n}\n")
    _write(
        repo,
        "Bookkeeper.swift",
        "public struct Bookkeeper {\n"
        "    func run() {\n"
        "        let ledger = makeLedger()\n"
        "        ledger.recordEntry()\n"
        "    }\n"
        "}\n",
    )
    kg = _build(repo)
    count = kg.store.con.execute("SELECT COUNT(*) FROM edges WHERE rel = 'RESOLVES_TO'").fetchone()[
        0
    ]
    kg.store.close()
    assert count > 0


def test_resolve_symbols_pruned_reports_net_kept(tmp_repo: Path) -> None:
    kg = _build(tmp_repo)
    kg.store.con.execute("DELETE FROM edges WHERE rel = 'RESOLVES_TO'")
    kg.store.con.commit()

    kept = resolve_symbols_pruned(kg.store)
    actual = kg.store.con.execute(
        "SELECT COUNT(*) FROM edges WHERE rel = 'RESOLVES_TO'"
    ).fetchone()[0]
    kg.store.close()
    assert kept == actual
