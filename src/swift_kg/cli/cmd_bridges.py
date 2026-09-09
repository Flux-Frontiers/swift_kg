"""
cli/cmd_bridges.py — swiftkg bridges command.

Module connectivity (bridge centrality) over the SwiftKG graph.
"""

from __future__ import annotations

from pathlib import Path

import click


@click.command("bridges")
@click.option(
    "--db",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(".swiftkg/graph.sqlite"),
    show_default=True,
    help="Path to the SwiftKG SQLite graph.",
)
@click.option("--top", type=int, default=25, show_default=True, help="Number of top modules.")
@click.option("--no-imports", is_flag=True, help="Ignore IMPORTS edges.")
def bridges(db: Path, top: int, no_imports: bool) -> None:
    """Show top bridge modules by connectivity score."""
    from swift_kg.bridge import (  # pylint: disable=import-outside-toplevel
        compute_bridge_centrality,
    )

    ranked = compute_bridge_centrality(
        kind="module",
        include_imports=not no_imports,
        top=top,
        db_path=str(db),
    )
    click.echo(f"Top {top} bridge modules:")
    for mod, score in ranked:
        click.echo(f"{mod:50s}  {score:.5f}")
