#!/usr/bin/env python3
"""
mcp_server.py -- SwiftKG MCP Server

Serves a Swift codebase's knowledge graph to any MCP-compatible agent
(Claude Code, Claude Desktop, Cursor, Copilot) over the fleet's shared server
base, :mod:`kg_utils.mcp`.

The server answers the fleet's canonical tools -- ``stats``, ``query``,
``pack``, ``get_node``, ``neighbors`` -- under the same names as every other
KG server, plus SwiftKG's own code-graph tools (``callers``,
``type_hierarchy``, ``public_api``, ``explain``, ``centrality``, the CodeRank
and snapshot tools, ...). ``query`` and ``pack`` are SwiftKG's richer versions
of the canonical pair: hybrid reranking by default, a per-module cap, and all
six Swift relations (including CONFORMS and EXTENDS) followed by default.

The tool list is not kept by hand anywhere. Each tool's docstring is its
description, the server's instructions are generated from them, and::

    swiftkg mcp --manifest

prints the whole list as JSON without opening the graph.

Usage
-----
Install the package, then run::

    swiftkg mcp --repo /path/to/swift-repo

``--db`` and ``--vectors`` are optional; they default to
``.swiftkg/graph.sqlite`` and ``.swiftkg/vectors.sqlite``, and a relative
path is taken from ``--repo``. ``swiftkg-mcp`` is the same command under the
name older Claude Desktop and Copilot configs use.

Per-project config for Claude Code and Kilo Code (``.mcp.json``)::

    {
      "mcpServers": {
        "swiftkg": {
          "command": "swiftkg",
          "args": ["mcp", "--repo", "/path/to/swift-repo"]
        }
      }
    }

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kg_utils.mcp import Context, KGServer, kg_from, make_server
from kg_utils.semantic import DEFAULT_MODEL
from kg_utils.validation import bounded_int, require_query

from swift_kg import __version__
from swift_kg.kg import SwiftKG
from swift_kg.snapshots import SnapshotManager
from swift_kg.validation import MAX_QUERY_LEN, normalize_node_id

#: Relations ``query`` and ``pack`` follow when ``rels`` is omitted: all six
#: SwiftKG emits, so conformances and extensions are expanded by default.
_DEFAULT_RELS: tuple[str, ...] = (
    "CONTAINS",
    "CALLS",
    "IMPORTS",
    "INHERITS",
    "CONFORMS",
    "EXTENDS",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshots(kg: SwiftKG) -> SnapshotManager:
    """Return the snapshot manager for the session's graph.

    :param kg: The session's graph.
    :return: A :class:`SnapshotManager` over ``<repo>/.swiftkg/snapshots``.
    """
    return SnapshotManager(kg.repo_root / ".swiftkg" / "snapshots", db_path=kg.db_path)


def _snapshot_freshness(kg: SwiftKG, snapshot_total_nodes: int) -> dict:
    """Compare a snapshot's node count against the currently loaded graph DB.

    :param kg: The session's graph.
    :param snapshot_total_nodes: ``metrics.total_nodes`` from a snapshot object.
    :return: Freshness metadata payload.
    """
    current_nodes = int(kg.stats()["nodes"]["total"])
    delta = current_nodes - int(snapshot_total_nodes)

    is_fresh = delta == 0
    status = "fresh" if delta == 0 else ("behind" if delta > 0 else "ahead")
    note = None

    if 0 < delta < 50:
        is_fresh = True
        status = "near_fresh"
        note = "Within tolerance (sym: stubs often accumulate between rebuilds)"

    out = {
        "snapshot_total_nodes": int(snapshot_total_nodes),
        "current_total_nodes": current_nodes,
        "delta_nodes": delta,
        "is_fresh": is_fresh,
        "status": status,
    }
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Instructions: the hand-written part. The tool list is appended by kg_utils.mcp.
# ---------------------------------------------------------------------------

PREAMBLE = (
    "SwiftKG is a hybrid semantic + structural knowledge graph for Swift codebases. "
    "It indexes every file, class, struct, enum, protocol, actor, extension, function, "
    "method, property and type alias as a node, with typed edges (CALLS, IMPORTS, "
    "CONTAINS, INHERITS, CONFORMS, EXTENDS) between them. Node IDs look like "
    "'<kind>:<module_path>:<qualname>', e.g. "
    "'cls:Sources/Networking/Client.swift:HTTPClient'.\n\n"
    "## Recommended workflows\n\n"
    "- **Explore an unfamiliar Swift repo**: stats -> query -> pack\n"
    "- **Find a specific class/function**: find_node(name) -> get_node -> neighbors\n"
    "- **Understand a Swift type or protocol**: find_node(name) -> type_hierarchy(node_id)\n"
    "- **Trace usage of a symbol**: find_node(name) -> callers(node_id)\n"
    "- **Find a protocol's implementations**: callers(node_id, rel='CONFORMS') or "
    "type_hierarchy(node_id)\n"
    "- **Review a module's exposed surface**: public_api(module_path='Sources/Networking')\n"
    "- **Identify structural hotspots**: centrality(top=20) or centrality(group_by='module')\n"
    "- **Architecture review**: analyze_repo\n"
    "- **Track codebase evolution**: snapshot_list -> snapshot_diff(key_a, key_b)\n"
    "- **Answer 'how does X work?'**: pack with a descriptive query\n\n"
    "## Argument bounds\n\n"
    "Out-of-range arguments are rejected with a message naming the accepted range, rather "
    "than silently clamped -- a truncated result that looks complete is worse than an "
    "error. `k` 1-100, `hop` 0-5, `max_nodes` 1-500, `max_lines` 1-2000, `radius` 0-5, "
    "`top` 1-1000, `limit` 1-5000 (`snapshot_list` accepts 0 for 'all'; `neighbors` "
    "1-500), queries at most 500 characters. A `node_id` may be passed with surrounding "
    "backticks or quotes; it is normalized before use."
)


# ---------------------------------------------------------------------------
# Canonical tools: SwiftKG's richer query and pack, under the fleet's names
# ---------------------------------------------------------------------------


def query(
    q: str,
    k: int = 8,
    hop: int = 1,
    rels: list[str] | None = None,
    max_nodes: int = 25,
    min_score: float = 0.0,
    max_per_module: int = 3,
    rerank_mode: str = "hybrid",
    rerank_semantic_weight: float = 0.7,
    rerank_lexical_weight: float = 0.3,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """
    Hybrid semantic + structural search: ranked Swift nodes and the edges among them.

    Seeds on vector similarity, then expands through the graph. Use ``pack``
    instead when you want the source itself.

    **rerank_mode:** ``hybrid`` (default) blends vector similarity (70%) with
    lexical overlap on name, qualname, module and doc-comment (30%);
    ``semantic`` ranks by vector score only; ``legacy`` orders by hop
    distance first, for stable comparisons with older results.

    :param q: Natural-language query, e.g. "request retry policy".
    :param k: Semantic seed nodes (1-100, default 8).
    :param hop: Graph expansion hops from each seed (0-5, default 1).
    :param rels: Edge types to follow; omit for all six (CONTAINS, CALLS,
        IMPORTS, INHERITS, CONFORMS, EXTENDS).
    :param max_nodes: Most nodes to return (default 25).
    :param min_score: Minimum semantic score for a seed, 0.0-1.0.
    :param max_per_module: Most nodes from one module (default 3; 0 disables).
    :param rerank_mode: ``hybrid`` (default), ``semantic`` or ``legacy``.
    :param rerank_semantic_weight: Semantic weight for ``hybrid`` (default 0.7).
    :param rerank_lexical_weight: Lexical weight for ``hybrid`` (default 0.3).
    """
    result = kg_from(ctx).query(
        q,
        k=k,
        hop=hop,
        rels=tuple(rels) if rels else _DEFAULT_RELS,
        max_nodes=max_nodes,
        min_score=min_score,
        max_per_module=max_per_module if max_per_module > 0 else None,
        rerank_mode=rerank_mode,
        rerank_semantic_weight=rerank_semantic_weight,
        rerank_lexical_weight=rerank_lexical_weight,
    )
    return json.loads(result.to_json())


def pack(
    q: str,
    k: int = 8,
    hop: int = 1,
    rels: list[str] | None = None,
    context: int = 5,
    max_lines: int = 60,
    max_nodes: int = 15,
    min_score: float = 0.0,
    max_per_module: int = 3,
    rerank_mode: str = "hybrid",
    rerank_semantic_weight: float = 0.7,
    rerank_lexical_weight: float = 0.3,
    *,
    ctx: Context,
) -> str:
    """
    Hybrid search rendered as a Markdown context pack of Swift source with line numbers.

    The answer to "how does X work?": ranked, deduplicated snippets ready to
    read. Same search and ``rerank_mode`` as ``query``.

    :param q: Natural-language query, e.g. "request error handling".
    :param k: Semantic seed nodes (1-100, default 8).
    :param hop: Graph expansion hops (0-5, default 1).
    :param rels: Edge types to follow; omit for all six Swift relations.
    :param context: Extra lines around each definition (default 5).
    :param max_lines: Longest snippet, in lines (1-2000, default 60).
    :param max_nodes: Most snippets (default 15).
    :param min_score: Minimum semantic score for a seed, 0.0-1.0.
    :param max_per_module: Most nodes from one module (default 3; 0 disables).
    :param rerank_mode: ``hybrid`` (default), ``semantic`` or ``legacy``.
    :param rerank_semantic_weight: Semantic weight for ``hybrid`` (default 0.7).
    :param rerank_lexical_weight: Lexical weight for ``hybrid`` (default 0.3).
    """
    result = kg_from(ctx).pack(
        q,
        k=k,
        hop=hop,
        rels=tuple(rels) if rels else _DEFAULT_RELS,
        context=context,
        max_lines=max_lines,
        max_nodes=max_nodes,
        min_score=min_score,
        max_per_module=max_per_module if max_per_module > 0 else None,
        rerank_mode=rerank_mode,
        rerank_semantic_weight=rerank_semantic_weight,
        rerank_lexical_weight=rerank_lexical_weight,
    )
    return result.to_markdown()


# ---------------------------------------------------------------------------
# SwiftKG's own tools
# ---------------------------------------------------------------------------


def callers(node_id: str, rel: str = "CALLS", paths: str = "", *, ctx: Context) -> str:
    """
    Return all nodes that call a given node, resolving through ``sym:`` stubs.

    Unlike ``query`` (which seeds on semantics and expands outward),
    this tool performs a precise reverse lookup: it finds every caller of the
    specified node, including cross-module callers that reference it via an
    import alias recorded as a ``sym:`` stub.

    The ``rel`` parameter accepts any edge relation, not just ``CALLS``::

        callers(node_id, rel="INHERITS")    # find all subclasses
        callers(node_id, rel="CONFORMS")    # every type conforming to a protocol
        callers(node_id, rel="IMPORTS")     # find all importers

    Typical workflow::

        # 1. Resolve the exact node ID
        get_node("meth:Sources/Networking/Client.swift:HTTPClient.send")

        # 2. Find all callers (production code only)
        callers("meth:Sources/Networking/Client.swift:HTTPClient.send", paths="Sources/")

    :param node_id: Target node identifier, e.g.
                    ``cls:Sources/Networking/Client.swift:HTTPClient``.
    :param rel: Relation type to invert (default ``"CALLS"``).
    :param paths: Comma-separated module path prefixes to include, e.g.
                  ``"Sources/"`` to exclude test callers.
                  Empty string (default) returns all callers.
    :return: JSON with ``node_id``, ``rel``, ``caller_count``, and
             ``callers`` list of node dicts.
    """
    caller_list = kg_from(ctx).callers(node_id, rel=rel)
    if paths:
        path_prefixes = [p.strip() for p in paths.split(",") if p.strip()]
        caller_list = [
            c
            for c in caller_list
            if any((c.get("module_path") or "").startswith(pfx) for pfx in path_prefixes)
        ]
    return json.dumps(
        {
            "node_id": node_id,
            "rel": rel,
            "caller_count": len(caller_list),
            "callers": caller_list,
        },
        indent=2,
        ensure_ascii=False,
    )


def type_hierarchy(node_id: str, *, ctx: Context) -> str:
    """
    Return everything the graph knows about one Swift type's relationships.

    Swift spreads a type across three relations that the sibling language
    modules do not have to separate, and answering "what is this type" means
    reading all three at once:

    - **conformers** — every type and extension conforming to it, if it is a
      protocol. This is the question about a protocol.
    - **subclasses** — every direct subclass, if it is a class or actor.
    - **extensions** — every ``extension`` declared on it, which in Swift
      routinely live in other files. "Where is the rest of this type" is a real
      question with a graph answer.
    - **conforms_to** / **inherits_from** — what it declares for itself.

    Calling ``callers()`` three times with three relations returns the same
    facts; this returns them together, already labelled, because for a Swift
    type they are one question.

    :param node_id: Node ID of a class, struct, enum, protocol or actor, e.g.
                    ``proto:Sources/SampleKit/Storage.swift:Repository``.
    :return: JSON with ``node``, ``conformers``, ``subclasses``, ``extensions``,
             ``conforms_to`` and ``inherits_from``.
    """
    try:
        # `kg.node()` normalizes internally, but the raw argument is reused
        # below for edges_from — so a backticked ID would resolve for the
        # lookup and then silently match no edges.
        node_id = normalize_node_id(node_id)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    kg = kg_from(ctx)
    node = kg.node(node_id)
    if node is None:
        return json.dumps({"error": f"Node not found: {node_id}"}, indent=2)

    def _outgoing(rel: str) -> list:
        try:
            edges = kg.store.edges_from(node_id, rel=rel, limit=200)
        except (AttributeError, ValueError, RuntimeError):
            return []
        out = []
        for edge in edges:
            raw = edge.get("dst") if isinstance(edge, dict) else edge[1]
            if not raw:
                continue
            dst = str(raw)
            target = None if dst.startswith("sym:") else kg.node(dst)
            out.append(target or {"id": dst, "name": dst.split(":")[-1], "external": True})
        return out

    return json.dumps(
        {
            "node": node,
            "conformers": kg.conformers(node_id),
            "subclasses": kg.subclasses(node_id),
            "extensions": kg.extensions_of(node_id),
            "conforms_to": _outgoing("CONFORMS"),
            "inherits_from": _outgoing("INHERITS"),
        },
        indent=2,
        ensure_ascii=False,
    )


def public_api(module_path: str = "", limit: int = 100, *, ctx: Context) -> str:
    """
    List the declared public API surface.

    Swift states access level with a keyword and SwiftKG stores it, so this is
    a fact read out of the graph rather than a heuristic. Use it to review what
    a module actually exposes, or to find `public` declarations that no longer
    need to be.

    :param module_path: Restrict to files under this path prefix. Empty
                        (default) covers the whole repository.
    :param limit: Maximum declarations to return (1-1000).
    :return: JSON with ``count`` and a ``declarations`` list, each carrying its
             ``visibility``.
    """
    try:
        limit = bounded_int("limit", limit, 1, 1000)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    con = kg_from(ctx).store.con
    sql = """
        SELECT id, kind, name, qualname, module_path, docstring,
               json_extract(metadata, '$.visibility') AS visibility
        FROM nodes
        WHERE json_extract(metadata, '$.visibility') IN ('public', 'open')
          AND id NOT LIKE 'sym:%'
    """
    params: list = []
    if module_path:
        sql += " AND module_path LIKE ?"
        params.append(f"{module_path}%")
    sql += " ORDER BY module_path, qualname LIMIT ?"
    params.append(limit)

    rows = con.execute(sql, params).fetchall()
    declarations = [
        {
            "id": r[0],
            "kind": r[1],
            "name": r[2],
            "qualname": r[3],
            "module_path": r[4],
            "docstring": r[5],
            "visibility": r[6],
        }
        for r in rows
    ]
    return json.dumps(
        {"count": len(declarations), "declarations": declarations}, indent=2, ensure_ascii=False
    )


def list_nodes(
    module_path: str = "",
    kind: str = "",
    limit: int = 500,
    *,
    ctx: Context,
) -> str:
    """
    List nodes filtered by module path prefix and/or kind.

    :param module_path: Module path prefix filter (e.g. "Sources/Networking/Client.swift").
    :param kind: Node kind filter: module | class | struct | enum | protocol |
                 actor | extension | function | method | property | typealias.
    :return: JSON array of matching node dicts.
    """
    try:
        limit = bounded_int("limit", limit, 1, 5000)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    kg = kg_from(ctx)
    store = kg.store

    q = "SELECT id, name, qualname, kind, module_path, lineno, docstring FROM nodes WHERE 1=1"
    q += " AND id NOT LIKE 'sym:%'"
    params = []

    if module_path:
        q += " AND module_path LIKE ?"
        params.append(f"{module_path}%")
    if kind:
        q += " AND kind = ?"
        params.append(kind)

    q += " ORDER BY module_path, lineno LIMIT ?"
    params.append(limit)

    try:
        rows = store.con.execute(q, params).fetchall()
        result = []
        for r in rows:
            doc = r[6]
            if doc and len(doc) > 120:
                doc = doc[:120] + "..."
            result.append(
                {
                    "id": r[0],
                    "name": r[1],
                    "qualname": r[2],
                    "kind": r[3],
                    "module_path": r[4],
                    "lineno": r[5],
                    "docstring": doc,
                }
            )
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:  # pylint: disable=broad-except
        return json.dumps({"error": str(e)}, indent=2)


def find_node(name: str, kind: str = "", limit: int = 100, *, ctx: Context) -> str:
    """
    Find graph nodes by name without knowing their full stable ID.

    Case-insensitive match against name and qualname. Use when you know a
    function or class name from reading code and need its stable ID.

    :param name: Function, type, or protocol name to search for.
    :param kind: Optional kind filter: module | class | struct | protocol | function | method | etc.
    :return: JSON array of matching node dicts.
    """
    try:
        name = require_query(name, MAX_QUERY_LEN)
        limit = bounded_int("limit", limit, 1, 5000)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    kg = kg_from(ctx)
    store = kg.store

    name_lower = name.lower()
    q = (
        "SELECT id, name, qualname, kind, module_path, lineno, docstring "
        "FROM nodes WHERE (LOWER(name) = ? OR LOWER(qualname) LIKE ?)"
        " AND id NOT LIKE 'sym:%'"
    )
    params: list = [name_lower, f"%{name_lower}%"]
    if kind:
        q += " AND kind = ?"
        params.append(kind)
    q += " ORDER BY module_path, lineno LIMIT ?"
    params.append(limit)

    try:
        rows = store.con.execute(q, params).fetchall()
        result = []
        for r in rows:
            doc = r[6]
            if doc and len(doc) > 120:
                doc = doc[:120] + "..."
            result.append(
                {
                    "id": r[0],
                    "name": r[1],
                    "qualname": r[2],
                    "kind": r[3],
                    "module_path": r[4],
                    "lineno": r[5],
                    "docstring": doc,
                }
            )
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:  # pylint: disable=broad-except
        return json.dumps({"error": str(e)}, indent=2)


def centrality(
    top: int = 20,
    kinds: str = "",
    group_by: str = "node",
    *,
    ctx: Context,
) -> str:
    """
    Compute Structural Importance Ranking (SIR) for the indexed codebase.

    Runs a deterministic weighted PageRank over the sym-stub-resolved call
    graph.  Edge weights are tuned per relation type
    (CALLS > INHERITS/CONFORMS/EXTENDS > IMPORTS > CONTAINS) and amplified for
    cross-module links; private symbols receive a post-convergence penalty.
    Scores are normalized to sum to 1.0.

    Use this to:

    - Identify the most structurally critical functions, types, and protocols
    - Understand which modules are most depended upon
    - Prioritize code review, refactoring, or test coverage efforts

    :param top: Maximum number of ranked entries to return (default 20).
    :param kinds: Comma-separated node kinds to include: ``module``, ``class``,
                  ``struct``, ``protocol``, ``actor``, ``function``, ``method``.
                  Empty string returns
                  all kinds.  Ignored when ``group_by='module'`` (all kinds
                  contribute to module aggregation).
    :param group_by: ``node`` (default) returns individual node rankings with
                     score, inbound edge count, and cross-module inbound count;
                     ``module`` aggregates node scores per module.
    :return: Markdown-formatted ranking table.
    """
    try:
        top = bounded_int("top", top, 1, 1000)
    except ValueError as exc:
        return f"## Invalid Argument\n\n{exc}"

    try:
        from swift_kg.centrality import (  # noqa: PLC0415
            StructuralImportanceRanker,
            aggregate_module_scores,
        )

        db_path = kg_from(ctx).db_path
        ranker = StructuralImportanceRanker(db_path)
        all_records = ranker.compute()
    except Exception as e:  # noqa: BLE001
        return f"## Centrality Error\n\nFailed to compute SIR scores: `{e}`"

    out: list[str] = ["## Structural Importance Ranking (SIR)\n"]

    if group_by == "module":
        payload = aggregate_module_scores(all_records)[:top]
        out.append(f"**Group by:** module  |  **Top:** {top}\n")
        out.append("| Rank | Score | Members | Module |")
        out.append("|-----:|------:|--------:|--------|")
        for row in payload:
            out.append(
                f"| {row['rank']} | {row['score']:.6f}"
                f" | {row['member_count']} | `{row['module_path']}` |"
            )
    else:
        kind_set: set[str] | None = None
        if kinds.strip():
            kind_set = {k.strip().lower() for k in kinds.split(",") if k.strip()}

        filtered = [r for r in all_records if kind_set is None or r.kind in kind_set][:top]
        label = kinds if kind_set else "all kinds"
        out.append(f"**Group by:** node  |  **Top:** {top}  |  **Filter:** {label}\n")
        out.append("| Rank | Score | Kind | Name | Module | Inbound | XMod |")
        out.append("|-----:|------:|------|------|--------|--------:|-----:|")
        for r in filtered:
            module = f"`{r.module_path}`" if r.module_path else "—"
            out.append(
                f"| {r.rank} | {r.score:.6f} | {r.kind} | `{r.name}`"
                f" | {module} | {r.inbound_count} | {r.cross_module_inbound} |"
            )

    out.append("")
    out.append(
        "> SIR scores are normalized to sum 1.0 across all nodes.  "
        "Higher score = more structurally central.  "
        "XMod = cross-module inbound edges."
    )
    return "\n".join(out)


def bridge_centrality(
    top: int = 20,
    include_imports: bool = True,
    *,
    ctx: Context,
) -> str:
    """
    Compute module connectivity: how many unique modules each module interacts with.

    For well-modularized codebases, identifies orchestrator and hub modules that
    touch many other modules. Replaces betweenness centrality (which is meaningless
    when inter-module edges are zero).

    **Connectivity score** = (unique modules called + unique modules calling this) / 30 + frequency / 50
    Higher score = more complex coupling with other modules.

    Scores are persisted to the ``centrality_scores`` table under the
    ``module_connectivity`` metric for use by ``framework_nodes()``.

    :param top: Number of top connectivity modules to return (default 20).
    :param include_imports: Whether to include IMPORTS in connectivity (default True).
    :return: Markdown-formatted ranking table of modules by connectivity.
    """
    try:
        from swift_kg.bridge import compute_bridge_centrality  # noqa: PLC0415

        db_path = str(kg_from(ctx).db_path)
        modules = compute_bridge_centrality(
            kind="module",
            include_imports=include_imports,
            top=top,
            db_path=db_path,
        )
    except Exception as e:  # noqa: BLE001
        return f"## Module Connectivity Error\n\nFailed to compute connectivity: `{e}`"

    out: list[str] = ["## Module Connectivity (Interaction Complexity)\n"]
    out.append(f"**Top:** {top}  |  **Include imports:** {include_imports}\n")
    out.append("| Rank | Connectivity | Module |")
    out.append("|-----:|-------------:|--------|")
    for rank_idx, (mod, score) in enumerate(modules, start=1):
        out.append(f"| {rank_idx} | {score:.6f} | `{mod}` |")
    out.append("")
    out.append(
        "> Connectivity = unique modules called + unique modules calling this module.  "
        "Higher score = orchestrator/hub module with complex interactions.  "
        "Scores are persisted as `module_connectivity` metric for use by `framework_nodes()`."
    )
    return "\n".join(out)


def framework_nodes(top: int = 20, *, ctx: Context) -> str:
    """
    Identify framework-like (hub) modules using SIR + module connectivity.

    A "framework node" is a module that is both:
    - Structurally important (high SIR/PageRank — central to the graph)
    - Highly connected (calls/imports many modules — orchestrator/hub role)

    Framework score = 0.6 × normalized SIR + 0.4 × normalized connectivity,
    both auto-computed on first call. High-scoring modules are critical hubs:
    architecturally central AND complex in their interactions.

    :param top: Number of top framework-like modules to return (default 20).
    :return: Markdown-formatted ranking table of framework nodes.
    """
    try:
        top = bounded_int("top", top, 1, 1000)
    except ValueError as exc:
        return f"## Invalid Argument\n\n{exc}"

    try:
        from swift_kg.bridge import compute_bridge_centrality  # noqa: PLC0415
        from swift_kg.centrality import StructuralImportanceRanker  # noqa: PLC0415
        from swift_kg.framework_detector import detect_framework_nodes  # noqa: PLC0415

        kg = kg_from(ctx)
        db_path = str(kg.db_path)

        # Compute and persist SIR scores (structural importance)
        try:
            ranker = StructuralImportanceRanker(db_path)
            records = ranker.compute()
            ranker.write_scores(records, metric="sir_pagerank")
        except Exception as e:  # noqa: BLE001
            return f"## Framework Nodes Error\n\nFailed to compute SIR scores: `{e}`"

        # Compute and persist module connectivity scores (interaction complexity)
        try:
            compute_bridge_centrality(kind="module", include_imports=True, top=25, db_path=db_path)
        except Exception as e:  # noqa: BLE001
            return f"## Framework Nodes Error\n\nFailed to compute module connectivity: `{e}`"

        # Detect framework nodes by combining both metrics
        nodes = detect_framework_nodes(limit=top, db_path=db_path)
    except Exception as e:  # noqa: BLE001
        return f"## Framework Nodes Error\n\nFailed to detect framework nodes: `{e}`"

    out: list[str] = ["## Framework-like Modules (Critical Hubs)\n"]
    out.append(f"**Top:** {top}  |  **Score:** 0.6 × SIR + 0.4 × connectivity (both normalized)\n")
    out.append("| Rank | Score | Module |")
    out.append("|-----:|------:|--------|")
    for rank_idx, (_, score, label) in enumerate(nodes, start=1):
        out.append(f"| {rank_idx} | {score:.6f} | `{label}` |")
    out.append("")
    out.append(
        "> Framework nodes: both architecturally central (SIR) AND heavily connected "
        "(calls/imports many modules).  High-scoring modules are critical orchestrators/hubs."
    )
    return "\n".join(out)


def find_definition_at(file: str, line: int, *, ctx: Context) -> str:
    """
    Find the code node whose definition spans a given file location.

    Reverse-resolves a ``(file, line)`` pair to a graph node ID and returns the
    same Markdown report as ``explain()``.  Useful when reading a file in an IDE
    and wanting to understand the symbol at a specific line without constructing
    a node ID manually.

    Matches the innermost (most-specific) function, method, type, extension,
    type alias, or enum whose ``lineno ≤ line ≤ end_lineno``.  Falls back to
    the module node when no narrower match exists.

    :param file: Module path as stored in the graph, e.g. ``Sources/Networking/Client.swift``.
                 Leading ``./`` is stripped automatically.
    :param line: Line number (1-indexed) within the file.
    :return: Markdown explanation from ``explain()``, or an informative error
             message if no node spans that location.
    """
    try:
        line = bounded_int("line", line, 1, 10_000_000)
    except ValueError as exc:
        return f"## Invalid Argument\n\n{exc}"

    kg = kg_from(ctx)
    store = getattr(kg, "_store", None) or getattr(kg, "store", None)
    if store is None:
        return "## Error\n\nNo graph store available."

    norm_file = file.lstrip("./")

    # Innermost span: smallest (end_lineno - lineno) that still contains `line`.
    rows = store.con.execute(
        """
        SELECT id
        FROM nodes
        WHERE (module_path = :f OR module_path LIKE :like)
          AND kind IN ('function', 'method', 'class', 'struct', 'enum', 'protocol',
                       'actor', 'extension', 'property', 'typealias')
          AND lineno IS NOT NULL
          AND lineno <= :ln
          AND (end_lineno IS NULL OR end_lineno >= :ln)
        ORDER BY (COALESCE(end_lineno, lineno) - lineno) ASC
        LIMIT 1
        """,
        {"f": norm_file, "like": f"%{norm_file}", "ln": line},
    ).fetchall()

    if not rows:
        # Fall back to the module node itself
        mod_rows = store.con.execute(
            "SELECT id FROM nodes WHERE kind = 'module' AND (module_path = ? OR module_path LIKE ?)",
            (norm_file, f"%{norm_file}"),
        ).fetchall()
        if not mod_rows:
            return (
                f"## No Definition Found\n\n"
                f"No function, method, type, extension or property spans "
                f"`{file}:{line}` in the graph.\n\n"
                "Check that the file path matches the module path stored in the graph "
                "(use `stats()` or `list_nodes()` to browse available modules)."
            )
        node_id = mod_rows[0][0]
    else:
        node_id = rows[0][0]

    return explain(node_id, ctx=ctx)


def analyze_repo(*, ctx: Context) -> str:
    """
    Run a full structural analysis of the indexed Swift repository.

    Executes the 14-phase SwiftKG analysis pipeline — baseline metrics,
    CodeRank, fan-in/fan-out, module coupling, critical call chains, public API
    surface, doc-comment coverage, type hierarchy and conformance, insights, snapshot
    history, and SIR centrality — and returns the results as Markdown.

    :return: Markdown-formatted analysis report.
    """
    from io import StringIO  # noqa: PLC0415

    from rich.console import Console  # noqa: PLC0415

    from swift_kg.kg import render_analysis  # noqa: PLC0415
    from swift_kg.swiftkg_thorough_analysis import SwiftKGAnalyzer  # noqa: PLC0415

    # Silence Rich output — stdout carries the MCP protocol on stdio transport.
    silent = Console(file=StringIO(), highlight=False)
    kg = kg_from(ctx)
    try:
        analyzer = SwiftKGAnalyzer(kg, console=silent, snapshot_mgr=_snapshots(kg))
        analyzer.run_analysis()
        return analyzer.to_markdown()
    except Exception as exc:  # noqa: BLE001
        # Lightweight stats-only fallback — never re-runs the noisy analyzer.
        try:
            return render_analysis(str(kg.repo_root), kg.store.stats())
        except Exception:  # noqa: BLE001
            return f"# SwiftKG Analysis\n\nAnalysis failed: {exc}\n"


def explain(node_id: str, limit: int = 10, *, ctx: Context) -> str:
    """
    Return a natural-language explanation of a code node.

    Given a node ID (e.g., ``meth:Sources/Networking/Client.swift:HTTPClient.send``),
    returns a markdown-formatted explanation that includes:

    - **What it is**: The node's kind, short description from its doc-comment
    - **Where it lives**: Module path and source location
    - **What calls it**: The callers (reverse call graph)
    - **What it calls**: The callees (functions/methods this node invokes)
    - **Documentation**: Full doc-comment if available

    This is ideal for understanding the role and context of a specific node
    without needing to read the full source code. Use ``pack()``
    to then retrieve the actual implementation.

    :param node_id: Stable node identifier, e.g.
                    ``meth:Sources/Networking/Client.swift:HTTPClient.send``.
    :param limit: Maximum callers and callees to list (default 10). Pass 0
                  to list all.
    :return: Markdown-formatted explanation ready for LLM consumption.
    """
    from swift_kg.explain import render_explain  # noqa: PLC0415

    # Validated before the KG is touched, so a bad argument is reported the
    # same way whether or not the server holds a graph. `render_explain`
    # re-checks for its CLI caller; both checks are idempotent.
    try:
        node_id = normalize_node_id(node_id)
        limit = bounded_int("limit", limit, 0, 1000)
    except ValueError as exc:
        return f"## Invalid Argument\n\n{exc}"

    return render_explain(
        kg_from(ctx),
        node_id,
        limit=limit,
        snippets_hint="pack()",
    )


def rank_nodes(
    top: int = 25,
    rels: str = "CALLS,IMPORTS,INHERITS,CONFORMS,EXTENDS",
    persist_metric: str = "",
    exclude_tests: bool = True,
    *,
    ctx: Context,
) -> str:
    """
    Compute global weighted CodeRank (PageRank) over the repository graph.

    Builds a directed weighted graph from the SQLite store and runs weighted
    PageRank to identify the most structurally important nodes.  Relation
    weights follow the CodeRank defaults: CALLS=1.0, IMPORTS=0.9,
    INHERITS/CONFORMS/EXTENDS=0.75.  Test paths are excluded by default.

    Optionally persists the scores into the ``node_metrics`` table under the
    given metric name so they can be loaded at query time without recomputing.

    :param top: Number of top-ranked nodes to return (default 25).
    :param rels: Comma-separated relations to include in the graph
                 (default ``"CALLS,IMPORTS,INHERITS,CONFORMS,EXTENDS"``).
    :param persist_metric: If non-empty, persist scores to ``node_metrics``
                           under this metric name (e.g. ``"coderank_global"``).
    :param exclude_tests: Exclude test-path nodes from the graph (default True).
    :return: JSON array of ranked node dicts with ``node_id``, ``score``,
             ``top_pct`` (e.g. ``"top 0.5%"``), ``kind``, ``qualname``,
             ``module_path``, and ``rank`` fields.
    """
    from swift_kg.coderank import (  # noqa: PLC0415
        build_code_graph,
        compute_coderank,
        persist_metric_scores,
    )

    try:
        top = bounded_int("top", top, 1, 1000)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    db_path = str(kg_from(ctx).db_path)
    rel_list = [r.strip() for r in rels.split(",") if r.strip()]

    try:
        graph = build_code_graph(
            db_path,
            include_relations=rel_list,
            exclude_test_paths=exclude_tests,
        )
        scores = compute_coderank(graph)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)}, indent=2)

    if persist_metric:
        try:
            persist_metric_scores(db_path, persist_metric, scores)
        except Exception:  # noqa: BLE001
            pass  # non-fatal — still return results

    # Filter out sym: stubs (import placeholders) — only return real code entities
    all_real_nodes = [
        (nid, s)
        for nid, s in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not nid.startswith("sym:")
    ]
    total_real = len(all_real_nodes)
    results = []
    for rank_idx, (node_id, score) in enumerate(all_real_nodes[:top], start=1):
        attrs = graph.nodes.get(node_id, {})
        top_pct = round(rank_idx / total_real * 100, 1) if total_real > 0 else 0.0
        results.append(
            {
                "rank": rank_idx,
                "node_id": node_id,
                "score": round(score, 8),
                "top_pct": f"top {top_pct:.1f}%",
                "kind": attrs.get("kind"),
                "qualname": attrs.get("qualname"),
                "module_path": attrs.get("module_path"),
            }
        )

    return json.dumps(results, indent=2, ensure_ascii=False)


def query_ranked(
    q: str,
    k: int = 8,
    mode: str = "hybrid",
    top: int = 25,
    rels: str = "CALLS,IMPORTS,INHERITS,CONFORMS,EXTENDS",
    radius: int = 2,
    exclude_tests: bool = True,
    *,
    ctx: Context,
) -> str:
    """
    Rank query results using CodeRank-enhanced hybrid or personalized PageRank.

    Combines semantic seed scores from the vector index with structural
    centrality and graph proximity to produce a final ranked list with
    explainability components.

    Two modes are available:

    - ``hybrid`` (default): 0.60 × semantic + 0.25 × centrality + 0.15 × proximity
    - ``ppr``: 0.70 × personalized PageRank + 0.30 × semantic

    :param q: Natural-language query string.
    :param k: Number of semantic seed nodes to retrieve (default 8).
    :param mode: Ranking mode — ``"hybrid"`` (default) or ``"ppr"``.
    :param top: Maximum ranked results to return (default 25).
    :param rels: Comma-separated relations to include in the local graph.
    :param radius: Graph expansion radius around seeds (default 2).
    :param exclude_tests: Exclude test-path nodes (default True).
    :return: JSON array of ranked result dicts with score components and
             ``why`` explanation strings.  ``sym:`` import stub nodes are
             always excluded from the output.
    """
    from swift_kg.coderank import (  # noqa: PLC0415
        build_code_graph,
        compute_coderank,
        rank_query_hybrid,
        rank_query_ppr,
    )

    kg = kg_from(ctx)
    db_path = str(kg.db_path)
    rel_list = [r.strip() for r in rels.split(",") if r.strip()]

    # Get semantic seeds from the vector index
    try:
        raw = kg.query(q, k=k, hop=0, rels=tuple(rel_list))
        seed_data = json.loads(raw.to_json())
        seed_nodes = seed_data.get("nodes", [])
        semantic_scores: dict[str, float] = {
            n["id"]: float((n.get("relevance") or {}).get("score", 0.0))
            for n in seed_nodes
            if (n.get("relevance") or {}).get("score", 0.0) > 0
        }
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Seed retrieval failed: {exc}"}, indent=2)

    if not semantic_scores:
        return json.dumps({"error": "No semantic seeds found for query."}, indent=2)

    try:
        graph = build_code_graph(
            db_path,
            include_relations=rel_list,
            exclude_test_paths=exclude_tests,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Graph build failed: {exc}"}, indent=2)

    global_cr = compute_coderank(graph)
    try:
        if mode == "ppr":
            results = rank_query_ppr(graph, semantic_scores, radius=radius, top_k=top)
        else:
            results = rank_query_hybrid(
                graph, semantic_scores, global_coderank=global_cr, radius=radius, top_k=top
            )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Ranking failed: {exc}"}, indent=2)

    output = []
    for rank_idx, r in enumerate(results, start=1):
        if r.node_id.startswith("sym:"):
            continue
        output.append(
            {
                "rank": rank_idx,
                "node_id": r.node_id,
                "adjusted_score": round(r.adjusted_score, 6),
                "final_score": round(r.final_score, 6),
                "semantic_score": round(r.semantic_score, 6),
                "centrality_score": round(r.centrality_score, 6),
                "proximity_score": round(r.proximity_score, 6),
                "kind": r.kind,
                "qualname": r.qualname,
                "module_path": r.module_path,
                "why": list(r.why),
            }
        )

    return json.dumps(
        {"query": q, "mode": mode, "returned": len(output), "results": output},
        indent=2,
        ensure_ascii=False,
    )


def explain_rank(node_id: str, q: str = "", *, ctx: Context) -> str:
    """
    Explain the CodeRank score components for a specific node.

    Returns a Markdown report showing the node's structural position in the
    graph: how many nodes call it, import it, or inherit from / implement /
    extend it; its global CodeRank score; and, when a query is provided, its
    semantic relevance and proximity to the query seed set.

    :param node_id: Stable node identifier, e.g.
                    ``meth:Sources/Networking/Client.swift:HTTPClient.send``.
    :param q: Optional query string.  When provided, semantic score and
              proximity to the query seed set are included in the report.
    :return: Markdown-formatted explanation of the node's rank components.
    """
    from swift_kg.coderank import (  # noqa: PLC0415
        DEFAULT_GLOBAL_RELS,
        build_code_graph,
        compute_coderank,
        compute_seed_proximity,
    )

    try:
        node_id = normalize_node_id(node_id)
    except ValueError as exc:
        return f"## Invalid Argument\n\n{exc}"

    kg = kg_from(ctx)
    db_path = str(kg.db_path)

    node = kg.node(node_id)
    if node is None:
        return f"## Node Not Found\n\nNode ID `{node_id}` does not exist."

    kind = node.get("kind", "unknown")
    name = node.get("qualname") or node.get("name", "unknown")
    out: list[str] = [f"## CodeRank Explanation: `{name}` ({kind})\n"]
    out.append(f"- **ID:** `{node_id}`")
    if node.get("module_path"):
        out.append(f"- **Module:** `{node['module_path']}`")
    out.append("")

    # Build graph and compute global CodeRank
    try:
        graph = build_code_graph(
            db_path,
            include_relations=list(DEFAULT_GLOBAL_RELS),
            exclude_test_paths=True,
        )
        scores = compute_coderank(graph)
    except Exception as exc:  # noqa: BLE001
        return f"## Error\n\nFailed to build graph: `{exc}`"

    global_score = scores.get(node_id, 0.0)
    meaningful_scores = sorted(
        (v for k, v in scores.items() if not k.startswith("sym:")), reverse=True
    )
    rank_pos = next(
        (i + 1 for i, s in enumerate(meaningful_scores) if s <= global_score),
        len(meaningful_scores),
    )

    out.append("### Global CodeRank\n")
    out.append(f"- **Score:** `{global_score:.8f}`")
    out.append(f"- **Rank:** #{rank_pos} of {len(meaningful_scores)} meaningful nodes")
    out.append("")

    # Structural context from graph
    if node_id in graph:
        in_edges = list(graph.in_edges(node_id, data=True))
        out.append("### Structural Inbound Edges\n")
        callers_count = sum(1 for _, _, d in in_edges if "CALLS" in d.get("relations", set()))
        importers_count = sum(1 for _, _, d in in_edges if "IMPORTS" in d.get("relations", set()))
        inheritors_count = sum(
            1
            for _, _, d in in_edges
            if d.get("relations", set()) & {"INHERITS", "CONFORMS", "EXTENDS"}
        )
        if callers_count:
            out.append(f"- Called by **{callers_count}** upstream node(s)")
        if importers_count:
            out.append(f"- Imported by **{importers_count}** upstream node(s)")
        if inheritors_count:
            out.append(
                f"- Inherited/implemented/extended by **{inheritors_count}** downstream node(s)"
            )
        if not (callers_count or importers_count or inheritors_count):
            out.append("- No inbound structural edges found in the ranked graph")
        out.append("")

        out_edges = list(graph.out_edges(node_id, data=True))
        if out_edges:
            out.append("### Structural Outbound Edges\n")
            out.append(f"- Calls/imports/inherits **{len(out_edges)}** downstream node(s)")
            out.append("")

    # Optional query-conditioned scores
    if q:
        out.append("### Query-Conditioned Scores\n")
        try:
            raw = kg.query(q, k=8, hop=0)
            seed_data = json.loads(raw.to_json())
            seed_nodes = seed_data.get("nodes", [])
            semantic_scores: dict[str, float] = {
                n["id"]: float((n.get("relevance") or {}).get("score", 0.0)) for n in seed_nodes
            }
            this_semantic = semantic_scores.get(node_id, 0.0)
            out.append(f"- **Query:** `{q}`")
            out.append(f"- **Semantic score:** `{this_semantic:.4f}`")

            if node_id in graph:
                seeds = list(semantic_scores.keys())
                proximity = compute_seed_proximity(graph, seeds)
                prox = proximity.get(node_id, 0.0)
                out.append(f"- **Proximity to seeds:** `{prox:.4f}`")
                if prox >= 1.0:
                    out.append("  → Direct semantic seed")
                elif prox >= 0.5:
                    out.append("  → One hop from a semantic seed")
                elif prox > 0:
                    out.append("  → Within local query neighborhood")
                else:
                    out.append("  → Outside query neighborhood")
        except Exception as exc:  # noqa: BLE001
            out.append(f"- Query scoring failed: `{exc}`")
        out.append("")

    out.append("---\n")
    out.append(
        "*Use `rank_nodes()` for global top-N ranking, or `query_ranked()` for query-conditioned ranking.*"
    )
    return "\n".join(out)


def snapshot_list(limit: int = 10, branch: str = "", *, ctx: Context) -> str:
    """
    List saved temporal snapshots of codebase metrics in reverse chronological order.

    Each entry in the returned list contains a ``key`` (tree hash snapshot
    identifier), ``branch``, ``timestamp``, ``version``, and a summary of
    key metrics (node count, edge count, doc-comment coverage) plus deltas vs. the
    previous snapshot.  Use the ``key`` field when calling ``snapshot_show()``
    or ``snapshot_diff(key_a=..., key_b=...)``.

    Use this tool to answer questions like "how has the codebase grown?" or
    "when did doc-comment coverage improve?" or "show me only main-branch snapshots".

    :param limit: Maximum number of snapshots to return (default 10; pass 0 for all).
    :param branch: If provided, filter to snapshots from this branch only
                   (e.g. ``"main"`` or ``"develop"``).
    :return: JSON array of snapshot metadata dicts, most recent first.
    """
    try:
        # 0 keeps its documented meaning of "all", so the floor is 0, not 1.
        limit = bounded_int("limit", limit, 0, 1000)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    mgr = _snapshots(kg_from(ctx))
    snapshots = mgr.list_snapshots(
        limit=limit if limit > 0 else None,
        branch=branch if branch else None,
    )
    for snap in snapshots:
        snap_metrics = snap.get("metrics", {})
        snap["freshness"] = _snapshot_freshness(kg_from(ctx), snap_metrics.get("total_nodes", 0))
    return json.dumps(snapshots, indent=2, ensure_ascii=False)


def snapshot_show(key: str = "latest", *, ctx: Context) -> str:
    """
    Show full details of a specific codebase metrics snapshot.

    Pass a snapshot key (tree hash) to retrieve that exact snapshot, or use
    the special value ``"latest"`` (default) to retrieve the most recent one.

    Snapshot keys are the ``key`` field returned by ``snapshot_list()``.

    The returned object contains the full metrics dict (total_nodes,
    total_edges, meaningful_nodes, docstring_coverage, node_counts,
    edge_counts, critical_issues, complexity_median), the top hotspots, and
    deltas computed vs. both the previous and the baseline (oldest) snapshots.

    :param key: Snapshot key to load, or ``"latest"`` for the most
                recent snapshot (default ``"latest"``).  Keys are tree
                hashes returned by ``snapshot_list()``.
    :return: JSON object with full snapshot details, or an error dict if
             the requested snapshot does not exist.
    """
    mgr = _snapshots(kg_from(ctx))

    if key == "latest":
        entries = mgr.list_snapshots(limit=1)
        if not entries:
            return json.dumps({"error": "No snapshots found."})
        key = entries[0]["key"]

    snapshot = mgr.load_snapshot(key)
    if snapshot is None:
        return json.dumps({"error": f"Snapshot not found for key: {key!r}"})
    out = snapshot.to_dict()
    out["freshness"] = _snapshot_freshness(kg_from(ctx), snapshot.metrics.get("total_nodes", 0))
    return json.dumps(out, indent=2, ensure_ascii=False)


def snapshot_diff(key_a: str, key_b: str, *, ctx: Context) -> str:
    """
    Compare two codebase metric snapshots side-by-side.

    Returns the full metrics dict for both snapshots and a computed delta
    (b − a) covering node and edge counts, plus per-kind node count and
    per-relation edge count deltas.

    Typical workflow::

        # 1. List available snapshots — note the 'key' field in each entry
        snapshot_list()

        # 2. Diff any two using the key= field values
        snapshot_diff(key_a="abc1234ef...", key_b="def5678ab...")

    :param key_a: First (older) snapshot key — the ``key`` field from
                  ``snapshot_list()`` output (a tree-hash string).
    :param key_b: Second (newer) snapshot key — the ``key`` field from
                  ``snapshot_list()`` output (a tree-hash string).
    :return: JSON object with keys ``a`` (metrics + issues list for key_a),
             ``b`` (metrics + issues list for key_b), ``delta`` (b − a),
             ``node_counts_delta``, and ``edge_counts_delta``. Returns an
             error dict if either snapshot is missing.
    """
    mgr = _snapshots(kg_from(ctx))
    result = mgr.diff_snapshots(key_a, key_b)
    if "error" not in result:
        result["freshness"] = {
            "a": _snapshot_freshness(
                kg_from(ctx), result.get("a", {}).get("metrics", {}).get("total_nodes", 0)
            ),
            "b": _snapshot_freshness(
                kg_from(ctx), result.get("b", {}).get("metrics", {}).get("total_nodes", 0)
            ),
        }
    return json.dumps(result, indent=2, ensure_ascii=False)


#: SwiftKG's own tools, registered after the canonical set in this order.
EXTRA_TOOLS = (
    callers,
    type_hierarchy,
    public_api,
    list_nodes,
    find_node,
    centrality,
    bridge_centrality,
    framework_nodes,
    find_definition_at,
    analyze_repo,
    explain,
    rank_nodes,
    query_ranked,
    explain_rank,
    snapshot_list,
    snapshot_show,
    snapshot_diff,
)


def build_server(
    repo: str | Path,
    db: str | Path | None = None,
    vectors: str | Path | None = None,
    model: str | None = None,
) -> KGServer:
    """Build the SwiftKG MCP server for one repository, without opening its graph.

    :param repo: Repository root the graph was built from.
    :param db: Graph database; ``None`` for ``<repo>/.swiftkg/graph.sqlite``.
    :param vectors: Vector store; ``None`` for ``<repo>/.swiftkg/vectors.sqlite``.
    :param model: Embedding model; ``None`` for :data:`DEFAULT_MODEL`.
    :return: The server; serve it with :func:`kg_utils.mcp.run`.
    """
    root = Path(repo).resolve()

    def open_kg() -> SwiftKG:
        return SwiftKG(root, db, vectors, model=model or DEFAULT_MODEL)

    server = make_server(
        open_kg, name="swiftkg", kind="code", version=__version__, instructions=PREAMBLE
    )
    server.canonical("query")(query)
    server.canonical("pack")(pack)
    for tool in EXTRA_TOOLS:
        server.add_tool(tool)
    return server


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``swiftkg-mcp``: the same command as ``swiftkg mcp``.

    Kept as a console script because Claude Desktop and Copilot configs name
    it; it runs the standard command, so both spellings take the same flags.

    :param argv: Arguments; ``None`` for ``sys.argv[1:]``.
    """
    from swift_kg.cli.main import mcp_command  # noqa: PLC0415

    mcp_command.main(args=argv, prog_name="swiftkg-mcp")


if __name__ == "__main__":
    main()
