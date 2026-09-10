"""
test_extractor.py — unit tests for SwiftCodeExtractor.

Covers the three grammar traps that would each produce a silently wrong graph
rather than an error, plus the two-pass resolver that separates inheritance
from conformance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swift_kg.extractor import _HAS_TREE_SITTER, SwiftCodeExtractor

pytestmark = pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed")


def _extract(repo: Path) -> tuple[list, list]:
    nodes, edges = [], []
    for item in SwiftCodeExtractor(repo).extract():
        (nodes if hasattr(item, "node_id") else edges).append(item)
    return nodes, edges


def _kinds(nodes: list, kind: str) -> list:
    return [n for n in nodes if n.kind == kind]


def _named(nodes: list, name: str) -> list:
    return [n for n in nodes if n.name == name]


def _rel(edges: list, relation: str) -> list:
    return [e for e in edges if e.relation == relation]


def _pairs(edges: list, relation: str) -> set[tuple[str, str]]:
    """Return (source qualname-ish, target tail) pairs for readable assertions."""
    return {
        (e.source_id.rsplit(":", 1)[-1], e.target_id.rsplit(":", 1)[-1])
        for e in _rel(edges, relation)
    }


# ---------------------------------------------------------------------------
# Grammar trap 1: class_declaration is overloaded
# ---------------------------------------------------------------------------


class TestDeclarationKinds:
    """`class_declaration` covers class, struct, enum, actor and extension.

    They differ only by the `declaration_kind` field. Matching on node type
    alone files all five as classes, which is wrong without being an error --
    exactly the kind of defect a test has to catch, because nothing else will.
    """

    def test_struct_is_not_a_class(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        point = _named(nodes, "Point")
        assert {n.kind for n in point} == {"struct", "extension"}

    def test_actor_is_its_own_kind(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert [n.kind for n in _named(nodes, "Counter")] == ["actor"]

    def test_enum_is_its_own_kind(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert [n.kind for n in _named(nodes, "StorageError")] == ["enum"]

    def test_protocol_is_its_own_kind(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert [n.kind for n in _named(nodes, "Repository")] == ["protocol"]

    def test_class_is_still_a_class(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert [n.kind for n in _named(nodes, "Storage")] == ["class"]

    def test_every_declared_kind_appears(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        found = {n.kind for n in nodes}
        assert {"module", "class", "struct", "enum", "protocol", "actor", "extension"} <= found


# ---------------------------------------------------------------------------
# Grammar trap 2: function_declaration carries two `name` fields
# ---------------------------------------------------------------------------


class TestMemberNames:
    def test_method_name_is_not_the_return_type(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        # `func distance(to other: Point) -> Double` has `name` fields for
        # both `distance` and `Double`; the first is the one that matters.
        distance = _named(nodes, "distance")
        assert len(distance) == 1
        assert distance[0].qualname == "Point.distance"

    def test_deinit_is_named(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "deinit"), "deinit_declaration has no name field to read"


# ---------------------------------------------------------------------------
# Grammar trap 3: call_expression has no `function` field
# ---------------------------------------------------------------------------


class TestCallEdges:
    def test_calls_are_emitted_at_all(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert _rel(edges, "CALLS"), (
            "no CALLS edges: call_expression exposes its callee as a child, "
            "not through a `function` field"
        )

    def test_call_resolves_across_files(self, tmp_repo: Path) -> None:
        """Swift has no per-file imports within a module, so this must resolve.

        `Counter.increment` is in SampleApp and `logAccess` is in SampleKit,
        with no import between them. A per-file walker cannot connect these.
        """
        _, edges = _extract(tmp_repo)
        calls = _rel(edges, "CALLS")
        cross = [
            e
            for e in calls
            if "Counter.increment" in e.source_id and e.target_id.endswith(":logAccess")
        ]
        assert cross, "cross-file call did not resolve"
        assert "SampleKit" in cross[0].target_id

    def test_super_call_resolves_to_superclass_member(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("DiskStorage.fetch", "Storage.fetch") in _pairs(edges, "CALLS")

    def test_initializer_call_targets_the_type(self, tmp_repo: Path) -> None:
        """`Point(x:y:)` is written like a function call on the type's name."""
        _, edges = _extract(tmp_repo)
        targets = {e.target_id for e in _rel(edges, "CALLS") if "Point.scaled" in e.source_id}
        assert any(t.startswith("struct:") and t.endswith(":Point") for t in targets)

    def test_subscript_access_is_not_a_call(self, tmp_repo: Path) -> None:
        """`items[id]` parses as a call_expression but calls nothing."""
        _, edges = _extract(tmp_repo)
        assert ("Storage.fetch", "Storage.items") not in _pairs(edges, "CALLS")

    def test_unresolved_call_becomes_a_stub(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("logAccess", "print") in _pairs(edges, "CALLS")
        stub = next(e for e in _rel(edges, "CALLS") if e.target_id == "sym:print")
        assert stub.target_id.startswith("sym:")


# ---------------------------------------------------------------------------
# The two-pass resolver: INHERITS vs CONFORMS
# ---------------------------------------------------------------------------


class TestInheritanceResolution:
    """`: Base, Proto` is written identically for both, so this is inferred."""

    def test_resolved_class_target_is_inheritance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("DiskStorage", "Storage") in _pairs(edges, "INHERITS")

    def test_resolved_protocol_target_is_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("DiskStorage", "Auditable") in _pairs(edges, "CONFORMS")
        assert ("DiskStorage", "Auditable") not in _pairs(edges, "INHERITS")

    def test_struct_never_inherits(self, tmp_repo: Path) -> None:
        """A struct cannot have a superclass, so both targets are protocols."""
        _, edges = _extract(tmp_repo)
        assert ("Point", "Equatable") in _pairs(edges, "CONFORMS")
        assert ("Point", "Hashable") in _pairs(edges, "CONFORMS")
        assert not [e for e in _rel(edges, "INHERITS") if e.source_id.startswith("struct:")]

    def test_unresolved_first_target_on_a_class_is_inheritance(self, tmp_repo: Path) -> None:
        """`class Storage<T>: NSObject, Repository` -- NSObject is external.

        Nothing in the graph knows what NSObject is, so this falls back to the
        language rule: only a class may have a superclass, written first.
        """
        _, edges = _extract(tmp_repo)
        assert ("Storage", "NSObject") in _pairs(edges, "INHERITS")

    def test_later_unresolved_target_on_a_class_is_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("Storage", "Repository") in _pairs(edges, "CONFORMS")

    def test_protocol_refinement_is_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("Repository", "AnyObject") in _pairs(edges, "CONFORMS")


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------


class TestExtensions:
    def test_extension_gets_its_own_node(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _kinds(nodes, "extension")

    def test_extension_points_at_the_extended_type(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        extends = [
            e for e in _rel(edges, "EXTENDS") if e.source_id.rsplit(":", 1)[-1].startswith("Point")
        ]
        assert extends
        assert all(e.target_id.endswith(":Point") for e in extends)
        assert all(e.target_id.startswith("struct:") for e in extends)

    def test_two_extensions_on_one_type_get_distinct_ids(self, tmp_repo: Path) -> None:
        """Swift allows any number of extensions on a type in one file.

        Keying on the extended type alone collides, and the store upserts by
        node ID, so the second would silently overwrite the first.
        """
        nodes, _ = _extract(tmp_repo)
        extensions = [n for n in _kinds(nodes, "extension") if n.name == "Point"]
        assert len(extensions) == 2
        assert len({n.node_id for n in extensions}) == 2

    def test_extension_id_names_its_conformance(self, tmp_repo: Path) -> None:
        """The conformance list is the discriminator, not a line number.

        It is stable under edits elsewhere in the file, and it is how the
        extension is actually referred to.
        """
        nodes, _ = _extract(tmp_repo)
        ids = {n.node_id for n in _kinds(nodes, "extension")}
        assert any(i.endswith(":Point+CustomStringConvertible") for i in ids)

    def test_every_extension_still_points_at_the_type(self, tmp_repo: Path) -> None:
        """Both extensions on `Point` emit an edge; the second is not lost."""
        _, edges = _extract(tmp_repo)
        to_point = [e for e in _rel(edges, "EXTENDS") if e.target_id.endswith(":Point")]
        assert len(to_point) == 2

    def test_extension_members_are_qualified_under_the_type(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        scaled = _named(nodes, "scaled")
        assert len(scaled) == 1
        assert scaled[0].qualname == "Point.scaled"
        assert scaled[0].kind == "method"

    def test_extension_conformance_is_conformance_not_inheritance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        # The source is the extension node, whose qualname carries the
        # conformance that disambiguates it from Point's other extension.
        assert ("Point+CustomStringConvertible", "CustomStringConvertible") in _pairs(
            edges, "CONFORMS"
        )
        assert not [e for e in _rel(edges, "INHERITS") if e.source_id.startswith("ext:")]


# ---------------------------------------------------------------------------
# Doc comments, nesting, visibility, conditional compilation
# ---------------------------------------------------------------------------


class TestDocComments:
    def test_triple_slash_run_is_captured(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "Point")[0].docstring == "A point in two dimensions."

    def test_block_doc_comment_is_captured(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        storage_mod = [n for n in nodes if n.kind == "module" and "Storage" in n.qualname]
        assert storage_mod[0].docstring == "Storage primitives for SampleKit."

    def test_member_doc_comment_is_captured(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        fetch = next(n for n in nodes if n.qualname == "Storage.fetch")
        assert fetch.docstring == "Fetch an item by identifier."

    def test_undocumented_member_has_empty_docstring(self, tmp_repo: Path) -> None:
        """A protocol requirement with no `///` above it must not inherit one."""
        nodes, _ = _extract(tmp_repo)
        requirement = next(n for n in nodes if n.qualname == "Repository.fetch")
        assert requirement.docstring == ""

    def test_doc_comment_is_not_stolen_from_a_preceding_declaration(self, tmp_repo: Path) -> None:
        """`var y: Double` follows a documented `var x` and has no doc of its own."""
        nodes, _ = _extract(tmp_repo)
        y = next(n for n in nodes if n.qualname == "Point.y")
        assert y.docstring == ""


class TestNesting:
    def test_nested_type_is_qualified(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        inner = _named(nodes, "Inner")
        assert inner[0].qualname == "DiskStorage.Inner"

    def test_nested_member_is_fully_qualified(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "deep")[0].qualname == "DiskStorage.Inner.deep"


class TestVisibility:
    def test_public_is_recorded(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "Point")[0].metadata["visibility"] == "public"

    def test_open_is_distinct_from_public(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "Storage")[0].metadata["visibility"] == "open"

    def test_private_is_recorded(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "items")[0].metadata["visibility"] == "private"

    def test_unmodified_declaration_defaults_to_internal(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "logAccess")[0].metadata["visibility"] == "internal"


class TestConditionalCompilation:
    def test_declaration_inside_if_directive_is_indexed(self, tmp_repo: Path) -> None:
        """`#if DEBUG` leaves its declarations as top-level siblings."""
        nodes, _ = _extract(tmp_repo)
        assert _named(nodes, "debugDump")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class TestImports:
    def test_import_becomes_a_module_stub(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        targets = {e.target_id for e in _rel(edges, "IMPORTS")}
        assert "sym:Foundation" in targets

    def test_local_spm_target_is_flagged(self, tmp_repo: Path) -> None:
        """A `Sources/<Target>/` directory makes an import first-party."""
        _, edges = _extract(tmp_repo)
        local = [e for e in _rel(edges, "IMPORTS") if e.target_id == "sym:SampleApp"]
        assert local and local[0].metadata["local"] is True

    def test_third_party_import_is_not_flagged(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        foundation = [e for e in _rel(edges, "IMPORTS") if e.target_id == "sym:Foundation"]
        assert foundation and foundation[0].metadata["local"] is False


# ---------------------------------------------------------------------------
# Extractor protocol
# ---------------------------------------------------------------------------


class TestExtractorProtocol:
    def test_declared_kinds_cover_what_is_emitted(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        extractor = SwiftCodeExtractor(tmp_repo)
        assert {n.kind for n in nodes} <= set(extractor.node_kinds())

    def test_declared_relations_cover_what_is_emitted(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        extractor = SwiftCodeExtractor(tmp_repo)
        assert {e.relation for e in edges} <= set(extractor.edge_kinds())

    def test_symbol_stubs_are_not_semantically_indexed(self) -> None:
        extractor = SwiftCodeExtractor(Path("."))
        assert "symbol" not in extractor.meaningful_node_kinds()

    def test_extraction_is_deterministic(self, tmp_repo: Path) -> None:
        first = [(i.__class__.__name__, str(i)) for i in SwiftCodeExtractor(tmp_repo).extract()]
        second = [(i.__class__.__name__, str(i)) for i in SwiftCodeExtractor(tmp_repo).extract()]
        assert first == second

    def test_node_ids_are_unique(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        ids = [n.node_id for n in nodes]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Access-level rules
# ---------------------------------------------------------------------------


class TestAccessLevelRules:
    """Swift's default is `internal` in most places, but not everywhere."""

    def test_public_extension_makes_members_public(self, tmp_repo: Path) -> None:
        """`public extension` confers public access on members declaring none.

        A `public class` does *not* work this way, which is why the level is
        carried per scope rather than inherited by every type.
        """
        nodes, _ = _extract(tmp_repo)
        inverted = next(n for n in nodes if n.qualname == "Point.inverted")
        assert inverted.metadata["visibility"] == "public"

    def test_public_class_members_still_default_to_internal(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        audit = next(n for n in nodes if n.qualname == "GeometryModel.audit")
        assert audit.metadata["visibility"] == "public"  # explicitly marked
        fetch = next(n for n in nodes if n.qualname == "Storage.fetch")
        assert fetch.metadata["visibility"] == "public"  # explicitly marked
        deep = next(n for n in nodes if n.qualname == "DiskStorage.Inner.deep")
        assert deep.metadata["visibility"] == "internal"  # unmodified

    def test_protocol_requirement_takes_the_protocol_level(self, tmp_repo: Path) -> None:
        """A requirement cannot declare an access level different from its protocol."""
        nodes, _ = _extract(tmp_repo)
        measure = next(n for n in nodes if n.qualname == "Measurable.measure")
        assert measure.metadata["visibility"] == "public"

    def test_explicit_modifier_beats_the_inherited_one(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        items = next(n for n in nodes if n.qualname == "Storage.items")
        assert items.metadata["visibility"] == "private"


class TestMultipleBindings:
    def test_every_name_in_one_declaration_is_captured(self, tmp_repo: Path) -> None:
        """`let first: Double, second: Double` binds two names, not one."""
        nodes, _ = _extract(tmp_repo)
        qualnames = {n.qualname for n in nodes}
        assert {"Pair.first", "Pair.second"} <= qualnames


class TestExternalProtocolClassification:
    """A well-known external protocol must not be mistaken for a superclass."""

    def test_known_external_protocol_is_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("GeometryModel", "ObservableObject") in _pairs(edges, "CONFORMS")

    def test_it_is_not_recorded_as_inheritance(self, tmp_repo: Path) -> None:
        """The positional heuristic alone would invent a superclass here."""
        _, edges = _extract(tmp_repo)
        assert ("GeometryModel", "ObservableObject") not in _pairs(edges, "INHERITS")

    def test_an_unknown_first_specifier_is_still_inheritance(self, tmp_repo: Path) -> None:
        """The heuristic still applies to names the list does not cover."""
        _, edges = _extract(tmp_repo)
        assert ("Storage", "NSObject") in _pairs(edges, "INHERITS")

    def test_a_later_known_protocol_is_still_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("GeometryModel", "Auditable") in _pairs(edges, "CONFORMS")


# ---------------------------------------------------------------------------
# Scoped name resolution
# ---------------------------------------------------------------------------


class TestNestedTypeScoping:
    """A nested type must not capture same-named references from outside it.

    Swift makes `PathMonitor.Result` invisible under its bare name outside
    `PathMonitor`, so a repo-wide index keyed on bare names lets one uniquely
    named nested type absorb every reference to the standard library's type of
    that name.
    """

    def test_nested_type_is_keyed_by_its_qualified_name(self, tmp_repo: Path) -> None:
        nodes, _ = _extract(tmp_repo)
        assert any(n.qualname == "PathMonitor.Result" and n.kind == "enum" for n in nodes)

    def test_file_scope_extension_does_not_attach_to_a_nested_type(self, tmp_repo: Path) -> None:
        """`extension Result` extends the standard library's type, not the nested one."""
        _, edges = _extract(tmp_repo)
        assert ("Result", "Result") in _pairs(edges, "EXTENDS")
        assert ("Result", "PathMonitor.Result") not in _pairs(edges, "EXTENDS")

    def test_the_unresolved_target_is_an_honest_stub(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        extends = next(e for e in _rel(edges, "EXTENDS") if e.source_id.endswith(":Result"))
        assert extends.target_id == "sym:Result"

    def test_nothing_outside_the_declaring_type_references_it(self, tmp_repo: Path) -> None:
        nested = "enum:Sources/SampleKit/Storage.swift:PathMonitor.Result"
        _, edges = _extract(tmp_repo)
        sources = {e.source_id for e in edges if e.target_id == nested}
        assert all("PathMonitor" in src for src in sources)

    def test_the_declaring_scope_still_resolves_the_bare_name(self, tmp_repo: Path) -> None:
        """The fix must not cost recall inside the type that declares it.

        `Config(timeout:)` inside `PathMonitor` is the bare name Swift resolves,
        so it still has to reach `PathMonitor.Config`.
        """
        _, edges = _extract(tmp_repo)
        assert ("PathMonitor.makeConfig", "PathMonitor.Config") in _pairs(edges, "CALLS")


# ---------------------------------------------------------------------------
# Enum raw values
# ---------------------------------------------------------------------------


class TestEnumRawValues:
    """`enum Section: Int` writes a raw type where a conformance would go."""

    def test_a_raw_value_type_is_not_a_conformance(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("Section", "Int") not in _pairs(edges, "CONFORMS")

    def test_it_is_not_recorded_as_inheritance_either(self, tmp_repo: Path) -> None:
        _, edges = _extract(tmp_repo)
        assert ("Section", "Int") not in _pairs(edges, "INHERITS")

    def test_a_conformance_after_the_raw_type_survives(self, tmp_repo: Path) -> None:
        """`enum Label: String, Auditable` drops `String` and keeps `Auditable`."""
        _, edges = _extract(tmp_repo)
        assert ("Label", "String") not in _pairs(edges, "CONFORMS")
        assert ("Label", "Auditable") in _pairs(edges, "CONFORMS")

    def test_a_non_raw_first_specifier_is_still_a_conformance(self, tmp_repo: Path) -> None:
        """Only literal-backed types are raw values; `enum StorageError: Error` is not."""
        _, edges = _extract(tmp_repo)
        assert ("StorageError", "Error") in _pairs(edges, "CONFORMS")
