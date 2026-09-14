#!/usr/bin/env python3
"""
kg.py — SwiftKG: concrete KGModule for Swift codebases.

Owns the Swift-specific extraction layer (tree-sitter AST) and delegates all
generic infrastructure (SQLite, sqlite-vec, hybrid query, snippet packing,
snapshots) to the KGModule base class from ``kg_utils.pipeline``.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from kg_utils.extractor import KGExtractor
    from kg_utils.pipeline import KGModule
    from kg_utils.semantic import DEFAULT_MODEL
    from kg_utils.specs import BuildStats, QueryResult, SnippetPack
    from kg_utils.store import DEFAULT_RELS, GraphStore  # noqa: F401  (DEFAULT_RELS re-exported)
except ImportError as _e:
    raise ImportError(
        "SwiftKG requires kgmodule-utils[semantic] for its graph infrastructure.\n"
        "Install with:  pip install 'swift-kg'\n"
        f"Original error: {_e}"
    ) from _e

from swift_kg.config import load_exclude_dirs, load_include_dirs
from swift_kg.extractor import SwiftCodeExtractor
from swift_kg.resolution import resolve_symbols_pruned
from swift_kg.validation import bounded_int, normalize_node_id, require_query

__all__ = [
    "SwiftKG",
    "BuildStats",
    "QueryResult",
    "SnippetPack",
]

#: Swift node-kind priority for ranking. Types outrank their members, and a
#: protocol outranks a concrete type: in Swift the protocol is usually the
#: abstraction a reader is looking for, and the conforming types are its
#: implementations.
_SWIFT_KIND_PRIORITY: dict[str, int] = {
    "protocol": 0,
    "class": 1,
    "struct": 2,
    "actor": 3,
    "enum": 4,
    "function": 5,
    "method": 6,
    "extension": 7,
    "typealias": 8,
    "property": 9,
    "module": 10,
    "symbol": 11,
}


class SwiftKG(KGModule):
    """Top-level orchestrator for the Swift Knowledge Graph.

    Subclasses :class:`~kg_utils.pipeline.KGModule` and provides the
    Swift-specific extraction layer via
    :class:`~swift_kg.extractor.SwiftCodeExtractor`. All generic infrastructure
    — SQLite persistence, sqlite-vec indexing, hybrid query, snippet packing —
    is inherited from KGModule.

    Typical usage::

        kg = SwiftKG(repo_root="/path/to/swift-repo")
        stats = kg.build(wipe=True)
        print(stats)

        result = kg.query("networking layer", k=8)
        pack = kg.pack("error handling")
        pack.save("context.md")

    :param repo_root: Repository root directory.
    :param db_path: SQLite database path (defaults to ``<repo_root>/.swiftkg/graph.sqlite``).
    :param vectors_path: sqlite-vec store path (defaults to ``<repo_root>/.swiftkg/vectors.sqlite``).
    :param model: Sentence-transformer model name.
    :param table: sqlite-vec table name.
    :param include: Top-level directory names to index, unioned with
        ``[tool.swiftkg].include``.  Empty means index everything.
    :param exclude: Directory names to skip at every depth, unioned with
        ``[tool.swiftkg].exclude``.
    """

    _default_dir = ".swiftkg"

    def __init__(
        self,
        repo_root: str | Path,
        db_path: str | Path | None = None,
        vectors_path: str | Path | None = None,
        *,
        model: str = DEFAULT_MODEL,
        table: str = "swiftkg_nodes",
        include: set[str] | None = None,
        exclude: set[str] | None = None,
    ) -> None:
        super().__init__(
            repo_root,
            db_path=db_path,
            model=model,
            table=table,
            vector_backend="sqlite-vec",
        )
        if vectors_path is not None:
            self.vectors_path = Path(vectors_path)
        self.include: set[str] = set(include or ())
        self.exclude: set[str] = set(exclude or ())

    # ------------------------------------------------------------------
    # KGModule abstract interface
    # ------------------------------------------------------------------

    def make_extractor(self) -> KGExtractor:
        # A Swift repo usually has no pyproject.toml, so the CLI flags are the
        # only reachable way to scope a build on most repositories.
        include = load_include_dirs(self.repo_root) | self.include
        exclude = load_exclude_dirs(self.repo_root) | self.exclude
        return SwiftCodeExtractor(self.repo_root, include=include, exclude=exclude)

    def kind(self) -> str:
        return "code"

    def _post_build_hook(self, store: GraphStore) -> None:
        """Resolve ``sym:`` stubs, then prune what Swift cannot support.

        The extractor's two-pass resolver already pins down every reference it
        can see, refusing to guess between candidates. What reaches here is
        what it could not: mostly framework names with no first-party
        declaration, plus calls through a receiver whose type is unknown. See
        :mod:`swift_kg.resolution` for why the generic resolution is pruned
        harder here than in PyCodeKG.

        :param store: The graph store just written by ``build_graph``.
        """
        resolve_symbols_pruned(store)

    def analyze(self) -> str:
        """Run thorough structural analysis and return a Markdown report.

        Uses :class:`~swift_kg.swiftkg_thorough_analysis.SwiftKGAnalyzer` for the full analysis
        (fan-in, fan-out, module coupling, doc coverage, conformance graph, …).
        Falls back to a lightweight summary when the KG has not been built yet.
        """
        try:
            from swift_kg.swiftkg_thorough_analysis import SwiftKGAnalyzer  # noqa: PLC0415

            analyzer = SwiftKGAnalyzer(self)
            analyzer.run_analysis()
            return analyzer.to_markdown()
        except Exception as exc:  # noqa: BLE001
            try:
                return render_analysis(str(self.repo_root), self.store.stats())
            except Exception:  # noqa: BLE001
                return f"# SwiftKG Analysis\n\nAnalysis failed: {exc}\n"

    # ------------------------------------------------------------------
    # Validated entry points
    # ------------------------------------------------------------------
    # Per FLEET_STANDARDS (settled 2026-08-24), validation lives here rather
    # than in the CLI and the MCP server separately: both funnel through these
    # methods, so one set of checks covers both surfaces and cannot drift.

    def query(  # type: ignore[override]
        self,
        q: str,
        *,
        k: int = 8,
        hop: int = 1,
        max_nodes: int = 25,
        **kwargs: Any,
    ) -> QueryResult:
        """Hybrid query with bounded inputs.

        :param q: Natural-language query (1–500 characters).
        :param k: Semantic seed count (1–100).
        :param hop: Graph expansion hops (0–5).
        :param max_nodes: Maximum nodes returned (1–500).
        :param kwargs: Remaining :meth:`kg_utils.pipeline.KGModule.query` options.
        :return: :class:`~kg_utils.specs.QueryResult`.
        :raises ValueError: If any bound is exceeded.
        """
        return super().query(
            require_query(q),
            k=bounded_int("k", k, 1, 100),
            hop=bounded_int("hop", hop, 0, 5),
            max_nodes=bounded_int("max_nodes", max_nodes, 1, 500),
            **kwargs,
        )

    def pack(  # type: ignore[override]
        self,
        q: str,
        *,
        k: int = 8,
        hop: int = 1,
        max_nodes: int | None = 15,
        max_lines: int = 60,
        **kwargs: Any,
    ) -> SnippetPack:
        """Hybrid query + snippet extraction with bounded inputs.

        :param q: Natural-language query (1–500 characters).
        :param k: Semantic seed count (1–100).
        :param hop: Graph expansion hops (0–5).
        :param max_nodes: Maximum nodes in the pack (1–500, or ``None``).
        :param max_lines: Maximum lines per snippet (1–2000).
        :param kwargs: Remaining :meth:`kg_utils.pipeline.KGModule.pack` options.
        :return: :class:`~kg_utils.specs.SnippetPack`.
        :raises ValueError: If any bound is exceeded.
        """
        return super().pack(
            require_query(q),
            k=bounded_int("k", k, 1, 100),
            hop=bounded_int("hop", hop, 0, 5),
            max_nodes=None if max_nodes is None else bounded_int("max_nodes", max_nodes, 1, 500),
            max_lines=bounded_int("max_lines", max_lines, 1, 2000),
            **kwargs,
        )

    def node(self, node_id: str) -> dict[str, Any] | None:
        """Fetch a single node, accepting the ID forms callers actually pass.

        :param node_id: Node ID, optionally wrapped in backticks or quotes.
        :return: Node dict, or ``None`` if not found.
        :raises ValueError: If the ID is empty or over-long.
        """
        return super().node(normalize_node_id(node_id))

    def callers(self, node_id: str, *, rel: str = "CALLS") -> list[dict[str, Any]]:
        """Return all nodes referencing ``node_id`` through ``rel``.

        :param node_id: Target node ID, normalized as in :meth:`node`.
        :param rel: Relation to invert — ``CALLS``, ``CONFORMS``, ``INHERITS``,
            ``EXTENDS``, ``IMPORTS`` or ``CONTAINS``.
        :return: Deduplicated caller node dicts.
        :raises ValueError: If the ID or relation is unusable.
        """
        if rel not in self.edge_relations():
            raise ValueError(f"rel must be one of {sorted(self.edge_relations())}, got {rel!r}")
        return super().callers(normalize_node_id(node_id), rel=rel)

    # ------------------------------------------------------------------
    # Swift-specific surface
    # ------------------------------------------------------------------

    @staticmethod
    def edge_relations() -> frozenset[str]:
        """Return the relation types SwiftKG emits.

        ``CONFORMS`` and ``INHERITS`` are separate relations because Swift
        writes them identically and separating them is most of what the
        extractor's two-pass resolver is for.
        """
        return frozenset({"CONTAINS", "IMPORTS", "CALLS", "INHERITS", "CONFORMS", "EXTENDS"})

    def conformers(self, node_id: str) -> list[dict[str, Any]]:
        """Return every type and extension conforming to a protocol.

        The question a Swift reader asks about a protocol is who implements
        it, which is the CONFORMS relation inverted.

        :param node_id: Node ID of a protocol.
        :return: Conforming node dicts.
        """
        return self.callers(node_id, rel="CONFORMS")

    def subclasses(self, node_id: str) -> list[dict[str, Any]]:
        """Return every direct subclass of a class or actor.

        :param node_id: Node ID of a class or actor.
        :return: Subclass node dicts.
        """
        return self.callers(node_id, rel="INHERITS")

    def extensions_of(self, node_id: str) -> list[dict[str, Any]]:
        """Return every extension declared on a type.

        Swift routinely declares a type's behaviour in extensions in other
        files, so "where is the rest of this type" is a real question with a
        graph answer.

        :param node_id: Node ID of a type.
        :return: Extension node dicts.
        """
        return self.callers(node_id, rel="EXTENDS")

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def _kind_priority(self, kind: str) -> int:
        return _SWIFT_KIND_PRIORITY.get(kind, 99)

    def __enter__(self) -> SwiftKG:
        # Narrowed from the base's `-> KGModule` so `with SwiftKG(...) as kg:`
        # keeps the subclass surface under `ty` (FLEET_STANDARDS, 2026-08-24).
        return self

    def __repr__(self) -> str:
        return (
            f"SwiftKG(repo_root={self.repo_root!r}, "
            f"db_path={self.db_path!r}, "
            f"vectors_path={self.vectors_path!r}, "
            f"model={self.model_name!r})"
        )


# ---------------------------------------------------------------------------
# Analysis renderer
# ---------------------------------------------------------------------------


def render_analysis(repo_root: str, stats: dict) -> str:
    """Render a Markdown analysis report from store stats.

    The fallback used when the full analyzer cannot run — typically because
    the graph has not been built yet.

    :param repo_root: Repository root that was analysed.
    :param stats: Statistics dict from the graph store.
    :return: Markdown report.
    """
    lines: list[str] = [
        "# SwiftKG Analysis Report\n",
        f"**Repository:** `{repo_root}`\n",
        "---\n",
        "## Structural Metrics\n",
        f"- **Total nodes:** {stats.get('total_nodes', 0):,}",
        f"- **Meaningful nodes:** {stats.get('meaningful_nodes', 0):,}",
        f"- **Total edges:** {stats.get('total_edges', 0):,}",
    ]

    cov = stats.get("docstring_coverage")
    if cov is not None:
        lines.append(f"- **Doc-comment coverage:** {cov:.1%}")

    node_counts: dict = stats.get("node_counts", {})
    if node_counts:
        lines.append("\n### Nodes by Kind\n")
        lines.append("| Kind | Count |")
        lines.append("|------|------:|")
        for kind, count in sorted(node_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {kind} | {count:,} |")

    edge_counts: dict = stats.get("edge_counts", {})
    if edge_counts:
        lines.append("\n### Edges by Relation\n")
        lines.append("| Relation | Count |")
        lines.append("|----------|------:|")
        for rel, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {rel} | {count:,} |")

    lines.append("\n---\n")
    lines.append(
        "> Graph built by deterministic tree-sitter AST extraction. "
        "No LLM inference used in indexing."
    )
    return "\n".join(lines)
