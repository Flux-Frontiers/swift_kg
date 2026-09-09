#!/usr/bin/env python3
"""
extractor.py — Swift AST extractor for SwiftKG.

Uses tree-sitter to parse ``.swift`` files and emit NodeSpec / EdgeSpec objects
for the KGModule build pipeline.

Node kinds:
  module      — every indexed source file
  class       — class declaration
  struct      — struct declaration
  enum        — enum declaration
  protocol    — protocol declaration
  actor       — actor declaration
  extension   — extension declaration
  function    — free function (file scope, or nested in a namespace-like scope)
  method      — function / initializer / deinitializer / subscript inside a type
  property    — stored or computed property, and file-scope `let` / `var`
  typealias   — type alias (and `associatedtype` inside a protocol)
  symbol      — unresolved import or call stub

Edge relations:
  CONTAINS    — module→type/function, type→member
  IMPORTS     — module→`sym:<Module>` (Swift imports name modules, not files)
  CALLS       — function/method→function/method/type-initializer
  INHERITS    — class/actor→superclass
  CONFORMS    — type/extension→protocol
  EXTENDS     — extension→extended type

Two passes, and why
-------------------
Swift writes superclass inheritance and protocol conformance with identical
syntax (``: Base, Proto``), so a declaration alone never says which it is.
Pass 1 builds a repo-wide symbol table of declared type names and their kinds;
pass 2 resolves each inheritance specifier against it — a protocol target
yields CONFORMS, a class or actor target yields INHERITS — and falls back to
the language rule (only a class or actor has a superclass, written first) when
the target is external and therefore unresolvable.

The table pays for itself twice. Swift has no per-file imports *within* a
module: every file in a target sees every other file's declarations. So calls
and type references resolve across the whole repository, where a single-file
walker could only resolve within one file.

The cost is parsing each file twice rather than holding every tree in memory
at once; tree-sitter parses far faster than a large repo's trees fit in RAM.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kg_utils.extractor import KGExtractor
from kg_utils.specs import EdgeSpec, NodeSpec

try:
    import tree_sitter_swift as _tss
    from tree_sitter import Language, Parser

    # tree_sitter_swift 0.7.x's `language()` returns the grammar as an int
    # rather than the PyCapsule newer bindings hand back, so `Language()`
    # takes its deprecated overload. There is no other entry point in that
    # release; drop the suppression when tree-sitter-swift ships a capsule.
    _SWIFT_LANGUAGE = Language(_tss.language())  # ty: ignore[deprecated]
    _HAS_TREE_SITTER = True
except Exception:  # noqa: BLE001
    _HAS_TREE_SITTER = False

__all__ = [
    "SwiftCodeExtractor",
    "SymbolTable",
    "SKIP_DIRS",
    "SWIFT_EXTENSIONS",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Directories never indexed. Beyond the usual VCS/venv noise these are the
#: Swift-ecosystem build and dependency sinks: SwiftPM's ``.build`` and
#: ``.swiftpm``, Xcode's ``DerivedData`` and per-user state, and the vendored
#: trees CocoaPods and Carthage check in.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".build",
        ".swiftpm",
        "DerivedData",
        "Pods",
        "Carthage",
        "Checkouts",
        "xcuserdata",
        ".git",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        "fastlane",
        "vendor",
        ".swiftkg",
        ".pycodekg",
        ".dockg",
        ".agentkg",
        ".tscodekg",
    }
)

#: Directory *suffixes* skipped at every depth. Xcode project and workspace
#: bundles are directories, not files, and the `.swift` files inside them are
#: generated stubs rather than source.
SKIP_DIR_SUFFIXES: tuple[str, ...] = (".xcodeproj", ".xcworkspace", ".xcassets", ".framework")

SWIFT_EXTENSIONS: frozenset[str] = frozenset({".swift"})

_KIND_PREFIX: dict[str, str] = {
    "module": "mod",
    "class": "cls",
    "struct": "struct",
    "enum": "enum",
    "protocol": "proto",
    "actor": "actor",
    "extension": "ext",
    "function": "fn",
    "method": "meth",
    "property": "prop",
    "typealias": "type",
    "symbol": "sym",
}

#: ``class_declaration`` is overloaded in the Swift grammar: it covers class,
#: struct, enum, actor *and* extension, distinguished only by the
#: ``declaration_kind`` field. Matching on node type alone files every struct,
#: enum, actor and extension in a repo as a class.
_DECLARATION_KIND_TO_NODE_KIND: dict[str, str] = {
    "class": "class",
    "struct": "struct",
    "enum": "enum",
    "actor": "actor",
    "extension": "extension",
    "protocol": "protocol",
}

#: Type-like declarations that own a body of members.
_TYPE_DECL_NODES = frozenset({"class_declaration", "protocol_declaration"})

_BODY_NODES = frozenset({"class_body", "enum_class_body", "protocol_body"})

#: Member declarations found inside a type body.
_FUNCTION_MEMBERS = frozenset(
    {
        "function_declaration",
        "protocol_function_declaration",
        "init_declaration",
        "deinit_declaration",
        "subscript_declaration",
    }
)

_PROPERTY_MEMBERS = frozenset({"property_declaration", "protocol_property_declaration"})

_TYPEALIAS_MEMBERS = frozenset({"typealias_declaration", "associatedtype_declaration"})

#: Node kinds a name in the symbol table may resolve to.
_TYPE_KINDS = frozenset({"class", "struct", "enum", "protocol", "actor"})

#: Only these can sit at the head of an inheritance clause as a superclass.
_SUPERCLASS_KINDS = frozenset({"class", "actor"})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node_id(kind: str, rel_path: str, qualname: str = "") -> str:
    """Build a stable node ID of the form ``<prefix>:<rel_path>:<qualname>``."""
    prefix = _KIND_PREFIX.get(kind, kind[:3])
    if qualname:
        return f"{prefix}:{rel_path}:{qualname}"
    return f"{prefix}:{rel_path}"


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _lineno(node: Any) -> int:
    """1-based start line."""
    return node.start_point[0] + 1


def _end_lineno(node: Any) -> int:
    """1-based end line."""
    return node.end_point[0] + 1


def _base_type_name(text: str) -> str:
    """Reduce a written type to the bare name used as a symbol-table key.

    ``Storage<Data>`` → ``Storage``; ``Swift.Array`` → ``Array``;
    ``[String: T]`` → ``""`` (a structural type names nothing).
    """
    text = text.strip()
    if not text:
        return ""
    text = text.split("<", 1)[0].strip()
    text = text.split(".")[-1].strip()
    text = text.rstrip("?!").strip()
    return text if _IDENTIFIER_RE.match(text) else ""


def _clean_doc_line(line: str) -> str:
    """Strip a doc-comment line's leader (``///``, ``*``) and surrounding space."""
    line = line.strip()
    if line.startswith("///"):
        line = line[3:]
    elif line.startswith("//"):
        line = line[2:]
    elif line.startswith("*"):
        line = line[1:]
    return line.strip()


def _doc_from_multiline(text: str) -> str:
    """Extract the body of a ``/** … */`` or ``/// …`` block comment."""
    inner = text.strip()
    if inner.startswith("/**"):
        inner = inner[3:]
    elif inner.startswith("/*"):
        inner = inner[2:]
    if inner.endswith("*/"):
        inner = inner[:-2]
    lines = [_clean_doc_line(ln) for ln in inner.splitlines()]
    return " ".join(ln for ln in lines if ln)


def _extract_doc(node: Any, source: bytes) -> str:
    """Return the doc comment immediately preceding ``node``.

    Swift spells doc comments two ways and both appear in real code: a run of
    consecutive ``///`` line comments (separate ``comment`` siblings, which is
    why this walks backwards rather than reading one), and a single
    ``/** … */`` block (one ``multiline_comment`` sibling).
    """
    parent = node.parent
    if parent is None:
        return ""

    children = list(parent.children)
    idx = next((i for i, c in enumerate(children) if c.id == node.id), -1)
    if idx <= 0:
        return ""

    # A `/** … */` block is a single sibling.
    prev = children[idx - 1]
    if prev.type == "multiline_comment":
        text = _node_text(prev, source)
        return _doc_from_multiline(text) if text.strip().startswith("/**") else ""

    # A `///` doc comment is a run of consecutive `comment` siblings.
    collected: list[str] = []
    cursor = idx - 1
    while cursor >= 0 and children[cursor].type == "comment":
        text = _node_text(children[cursor], source).strip()
        if not text.startswith("///"):
            break
        collected.append(_clean_doc_line(text))
        cursor -= 1

    collected.reverse()
    return " ".join(ln for ln in collected if ln)


def _declaration_kind(node: Any, source: bytes) -> str:
    """Map a declaration node to a SwiftKG node kind.

    Reads the ``declaration_kind`` field, which is the only thing separating a
    struct from a class from an extension in this grammar.
    """
    field = node.child_by_field_name("declaration_kind")
    if field is not None:
        return _DECLARATION_KIND_TO_NODE_KIND.get(_node_text(field, source).strip(), "class")
    if node.type == "protocol_declaration":
        return "protocol"
    return "class"


def _declared_name(node: Any, source: bytes) -> str:
    """Return the declared type name for a type-like declaration.

    An ``extension``'s ``name`` field is a ``user_type`` rather than a
    ``type_identifier``, so this reduces whatever it finds to a bare name.
    """
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return ""
    return _base_type_name(_node_text(name_node, source))


def _member_name(node: Any, source: bytes) -> str:
    """Return the declared name of a member declaration.

    ``function_declaration`` carries two ``name`` fields — the function name
    and the return type — and ``child_by_field_name`` returns the first, which
    is what we want. ``subscript_declaration`` carries *only* the return-type
    ``name``, so it is named literally instead.
    """
    if node.type == "subscript_declaration":
        return "subscript"
    if node.type == "deinit_declaration":
        return "deinit"
    if node.type == "init_declaration":
        return "init"

    name_node = node.child_by_field_name("name")
    if name_node is None:
        return ""

    if name_node.type == "pattern":
        bound = name_node.child_by_field_name("bound_identifier")
        if bound is not None:
            return _node_text(bound, source).strip()
        return _node_text(name_node, source).strip()

    return _node_text(name_node, source).strip()


#: Swift access levels, ordered least to most visible. `internal` is the
#: language default and is what an unmodified declaration gets.
_VISIBILITY_LEVELS = ("private", "fileprivate", "internal", "package", "public", "open")


def _visibility(node: Any, source: bytes) -> str:
    """Return a declaration's Swift access level.

    Swift states visibility with a keyword, so this is a fact about the code
    rather than the naming convention (`_`-prefix) that the Python and
    JavaScript modules have to infer it from. Defaults to ``"internal"``,
    which is what Swift itself defaults to.
    """
    modifiers = next((c for c in node.children if c.type == "modifiers"), None)
    if modifiers is None:
        return "internal"
    for child in modifiers.children:
        if child.type == "visibility_modifier":
            level = _node_text(child, source).strip()
            if level in _VISIBILITY_LEVELS:
                return level
    return "internal"


def _inheritance_targets(node: Any, source: bytes) -> list[str]:
    """Return the bare names in a declaration's inheritance clause, in order."""
    names: list[str] = []
    for child in node.children:
        if child.type != "inheritance_specifier":
            continue
        target = child.child_by_field_name("inherits_from")
        text = _node_text(target if target is not None else child, source)
        name = _base_type_name(text)
        if name:
            names.append(name)
    return names


def _call_target_name(call_node: Any, source: bytes) -> tuple[str, str]:
    """Return ``(receiver, callee)`` for a call expression.

    ``call_expression`` has no ``function`` field — its children are a
    ``simple_identifier`` or a ``navigation_expression`` followed by a
    ``call_suffix``. ``helper()`` yields ``("", "helper")`` and
    ``Service.make()`` yields ``("Service", "make")``.
    """
    if not call_node.children:
        return "", ""

    # `items[id]` parses as a call_expression whose suffix is a subscript.
    # It is a subscript access, not a call to `items`, and treating it as one
    # wires every stored collection into the CALLS graph as a callee.
    suffix = call_node.children[-1]
    if suffix.type == "call_suffix" and _node_text(suffix, source).lstrip().startswith("["):
        return "", ""

    head = call_node.children[0]

    if head.type == "simple_identifier":
        return "", _node_text(head, source).strip()

    if head.type == "navigation_expression":
        text = _node_text(head, source).strip()
        parts = [p for p in text.replace("?", "").split(".") if p]
        if len(parts) < 2:
            return "", ""
        callee = parts[-1]
        receiver = parts[-2]
        if not _IDENTIFIER_RE.match(callee):
            return "", ""
        return (receiver if _IDENTIFIER_RE.match(receiver) else ""), callee

    return "", ""


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _skip_directory(name: str, excludes: frozenset[str] | set[str]) -> bool:
    if name in excludes:
        return True
    return any(name.endswith(suffix) for suffix in SKIP_DIR_SUFFIXES)


def find_swift_files(
    repo_root: Path,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[Path]:
    """Walk ``repo_root`` and return every indexable Swift source file.

    :param repo_root: Repository root to walk.
    :param include: Top-level directory names to include (empty = all).
    :param exclude: Extra directory names to exclude at every depth.
    :return: Sorted list of absolute paths.
    """
    include = include or set()
    all_excludes = SKIP_DIRS | (exclude or set())
    result: list[Path] = []

    def _walk(directory: Path, depth: int) -> None:
        try:
            entries = sorted(directory.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name.startswith("."):
                    continue
                if _skip_directory(entry.name, all_excludes):
                    continue
                if depth == 0 and include and entry.name not in include:
                    continue
                _walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix in SWIFT_EXTENSIONS:
                result.append(entry)

    _walk(repo_root, depth=0)
    return result


def local_spm_targets(repo_root: Path) -> set[str]:
    """Return module names that look like local SwiftPM targets.

    An ``import`` names a module, never a file, so imports cannot resolve to
    nodes the way TypeScript's path imports do. What *can* be recovered without
    building the package is whether the imported module is first-party: SwiftPM
    lays targets out as ``Sources/<Target>/`` and ``Tests/<Target>/``. The
    answer rides along in IMPORTS edge metadata rather than inventing a node
    kind for something the graph cannot fully model.
    """
    targets: set[str] = set()
    for root_name in ("Sources", "Tests", "Source"):
        root = repo_root / root_name
        if not root.is_dir():
            continue
        try:
            for entry in root.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    targets.add(entry.name)
        except OSError:
            continue
    return targets


# ---------------------------------------------------------------------------
# Symbol table (pass 1)
# ---------------------------------------------------------------------------


class SymbolTable:
    """Repo-wide index of declared names, built by the extractor's first pass.

    Swift has no per-file imports within a module, so a name declared anywhere
    in the repository is visible everywhere in it. That makes a repo-wide table
    the correct resolution scope — not an approximation of one.

    Every lookup returns a match only when it is *unambiguous*. A name declared
    twice resolves to nothing rather than to an arbitrary one of them, so an
    unresolved reference becomes an honest ``sym:`` stub instead of a
    confidently wrong edge.
    """

    def __init__(self) -> None:
        #: bare type name → list of (kind, node_id)
        self.types: dict[str, list[tuple[str, str]]] = {}
        #: free function name → list of node_id
        self.functions: dict[str, list[str]] = {}
        #: bare method name → list of node_id
        self.methods: dict[str, list[str]] = {}
        #: "Type.member" → list of node_id
        self.qualified: dict[str, list[str]] = {}

    # -- population -----------------------------------------------------

    def add_type(self, name: str, kind: str, node_id: str) -> None:
        self.types.setdefault(name, []).append((kind, node_id))

    def add_function(self, name: str, node_id: str) -> None:
        self.functions.setdefault(name, []).append(node_id)

    def add_method(self, owner: str, name: str, node_id: str) -> None:
        self.methods.setdefault(name, []).append(node_id)
        if owner:
            self.qualified.setdefault(f"{owner}.{name}", []).append(node_id)

    # -- lookup ---------------------------------------------------------

    def type_kind(self, name: str) -> str | None:
        """Return the declared kind of ``name``, or ``None`` if unknown/ambiguous."""
        entries = self.types.get(name)
        if not entries:
            return None
        kinds = {kind for kind, _ in entries}
        return kinds.pop() if len(kinds) == 1 else None

    def type_id(self, name: str) -> str | None:
        """Return the node ID declaring ``name``, or ``None`` if unknown/ambiguous."""
        entries = self.types.get(name)
        if not entries or len(entries) != 1:
            return None
        return entries[0][1]

    def resolve_call(
        self,
        receiver: str,
        callee: str,
        enclosing_type: str,
        enclosing_super: str = "",
    ) -> str | None:
        """Resolve a call to a node ID, or ``None`` when it cannot be pinned down.

        Tried in order of confidence: an explicit receiver (with ``self``
        rewritten to the enclosing type and ``super`` to its superclass), a
        member of the enclosing type, a free function, an initializer call on a
        known type, and finally a repo-unique method name.
        """
        if receiver in ("self", "Self") and enclosing_type:
            receiver = enclosing_type
        elif receiver == "super":
            # `super.fetch(...)` names the superclass's member, and an override
            # calling up is one of the more informative edges in a class graph.
            receiver = enclosing_super

        if receiver:
            hit = self._unique(self.qualified.get(f"{receiver}.{callee}"))
            if hit:
                return hit
            # `Service.make()` where Service is a type but the member is
            # inherited or external: fall through rather than guess.

        if enclosing_type and not receiver:
            hit = self._unique(self.qualified.get(f"{enclosing_type}.{callee}"))
            if hit:
                return hit

        if not receiver:
            hit = self._unique(self.functions.get(callee))
            if hit:
                return hit

            # `Point(x: 1, y: 2)` is an initializer call, which in Swift is
            # written exactly like a function call on the type's own name.
            type_hit = self.type_id(callee)
            if type_hit is not None:
                return type_hit

            hit = self._unique(self.methods.get(callee))
            if hit:
                return hit

        return None

    @staticmethod
    def _unique(candidates: list[str] | None) -> str | None:
        if candidates and len(candidates) == 1:
            return candidates[0]
        return None


# ---------------------------------------------------------------------------
# Per-file walker
# ---------------------------------------------------------------------------


class _FileWalker:
    """Walk one parsed Swift file, emitting NodeSpec / EdgeSpec objects.

    Runs in one of two modes. In ``collect_only`` mode it populates the shared
    :class:`SymbolTable` and emits nothing; otherwise it emits the graph,
    resolving references against the now-complete table.
    """

    def __init__(
        self,
        rel_path: str,
        source: bytes,
        tree: Any,
        symbols: SymbolTable,
        *,
        collect_only: bool,
        spm_targets: frozenset[str] = frozenset(),
    ) -> None:
        self.rel_path = rel_path
        self.source = source
        self.root = tree.root_node
        self.symbols = symbols
        self.collect_only = collect_only
        self.spm_targets = spm_targets
        self._mod_id = _make_node_id("module", rel_path)
        self._emitted: list[NodeSpec | EdgeSpec] = []

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def walk(self) -> list[NodeSpec | EdgeSpec]:
        self._emitted = []
        if not self.collect_only:
            self._emit_module()
        self._walk_scope(
            self.root, owner_id=self._mod_id, scope=(), enclosing_type="", enclosing_super=""
        )
        return self._emitted

    # ------------------------------------------------------------------
    # Emission helpers
    # ------------------------------------------------------------------

    def _emit(self, item: NodeSpec | EdgeSpec) -> None:
        if not self.collect_only:
            self._emitted.append(item)

    def _emit_module(self) -> None:
        self._emitted.append(
            NodeSpec(
                node_id=self._mod_id,
                kind="module",
                name=Path(self.rel_path).name,
                qualname=self.rel_path,
                source_path=self.rel_path,
                lineno=1,
                end_lineno=self.root.end_point[0] + 1,
                docstring=self._file_doc(),
            )
        )

    def _file_doc(self) -> str:
        """Return the file's leading doc comment, if it has one."""
        for child in self.root.children:
            if child.type == "multiline_comment":
                text = _node_text(child, self.source)
                return _doc_from_multiline(text) if text.strip().startswith("/**") else ""
            if child.type == "comment":
                collected: list[str] = []
                for sibling in self.root.children:
                    if sibling.type != "comment":
                        break
                    collected.append(_clean_doc_line(_node_text(sibling, self.source)))
                return " ".join(ln for ln in collected if ln)
            if child.type != "shebang_line":
                break
        return ""

    # ------------------------------------------------------------------
    # Scope walker
    # ------------------------------------------------------------------

    def _walk_scope(
        self,
        node: Any,
        *,
        owner_id: str,
        scope: tuple[str, ...],
        enclosing_type: str,
        enclosing_super: str,
    ) -> None:
        """Recurse through a scope, dispatching on declaration node type.

        ``scope`` is the chain of enclosing type names, which is what makes
        ``Service.Inner.deep`` come out qualified rather than flat.
        """
        for child in node.children:
            t = child.type

            if t == "import_declaration":
                self._handle_import(child)

            elif t in _TYPE_DECL_NODES:
                self._handle_type_declaration(child, owner_id=owner_id, scope=scope)

            elif t in _FUNCTION_MEMBERS:
                self._handle_callable(
                    child,
                    owner_id=owner_id,
                    scope=scope,
                    enclosing_type=enclosing_type,
                    enclosing_super=enclosing_super,
                )

            elif t in _PROPERTY_MEMBERS:
                self._handle_property(
                    child,
                    owner_id=owner_id,
                    scope=scope,
                    enclosing_type=enclosing_type,
                    enclosing_super=enclosing_super,
                )

            elif t in _TYPEALIAS_MEMBERS:
                self._handle_typealias(child, owner_id=owner_id, scope=scope)

            elif t == "enum_entry":
                self._handle_enum_entry(child, owner_id=owner_id, scope=scope)

            else:
                # `#if DEBUG` guarded declarations stay top-level siblings of a
                # `directive` node, and `statements` wraps file-scope code, so
                # recursing through unrecognised nodes reaches both.
                self._walk_scope(
                    child,
                    owner_id=owner_id,
                    scope=scope,
                    enclosing_type=enclosing_type,
                    enclosing_super=enclosing_super,
                )

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def _handle_import(self, node: Any) -> None:
        target = node.child_by_field_name("module") or next(
            (c for c in node.children if c.type in ("identifier", "simple_identifier")), None
        )
        if target is None:
            return
        # `import struct Foundation.Data` names a submodule path; the first
        # component is the module.
        raw = _node_text(target, self.source).strip()
        module_name = raw.split(".")[0].strip()
        if not _IDENTIFIER_RE.match(module_name):
            return
        self._emit(
            EdgeSpec(
                source_id=self._mod_id,
                target_id=f"sym:{module_name}",
                relation="IMPORTS",
                metadata={"local": module_name in self.spm_targets},
            )
        )

    # ------------------------------------------------------------------
    # Type declarations
    # ------------------------------------------------------------------

    def _handle_type_declaration(
        self,
        node: Any,
        *,
        owner_id: str,
        scope: tuple[str, ...],
    ) -> None:
        kind = _declaration_kind(node, self.source)
        name = _declared_name(node, self.source)
        if not name:
            return

        if kind == "extension":
            self._handle_extension(node, name=name, owner_id=owner_id)
            return

        qualname = ".".join((*scope, name))
        node_id = _make_node_id(kind, self.rel_path, qualname)

        if self.collect_only:
            self.symbols.add_type(name, kind, node_id)
        else:
            self._emitted.append(
                NodeSpec(
                    node_id=node_id,
                    kind=kind,
                    name=name,
                    qualname=qualname,
                    source_path=self.rel_path,
                    lineno=_lineno(node),
                    end_lineno=_end_lineno(node),
                    docstring=_extract_doc(node, self.source),
                    metadata={
                        "declaration_kind": kind,
                        "visibility": _visibility(node, self.source),
                    },
                )
            )
            self._emitted.append(
                EdgeSpec(source_id=owner_id, target_id=node_id, relation="CONTAINS")
            )
            self._emit_inheritance(node, subject_id=node_id, subject_kind=kind)

        self._walk_body(
            node,
            owner_id=node_id,
            scope=(*scope, name),
            enclosing_type=name,
            enclosing_super=self._superclass_of(node, kind),
        )

    def _handle_extension(self, node: Any, *, name: str, owner_id: str) -> None:
        """Emit an extension as its own node, with members qualified under the extended type.

        Extensions are a unit of authorship in Swift, not a syntactic wrapper:
        a conformance is routinely declared in an extension in a different file
        from the type it extends. Folding the members into the type would lose
        where the code actually lives, so the extension gets a node and an
        EXTENDS edge, while its members are still qualified as ``Type.member``
        so they read as members of the type.
        """
        node_id = _make_node_id("extension", self.rel_path, name)

        if not self.collect_only:
            self._emitted.append(
                NodeSpec(
                    node_id=node_id,
                    kind="extension",
                    name=name,
                    qualname=name,
                    source_path=self.rel_path,
                    lineno=_lineno(node),
                    end_lineno=_end_lineno(node),
                    docstring=_extract_doc(node, self.source),
                    metadata={
                        "declaration_kind": "extension",
                        "extends": name,
                        "visibility": _visibility(node, self.source),
                    },
                )
            )
            self._emitted.append(
                EdgeSpec(source_id=self._mod_id, target_id=node_id, relation="CONTAINS")
            )
            target_id = self.symbols.type_id(name) or f"sym:{name}"
            self._emitted.append(
                EdgeSpec(source_id=node_id, target_id=target_id, relation="EXTENDS")
            )
            # Everything in an extension's inheritance clause is a protocol:
            # extensions add conformance, never a superclass.
            for base in _inheritance_targets(node, self.source):
                base_id = self.symbols.type_id(base) or f"sym:{base}"
                self._emitted.append(
                    EdgeSpec(source_id=node_id, target_id=base_id, relation="CONFORMS")
                )

        self._walk_body(
            node,
            owner_id=node_id,
            scope=(name,),
            enclosing_type=name,
            # An extension cannot override, so `super` has no meaning in its body.
            enclosing_super="",
        )

    def _walk_body(
        self,
        node: Any,
        *,
        owner_id: str,
        scope: tuple[str, ...],
        enclosing_type: str,
        enclosing_super: str,
    ) -> None:
        body = node.child_by_field_name("body")
        if body is None:
            body = next((c for c in node.children if c.type in _BODY_NODES), None)
        if body is None:
            return
        self._walk_scope(
            body,
            owner_id=owner_id,
            scope=scope,
            enclosing_type=enclosing_type,
            enclosing_super=enclosing_super,
        )

    def _emit_inheritance(self, node: Any, *, subject_id: str, subject_kind: str) -> None:
        """Split an inheritance clause into INHERITS and CONFORMS edges.

        Swift gives no syntactic signal, so this asks the symbol table what the
        target actually is. When the target is external and unresolvable, it
        falls back to the language rule: only a class or actor may have a
        superclass, and the superclass must be written first.
        """
        for position, base in enumerate(_inheritance_targets(node, self.source)):
            target_kind = self.symbols.type_kind(base)
            target_id = self.symbols.type_id(base) or f"sym:{base}"

            if target_kind == "protocol":
                relation = "CONFORMS"
            elif target_kind in _SUPERCLASS_KINDS:
                relation = "INHERITS"
            elif target_kind is not None:
                # A struct or enum can never be inherited from.
                relation = "CONFORMS"
            elif position == 0 and subject_kind in _SUPERCLASS_KINDS:
                relation = "INHERITS"
            else:
                relation = "CONFORMS"

            self._emitted.append(
                EdgeSpec(source_id=subject_id, target_id=target_id, relation=relation)
            )

    # ------------------------------------------------------------------
    # Callables
    # ------------------------------------------------------------------

    def _handle_callable(
        self,
        node: Any,
        *,
        owner_id: str,
        scope: tuple[str, ...],
        enclosing_type: str,
        enclosing_super: str,
    ) -> None:
        name = _member_name(node, self.source)
        if not name:
            return

        kind = "method" if scope else "function"
        qualname = ".".join((*scope, name))
        node_id = _make_node_id(kind, self.rel_path, qualname)

        if self.collect_only:
            if kind == "function":
                self.symbols.add_function(name, node_id)
            else:
                self.symbols.add_method(scope[-1] if scope else "", name, node_id)
            return

        self._emitted.append(
            NodeSpec(
                node_id=node_id,
                kind=kind,
                name=name,
                qualname=qualname,
                source_path=self.rel_path,
                lineno=_lineno(node),
                end_lineno=_end_lineno(node),
                docstring=_extract_doc(node, self.source),
                metadata={
                    "declaration": node.type,
                    "visibility": _visibility(node, self.source),
                },
            )
        )
        self._emitted.append(EdgeSpec(source_id=owner_id, target_id=node_id, relation="CONTAINS"))
        self._emit_calls(
            node,
            source_id=node_id,
            enclosing_type=enclosing_type,
            enclosing_super=enclosing_super,
        )

    def _handle_property(
        self,
        node: Any,
        *,
        owner_id: str,
        scope: tuple[str, ...],
        enclosing_type: str,
        enclosing_super: str,
    ) -> None:
        name = _member_name(node, self.source)
        if not name or not _IDENTIFIER_RE.match(name):
            return

        qualname = ".".join((*scope, name))
        node_id = _make_node_id("property", self.rel_path, qualname)

        if self.collect_only:
            if scope:
                self.symbols.add_method(scope[-1], name, node_id)
            return

        self._emitted.append(
            NodeSpec(
                node_id=node_id,
                kind="property",
                name=name,
                qualname=qualname,
                source_path=self.rel_path,
                lineno=_lineno(node),
                end_lineno=_end_lineno(node),
                docstring=_extract_doc(node, self.source),
                metadata={
                    "declaration": node.type,
                    "visibility": _visibility(node, self.source),
                },
            )
        )
        self._emitted.append(EdgeSpec(source_id=owner_id, target_id=node_id, relation="CONTAINS"))
        # A computed property has a body, and that body calls things.
        self._emit_calls(
            node,
            source_id=node_id,
            enclosing_type=enclosing_type,
            enclosing_super=enclosing_super,
        )

    def _handle_typealias(self, node: Any, *, owner_id: str, scope: tuple[str, ...]) -> None:
        name = _member_name(node, self.source)
        if not name or not _IDENTIFIER_RE.match(name):
            return

        qualname = ".".join((*scope, name))
        node_id = _make_node_id("typealias", self.rel_path, qualname)

        if self.collect_only:
            return

        self._emitted.append(
            NodeSpec(
                node_id=node_id,
                kind="typealias",
                name=name,
                qualname=qualname,
                source_path=self.rel_path,
                lineno=_lineno(node),
                end_lineno=_end_lineno(node),
                docstring=_extract_doc(node, self.source),
                metadata={
                    "declaration": node.type,
                    "visibility": _visibility(node, self.source),
                },
            )
        )
        self._emitted.append(EdgeSpec(source_id=owner_id, target_id=node_id, relation="CONTAINS"))

    def _handle_enum_entry(self, node: Any, *, owner_id: str, scope: tuple[str, ...]) -> None:
        """Record an enum case as a property node.

        Cases are the enum's API surface — an exhaustive `switch` is written
        against them — so they are worth indexing, and `property` is the kind
        that already means "named value member" in this schema.
        """
        name = _member_name(node, self.source)
        if not name or not _IDENTIFIER_RE.match(name):
            return

        qualname = ".".join((*scope, name))
        node_id = _make_node_id("property", self.rel_path, qualname)

        if self.collect_only:
            return

        self._emitted.append(
            NodeSpec(
                node_id=node_id,
                kind="property",
                name=name,
                qualname=qualname,
                source_path=self.rel_path,
                lineno=_lineno(node),
                end_lineno=_end_lineno(node),
                docstring=_extract_doc(node, self.source),
                metadata={"declaration": "enum_entry", "visibility": "public"},
            )
        )
        self._emitted.append(EdgeSpec(source_id=owner_id, target_id=node_id, relation="CONTAINS"))

    # ------------------------------------------------------------------
    # Superclass lookup
    # ------------------------------------------------------------------

    def _superclass_of(self, node: Any, kind: str) -> str:
        """Return the name of a declaration's superclass, or ``""`` if it has none."""
        if kind not in _SUPERCLASS_KINDS:
            return ""
        for position, base in enumerate(_inheritance_targets(node, self.source)):
            target_kind = self.symbols.type_kind(base)
            if target_kind in _SUPERCLASS_KINDS:
                return base
            if target_kind is None and position == 0:
                return base
        return ""

    # ------------------------------------------------------------------
    # Calls
    # ------------------------------------------------------------------

    def _emit_calls(
        self,
        node: Any,
        *,
        source_id: str,
        enclosing_type: str,
        enclosing_super: str,
    ) -> None:
        body = node.child_by_field_name("body") or node.child_by_field_name("computed_value")
        if body is None:
            return

        seen: set[str] = set()
        for receiver, callee in self._collect_calls(body):
            target_id = self.symbols.resolve_call(receiver, callee, enclosing_type, enclosing_super)
            if target_id is None:
                target_id = f"sym:{callee}"
            if target_id == source_id or target_id in seen:
                continue
            seen.add(target_id)
            self._emitted.append(
                EdgeSpec(source_id=source_id, target_id=target_id, relation="CALLS")
            )

    def _collect_calls(self, node: Any, depth: int = 0) -> Iterator[tuple[str, str]]:
        """Yield ``(receiver, callee)`` for every call in a body, closures included."""
        if depth > 40:
            return
        for child in node.children:
            if child.type == "call_expression":
                receiver, callee = _call_target_name(child, self.source)
                if callee:
                    yield receiver, callee
            yield from self._collect_calls(child, depth + 1)


# ---------------------------------------------------------------------------
# SwiftCodeExtractor
# ---------------------------------------------------------------------------


class SwiftCodeExtractor(KGExtractor):
    """KGExtractor backed by tree-sitter Swift AST parsing.

    Yields :class:`NodeSpec` and :class:`EdgeSpec` objects for every ``.swift``
    file under ``repo_path``, resolving inheritance, conformance and calls
    against a repo-wide symbol table built in a first pass.

    :param repo_path: Absolute path to the Swift repository.
    :param include: Top-level directory names to include (empty = all).
    :param exclude: Directory names to exclude at every depth.
    :param config: Optional domain config dict.
    """

    def __init__(
        self,
        repo_path: Path,
        *,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(repo_path, config)
        self._include: set[str] = include or set()
        self._exclude: set[str] = exclude or set()
        self.symbols = SymbolTable()

    # ------------------------------------------------------------------
    # KGExtractor protocol
    # ------------------------------------------------------------------

    def node_kinds(self) -> list[str]:
        return [
            "module",
            "class",
            "struct",
            "enum",
            "protocol",
            "actor",
            "extension",
            "function",
            "method",
            "property",
            "typealias",
            "symbol",
        ]

    def edge_kinds(self) -> list[str]:
        return [
            "CONTAINS",
            "IMPORTS",
            "CALLS",
            "INHERITS",
            "CONFORMS",
            "EXTENDS",
        ]

    def meaningful_node_kinds(self) -> list[str]:
        """Exclude ``symbol`` stubs from vector indexing and coverage metrics."""
        return [
            "module",
            "class",
            "struct",
            "enum",
            "protocol",
            "actor",
            "extension",
            "function",
            "method",
            "property",
            "typealias",
        ]

    def extract(self) -> Iterator[NodeSpec | EdgeSpec]:
        if not _HAS_TREE_SITTER:
            raise RuntimeError(
                "tree-sitter and tree-sitter-swift are required. "
                "Install with: pip install tree-sitter tree-sitter-swift"
            )

        files = find_swift_files(self.repo_path, self._include, self._exclude)
        spm_targets = frozenset(local_spm_targets(self.repo_path))

        # Pass 1 — build the symbol table. Nothing is emitted.
        for abs_path, rel_path, source, tree in self._parse_all(files):
            _FileWalker(
                rel_path,
                source,
                tree,
                self.symbols,
                collect_only=True,
                spm_targets=spm_targets,
            ).walk()
            del abs_path

        # Pass 2 — emit the graph, resolving against the completed table.
        for abs_path, rel_path, source, tree in self._parse_all(files):
            yield from _FileWalker(
                rel_path,
                source,
                tree,
                self.symbols,
                collect_only=False,
                spm_targets=spm_targets,
            ).walk()
            del abs_path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_all(self, files: list[Path]) -> Iterator[tuple[Path, str, bytes, Any]]:
        """Parse each file in turn, skipping any that cannot be read or parsed.

        Streams one tree at a time rather than retaining every tree between the
        two passes: a large Swift repository's trees do not comfortably fit in
        memory, and re-parsing is cheap by comparison.
        """
        parser = Parser(_SWIFT_LANGUAGE)
        for abs_path in files:
            try:
                rel_path = str(abs_path.relative_to(self.repo_path)).replace("\\", "/")
                source = abs_path.read_bytes()
                tree = parser.parse(source)
            except Exception:  # noqa: BLE001
                continue
            yield abs_path, rel_path, source, tree
