"""
Module Connectivity Centrality for SwiftKG.
Measures file-to-file interaction complexity: how many unique source files
each file reaches, and is reached by. For well-modularized codebases this
identifies orchestrator and hub files.

Ported from PyCodeKG's ``analysis/bridge.py``, with one substantive change for
Swift. In the Python and TypeScript modules, IMPORTS is the backbone of this
metric, because an import there names a *file* and so resolves to a node with
a module_path. A Swift ``import`` names a whole module and resolves to a
``sym:`` stub with no module_path, so it is dropped by the join and
contributes nothing. Leaving the relation set unchanged would have produced a
technically-working metric carrying roughly half the signal it does elsewhere,
with nothing to indicate the difference.

The relations that actually cross file boundaries in Swift are CALLS,
INHERITS, CONFORMS and EXTENDS — the last two especially, since declaring a
conformance in an extension in another file is idiomatic rather than unusual,
and is exactly the coupling this metric exists to surface.

Author: Eric G. Suchanek, PhD
License: Elastic 2.0
"""

import sqlite3
from collections import defaultdict

from swift_kg.centrality import CentralityRecord, StructuralImportanceRanker


def compute_bridge_centrality(
    kind: str = "module",
    include_imports: bool = True,
    top: int = 25,
    db_path: str = "swiftkg.sqlite",
) -> list[tuple[str, float]]:
    """
    Compute module connectivity: unique module interactions per module.

    For well-modularized codebases with strong module boundaries, connectivity
    identifies which modules are hubs (calling many others) or widely depended upon
    (called by many modules).

    Replaces betweenness centrality, which is meaningless when inter-module
    edges are zero.

    :param kind: Node kind (default 'module', currently unused but kept for compatibility)
    :param include_imports: Whether to include IMPORTS in connectivity (default
        True). Retained for CLI parity with the sibling modules; in Swift,
        IMPORTS edges point at ``sym:`` module stubs with no module_path and
        so are already excluded by the join, making this flag a no-op.
    :param top: Number of top modules to return (default 25)
    :param db_path: Path to SQLite database
    :return: List of (module_path, connectivity_score) tuples
    """
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            """
            SELECT src.module_path, dst.module_path, rel
            FROM edges
            JOIN nodes AS src ON edges.src = src.id
            JOIN nodes AS dst ON edges.dst = dst.id
            WHERE rel IN ('CALLS', 'IMPORTS', 'INHERITS', 'CONFORMS', 'EXTENDS')
              AND src.module_path IS NOT NULL
              AND dst.module_path IS NOT NULL
            """
        ).fetchall()

    # Compute unique modules called + unique modules calling this module
    outbound: dict[str, set[str]] = defaultdict(set)  # modules this module calls
    inbound: dict[str, set[str]] = defaultdict(set)  # modules that call this module
    call_counts: dict[str, int] = defaultdict(int)  # total call frequency

    for src_mod, dst_mod, rel in rows:
        if not src_mod or not dst_mod:
            continue
        if rel == "IMPORTS" and not include_imports:
            continue

        # Record outbound: src_mod calls/imports dst_mod
        outbound[src_mod].add(dst_mod)
        # Record inbound: dst_mod is called/imported by src_mod
        inbound[dst_mod].add(src_mod)
        call_counts[src_mod] += 1

    # Collect all modules
    all_modules = set(outbound.keys()) | set(inbound.keys())

    # Compute connectivity score: unique modules touched (fan-out + fan-in)
    # Higher score = more coupled with other modules
    scores: dict[str, float] = {}
    for mod in all_modules:
        unique_outbound = len(outbound[mod])
        unique_inbound = len(inbound[mod])
        total_calls = call_counts[mod]

        # Normalize: average of outbound and inbound diversity + call frequency
        # Scale to [0, 1]: assume typical module touches ~15 others
        connectivity_score = (
            (unique_outbound + unique_inbound) / 30.0  # diversity (60%)
            + min(total_calls / 50.0, 1.0) * 0.4  # frequency (40%)
        ) / 1.4  # normalize to roughly [0, 1]
        scores[mod] = min(connectivity_score, 1.0)

    # Persist scores
    records = [
        CentralityRecord(
            node_id=mod,
            kind="module",
            name=mod.split("/")[-1],
            module_path=mod,
            score=score,
            rank=idx + 1,
            inbound_count=len(inbound.get(mod, set())),
            cross_module_inbound=len(inbound.get(mod, set())),  # all are cross-module
            rel_breakdown={
                "calls_to_modules": len(outbound.get(mod, set())),
                "called_by_modules": len(inbound.get(mod, set())),
            },
            top_contributors=[],
        )
        for idx, (mod, score) in enumerate(sorted(scores.items(), key=lambda x: x[1], reverse=True))
    ]

    if records:
        StructuralImportanceRanker(db_path).write_scores(records, metric="module_connectivity")

    # Return top modules by connectivity
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top]
