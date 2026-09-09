"""
cli/cmd_framework_nodes.py — swiftkg framework-nodes command.

Framework-like hub module detection over the SwiftKG graph.
"""

from __future__ import annotations

from pathlib import Path

import click


@click.command("framework-nodes")
@click.option(
    "--db",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(".swiftkg/graph.sqlite"),
    show_default=True,
    help="Path to the SwiftKG SQLite graph.",
)
@click.option("--top", type=int, default=25, show_default=True, help="Number of top modules.")
def framework_nodes(db: Path, top: int) -> None:
    """Show top framework-like modules (high SIR + high connectivity)."""
    from swift_kg.bridge import (  # pylint: disable=import-outside-toplevel
        compute_bridge_centrality,
    )
    from swift_kg.centrality import (  # pylint: disable=import-outside-toplevel
        StructuralImportanceRanker,
    )
    from swift_kg.framework_detector import (  # pylint: disable=import-outside-toplevel
        detect_framework_nodes,
    )

    # Both metrics must be persisted before detection can combine them.
    ranker = StructuralImportanceRanker(str(db))
    ranker.write_scores(ranker.compute(), metric="sir_pagerank")
    compute_bridge_centrality(kind="module", include_imports=True, top=top, db_path=str(db))

    nodes = detect_framework_nodes(limit=top, db_path=str(db))
    click.echo(f"Top {top} framework-like modules:")
    for node_id, score, label in nodes:
        click.echo(f"{label:50s}  {score:.5f}  ({node_id})")
