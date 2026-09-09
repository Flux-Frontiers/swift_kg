"""
test_explain.py — Markdown node explanations.

The role labels are kind-aware, and Swift's kinds are not TypeScript's: a
struct is "Constructed", a protocol is "Conformed to". The zero-caller
heuristics matter more here than in the sibling modules, because Swift reaches
a large share of its surface through protocol witnesses and framework dispatch
that never appear as a call edge.
"""

from __future__ import annotations

from typing import Any

import pytest

from swift_kg.explain import render_explain


class FakeKG:
    """Minimal stand-in exposing the four members render_explain uses."""

    def __init__(self, nodes: dict[str, dict], callers: dict[str, list] | None = None) -> None:
        self._nodes = nodes
        self._callers = callers or {}
        self._store = None

    def node(self, node_id: str) -> dict | None:
        return self._nodes.get(node_id)

    def callers(self, node_id: str, *, rel: str = "CALLS") -> list[dict[str, Any]]:
        return self._callers.get((node_id, rel), self._callers.get(node_id, []))

    def stats(self) -> dict:
        return {"meaningful_nodes": 200}


def _node(node_id: str, kind: str, name: str, **extra: Any) -> dict:
    base = {
        "id": node_id,
        "kind": kind,
        "name": name,
        "qualname": extra.pop("qualname", name),
        "module_path": extra.pop("module_path", "Sources/App/File.swift"),
        "lineno": 1,
        "end_lineno": 10,
        "docstring": extra.pop("docstring", ""),
    }
    base.update(extra)
    return base


class TestMissingNode:
    def test_unknown_id_is_reported_not_raised(self) -> None:
        out = render_explain(FakeKG({}), "cls:nope:Nope")
        assert out.startswith("# Node Not Found")


class TestHeaderAndMetadata:
    def test_header_names_the_kind(self) -> None:
        node_id = "struct:Sources/Model/Point.swift:Point"
        kg = FakeKG({node_id: _node(node_id, "struct", "Point")})
        assert render_explain(kg, node_id).startswith("# Struct: `Point`")

    def test_docstring_is_rendered(self) -> None:
        node_id = "struct:Sources/Model/Point.swift:Point"
        kg = FakeKG({node_id: _node(node_id, "struct", "Point", docstring="A 2-D point.")})
        assert "A 2-D point." in render_explain(kg, node_id)


class TestKindAwareRoles:
    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("struct", "Constructed"),
            ("class", "Constructed"),
            ("actor", "Constructed"),
            ("protocol", "Conformed to"),
            ("function", "Called"),
        ],
    )
    def test_verb_matches_the_kind(self, kind: str, expected: str) -> None:
        node_id = f"{kind}:Sources/App/File.swift:Thing"
        callers = [_node(f"fn:Sources/App/c{i}.swift:c{i}", "function", f"c{i}") for i in range(6)]
        kg = FakeKG({node_id: _node(node_id, kind, "Thing")}, {node_id: callers})
        assert expected in render_explain(kg, node_id)


class TestZeroCallerHeuristics:
    """Swift's zero-caller population is large and mostly not dead code."""

    def test_protocol_witness_is_not_called_dead(self) -> None:
        node_id = "meth:Sources/Model/Point.swift:Point.description"
        kg = FakeKG({node_id: _node(node_id, "property", "description")})
        out = render_explain(kg, node_id)
        assert "Protocol witness" in out
        assert "Orphaned" not in out

    def test_swiftui_body_is_not_called_dead(self) -> None:
        node_id = "prop:Sources/Views/HomeView.swift:HomeView.body"
        kg = FakeKG({node_id: _node(node_id, "property", "body")})
        assert "Orphaned" not in render_explain(kg, node_id)

    def test_public_declaration_is_not_called_dead(self) -> None:
        """A public API's callers are outside the indexed module by design."""
        node_id = "fn:Sources/App/File.swift:doThing"
        kg = FakeKG({node_id: _node(node_id, "function", "doThing", visibility="public")})
        out = render_explain(kg, node_id)
        assert "Public API surface" in out
        assert "Orphaned" not in out

    def test_type_level_declaration_is_not_called_dead(self) -> None:
        node_id = "proto:Sources/Model/Drawable.swift:Drawable"
        kg = FakeKG({node_id: _node(node_id, "protocol", "Drawable")})
        assert "Type-level declaration" in render_explain(kg, node_id)

    def test_test_code_is_not_called_dead(self) -> None:
        node_id = "meth:Tests/AppTests/PointTests.swift:PointTests.checkThing"
        kg = FakeKG(
            {
                node_id: _node(
                    node_id,
                    "method",
                    "checkThing",
                    module_path="Tests/AppTests/PointTests.swift",
                )
            }
        )
        assert "Test code" in render_explain(kg, node_id)

    def test_genuinely_unreferenced_internal_function_is_flagged(self) -> None:
        node_id = "fn:Sources/App/File.swift:unusedHelper"
        kg = FakeKG({node_id: _node(node_id, "function", "unusedHelper", visibility="internal")})
        assert "Orphaned" in render_explain(kg, node_id)


class TestSnippetHint:
    def test_hint_is_configurable_for_each_surface(self) -> None:
        node_id = "fn:Sources/App/File.swift:doThing"
        kg = FakeKG({node_id: _node(node_id, "function", "doThing")})
        assert "swiftkg pack" in render_explain(kg, node_id, snippets_hint="swiftkg pack")
        assert "pack_snippets()" in render_explain(kg, node_id)
