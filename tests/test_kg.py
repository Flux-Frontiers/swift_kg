"""
test_kg.py — the SwiftKG module: build, lookup, validation, Swift surface.

Most of this needs no embedding model: ``build_graph()`` writes SQLite without
touching the vector index, which is what lets the Swift-specific graph surface
(``conformers``, ``subclasses``, ``extensions_of``) be tested in ordinary CI
rather than behind the ``integration`` marker. Only the tests that actually
issue a semantic query carry that marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swift_kg.extractor import _HAS_TREE_SITTER
from swift_kg.kg import SwiftKG

pytestmark = pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")


@pytest.fixture
def kg(tmp_repo: Path, tmp_path: Path):
    """A SwiftKG with the graph built but no vector index."""
    instance = SwiftKG(
        repo_root=tmp_repo,
        db_path=tmp_path / "graph.sqlite",
        vectors_path=tmp_path / "vectors.sqlite",
    )
    instance.build_graph(wipe=True)
    yield instance
    instance.close()


def _id(kg: SwiftKG, qualname: str) -> str:
    row = kg.store.con.execute(
        "SELECT id FROM nodes WHERE qualname = ? AND id NOT LIKE 'sym:%'", (qualname,)
    ).fetchone()
    assert row, f"no node with qualname {qualname!r}"
    return row[0]


class TestBuild:
    def test_graph_is_populated(self, kg: SwiftKG) -> None:
        stats = kg.stats()
        assert stats["total_nodes"] > 0
        assert stats["total_edges"] > 0

    def test_every_swift_kind_is_stored(self, kg: SwiftKG) -> None:
        counts = kg.stats()["node_counts"]
        for kind in ("class", "struct", "enum", "protocol", "actor", "extension"):
            assert counts.get(kind, 0) > 0, f"no {kind} nodes were stored"

    def test_conformance_and_inheritance_are_separate_relations(self, kg: SwiftKG) -> None:
        counts = kg.stats()["edge_counts"]
        assert counts.get("CONFORMS", 0) > 0
        assert counts.get("INHERITS", 0) > 0

    def test_rebuild_is_idempotent(self, kg: SwiftKG) -> None:
        before = kg.stats()["total_nodes"]
        kg.build_graph(wipe=True)
        assert kg.stats()["total_nodes"] == before

    def test_kind_is_code(self, kg: SwiftKG) -> None:
        assert kg.kind() == "code"


class TestArtefactPaths:
    def test_default_directory_is_dot_swiftkg(self, tmp_repo: Path) -> None:
        instance = SwiftKG(repo_root=tmp_repo)
        assert instance.db_path.parent.name == ".swiftkg"
        instance.close()

    def test_explicit_paths_are_honoured(self, tmp_repo: Path, tmp_path: Path) -> None:
        instance = SwiftKG(
            repo_root=tmp_repo,
            db_path=tmp_path / "a.sqlite",
            vectors_path=tmp_path / "b.sqlite",
        )
        assert instance.db_path == tmp_path / "a.sqlite"
        assert instance.vectors_path == tmp_path / "b.sqlite"
        instance.close()


class TestSwiftGraphSurface:
    """The three questions a Swift reader asks that CALLS cannot answer."""

    def test_conformers_finds_implementations_of_a_protocol(self, kg: SwiftKG) -> None:
        conformers = kg.conformers(_id(kg, "Repository"))
        assert {c["name"] for c in conformers} >= {"Storage"}

    def test_subclasses_finds_derived_classes(self, kg: SwiftKG) -> None:
        subclasses = kg.subclasses(_id(kg, "Storage"))
        assert {c["name"] for c in subclasses} == {"DiskStorage"}

    def test_conformance_does_not_leak_into_subclasses(self, kg: SwiftKG) -> None:
        """The point of the two-pass resolver: these are different questions."""
        subclasses = {c["name"] for c in kg.subclasses(_id(kg, "Repository"))}
        assert "Storage" not in subclasses

    def test_extensions_of_finds_the_extension(self, kg: SwiftKG) -> None:
        extensions = kg.extensions_of(_id(kg, "Point"))
        assert extensions and all(e["kind"] == "extension" for e in extensions)

    def test_declared_relations_are_exposed(self) -> None:
        assert SwiftKG.edge_relations() == {
            "CONTAINS",
            "IMPORTS",
            "CALLS",
            "INHERITS",
            "CONFORMS",
            "EXTENDS",
        }


class TestLookup:
    def test_node_round_trips(self, kg: SwiftKG) -> None:
        node_id = _id(kg, "Point")
        assert kg.node(node_id)["kind"] == "struct"

    def test_node_accepts_a_backtick_wrapped_id(self, kg: SwiftKG) -> None:
        """IDs get pasted out of Markdown reports as often as from tool output."""
        node_id = _id(kg, "Point")
        assert kg.node(f"`{node_id}`") is not None

    def test_unknown_node_returns_none(self, kg: SwiftKG) -> None:
        assert kg.node("cls:nope.swift:Nope") is None


class TestValidation:
    """Validated once here, so the CLI and the MCP server are both covered."""

    @pytest.mark.parametrize(("field", "value"), [("k", 0), ("k", 101), ("hop", -1), ("hop", 6)])
    def test_query_rejects_out_of_range_values(self, kg: SwiftKG, field: str, value: int) -> None:
        with pytest.raises(ValueError, match=field):
            kg.query("anything", **{field: value})

    def test_query_rejects_an_empty_query(self, kg: SwiftKG) -> None:
        with pytest.raises(ValueError, match="empty"):
            kg.query("   ")

    def test_pack_rejects_an_over_long_query(self, kg: SwiftKG) -> None:
        with pytest.raises(ValueError, match="at most"):
            kg.pack("a" * 501)

    def test_pack_rejects_an_out_of_range_max_lines(self, kg: SwiftKG) -> None:
        with pytest.raises(ValueError, match="max_lines"):
            kg.pack("anything", max_lines=99_999)

    def test_callers_rejects_an_unknown_relation(self, kg: SwiftKG) -> None:
        with pytest.raises(ValueError, match="rel must be"):
            kg.callers(_id(kg, "Point"), rel="IMPLEMENTS")

    def test_node_rejects_an_empty_id(self, kg: SwiftKG) -> None:
        with pytest.raises(ValueError, match="empty"):
            kg.node("")


class TestContextManager:
    def test_enter_returns_the_subclass(self, tmp_repo: Path, tmp_path: Path) -> None:
        """Narrowed from the base's `-> KGModule` so `ty` keeps the surface."""
        with SwiftKG(repo_root=tmp_repo, db_path=tmp_path / "g.sqlite") as instance:
            assert isinstance(instance, SwiftKG)
            assert instance.edge_relations()

    def test_repr_names_the_class(self, kg: SwiftKG) -> None:
        assert repr(kg).startswith("SwiftKG(")


class TestKindPriority:
    def test_protocols_rank_above_concrete_types(self, kg: SwiftKG) -> None:
        assert kg._kind_priority("protocol") < kg._kind_priority("struct")

    def test_types_rank_above_their_members(self, kg: SwiftKG) -> None:
        assert kg._kind_priority("class") < kg._kind_priority("method")

    def test_unknown_kind_sorts_last(self, kg: SwiftKG) -> None:
        assert kg._kind_priority("widget") == 99


@pytest.mark.integration
class TestSemanticPipeline:
    """Needs the real embedding model. Run with: pytest -m integration"""

    @pytest.fixture
    def built(self, tmp_repo: Path, tmp_path: Path):
        instance = SwiftKG(
            repo_root=tmp_repo,
            db_path=tmp_path / "graph.sqlite",
            vectors_path=tmp_path / "vectors.sqlite",
        )
        instance.build(wipe=True)
        yield instance
        instance.close()

    def test_query_returns_nodes(self, built: SwiftKG) -> None:
        result = built.query("storage repository", k=5)
        assert result.nodes

    def test_pack_returns_source_snippets(self, built: SwiftKG) -> None:
        pack = built.pack("storage repository", k=5)
        assert pack.nodes
        assert any(n.get("snippet") for n in pack.nodes)

    def test_analyze_returns_markdown(self, built: SwiftKG) -> None:
        report = built.analyze()
        assert report.startswith("# SwiftKG")
