"""
snapshots.py — Temporal snapshots of SwiftKG metrics.

Thin layer over the shared ``kg_utils.snapshots`` module. The shared module
provides the canonical ``Snapshot``, ``SnapshotManifest``, ``SnapshotManager``
and ``PruneResult``; this module re-exports those types and adds a
``SnapshotManager`` subclass carrying two things the base cannot know: which
package stamps the version, and which metrics are Swift-specific.

Per FLEET_STANDARDS (settled 2026-09-08) this configures the base rather than
overriding it. There is no ``capture()`` override and no ``Snapshot``
subclass — a ``capture()`` override must restate the base signature, and
restating it is how an unnamed ``key=`` falls into ``**extra_metrics`` and the
snapshot silently keys on the wrong thing. That shipped in four packages.

Snapshots live in ``.swiftkg/snapshots/{key}.json`` with a ``manifest.json``
tracking all snapshots — the same layout PyCodeKG and TypeScriptKG use.

Usage
-----
>>> from swift_kg.snapshots import SnapshotManager
>>> mgr = SnapshotManager(".swiftkg/snapshots")
>>> snapshot = mgr.capture(version="0.1.0", branch="main", key="0.1.0",
...                        subject="repo:swift-kg", graph_stats_dict=stats)
>>> mgr.save_snapshot(snapshot)
>>> manifest = mgr.load_manifest()

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from typing import Any

from kg_utils.snapshots import (
    PruneResult,  # noqa: F401  re-exported
    Snapshot,  # noqa: F401  re-exported
    SnapshotManifest,  # noqa: F401  re-exported
)
from kg_utils.snapshots import SnapshotManager as _BaseSnapshotManager

__all__ = [
    "Snapshot",
    "SnapshotManifest",
    "SnapshotManager",
    "PruneResult",
]


class SnapshotManager(_BaseSnapshotManager):
    """Snapshot manager bound to the ``swift-kg`` package.

    Identical to :class:`kg_utils.snapshots.SnapshotManager` except that
    version auto-detection resolves against the installed ``swift-kg``
    package, and :meth:`_domain_metrics` adds the counts that describe a
    Swift codebase specifically.

    The constructor is the base's, inherited unchanged: ``snapshots_dir`` is
    the directory holding snapshot JSON files and the manifest, keyword-only
    ``package_name`` overrides the package whose installed version stamps
    snapshots, and keyword-only ``db_path`` points at a SQLite graph for
    per-module node counts. Described here rather than as ``:param:`` tags
    because this class declares no ``__init__`` for them to document -- griffe
    matches those against the signature the documented object itself carries,
    and reports every one of them as unmatched when there is none.
    """

    package_name = "swift-kg"

    def _domain_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Add Swift-shaped counts to the metrics a snapshot records.

        The generic ``total_nodes`` moves whenever anything moves. These are
        the numbers that say *what* moved in a Swift repository: whether the
        codebase gained protocols, whether behaviour is arriving in extensions
        rather than in the types themselves, and whether concurrency is
        spreading through actors.

        :param stats: Graph statistics from the store.
        :return: Extra metric keys merged into the snapshot's metrics.
        """
        node_counts: dict[str, int] = stats.get("node_counts", {}) or {}
        edge_counts: dict[str, int] = stats.get("edge_counts", {}) or {}

        types = sum(
            node_counts.get(kind, 0) for kind in ("class", "struct", "enum", "protocol", "actor")
        )
        extensions = node_counts.get("extension", 0)

        return {
            "swift_types": types,
            "swift_classes": node_counts.get("class", 0),
            "swift_structs": node_counts.get("struct", 0),
            "swift_enums": node_counts.get("enum", 0),
            "swift_protocols": node_counts.get("protocol", 0),
            "swift_actors": node_counts.get("actor", 0),
            "swift_extensions": extensions,
            "swift_conformances": edge_counts.get("CONFORMS", 0),
            "swift_inheritances": edge_counts.get("INHERITS", 0),
            # Extensions per type: how much of the codebase's behaviour is
            # declared away from the type it belongs to.
            "swift_extension_ratio": round(extensions / types, 4) if types else 0.0,
        }
