"""
cli/cmd_build.py — swiftkg build / update commands.

Builds the SQLite graph and sqlite-vec vector index from a Swift repo.

Two commands, not one command with a flag, mirroring ``pycodekg``:

* ``build``  wipes existing data and rebuilds from scratch.
* ``update`` upserts changes without wiping.

The split matters because the two are different operations, not a switch on
one. A rebuild is correct after renames or deletions, where an upsert leaves
phantom nodes behind — the vector store upserts by node ID, so a renamed
symbol keeps its old entry forever. Making the safe operation the bare verb
means the surprising outcome has to be asked for by name.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from swift_kg.cli.options import exclude_option, include_option

console = Console()


def _build_options(fn):
    """Apply the option set shared by ``build`` and ``update``."""
    for option in reversed(
        [
            click.option(
                "--repo", default=".", show_default=True, help="Repository root directory."
            ),
            click.option(
                "--db",
                default=None,
                help="SQLite database path (default: <repo>/.swiftkg/graph.sqlite).",
            ),
            click.option(
                "--vectors",
                default=None,
                help="sqlite-vec store path (default: <repo>/.swiftkg/vectors.sqlite).",
            ),
            click.option(
                "--graph-only",
                is_flag=True,
                default=False,
                help="Build SQLite graph only; skip vector index.",
            ),
            click.option(
                "--index-only",
                is_flag=True,
                default=False,
                help="Build vector index only; graph must already exist.",
            ),
            include_option,
            exclude_option,
        ]
    ):
        fn = option(fn)
    return fn


def _run(
    *,
    repo: str,
    db: str | None,
    vectors: str | None,
    graph_only: bool,
    index_only: bool,
    wipe: bool,
    include_dir: tuple[str, ...] = (),
    exclude_dir: tuple[str, ...] = (),
) -> None:
    """Shared body for ``build`` and ``update``.

    ``include_dir``/``exclude_dir`` scope extraction, so they are left empty by
    ``build-index``, which indexes a graph that already exists.
    """
    from swift_kg.kg import SwiftKG  # pylint: disable=import-outside-toplevel

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        console.print(f"[red]Error:[/red] Repository not found: {repo_path}")
        raise SystemExit(1)

    kg = SwiftKG(
        repo_root=repo_path,
        db_path=db,
        vectors_path=vectors,
        include=set(include_dir),
        exclude=set(exclude_dir),
    )

    console.print(f"[bold]SwiftKG {'build' if wipe else 'update'}[/bold]")
    console.print(f"  repo    : {repo_path}")
    console.print(f"  db      : {kg.db_path}")
    console.print(f"  vectors : {kg.vectors_path}")
    console.print(f"  mode    : {'full rebuild (wipes)' if wipe else 'incremental upsert'}")
    console.print()

    try:
        if index_only:
            console.print("[cyan]Building vector index...[/cyan]")
            stats = kg.build_index(wipe=wipe)
        elif graph_only:
            console.print("[cyan]Building SQLite graph...[/cyan]")
            stats = kg.build_graph(wipe=wipe)
        else:
            console.print("[cyan]Building graph + vector index...[/cyan]")
            stats = kg.build(wipe=wipe)

        console.print("[green]Done.[/green]")
        console.print(str(stats))
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Build failed:[/red] {exc}")
        raise SystemExit(1) from exc


@click.command("build")
@_build_options
def build(
    repo: str,
    db: str | None,
    vectors: str | None,
    graph_only: bool,
    index_only: bool,
    include_dir: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Build knowledge graph from scratch: wipes existing data, then extracts
    Swift AST -> graph store -> vector index."""
    _run(
        repo=repo,
        db=db,
        vectors=vectors,
        graph_only=graph_only,
        index_only=index_only,
        include_dir=include_dir,
        exclude_dir=exclude_dir,
        wipe=True,
    )


@click.command("update")
@_build_options
def update(
    repo: str,
    db: str | None,
    vectors: str | None,
    graph_only: bool,
    index_only: bool,
    include_dir: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Update knowledge graph incrementally: upserts changes without wiping
    existing data."""
    _run(
        repo=repo,
        db=db,
        vectors=vectors,
        graph_only=graph_only,
        index_only=index_only,
        include_dir=include_dir,
        exclude_dir=exclude_dir,
        wipe=False,
    )


# ---------------------------------------------------------------------------
# Granular stages, mirroring `pycodekg build-sqlite` / `pycodekg build-index`
# ---------------------------------------------------------------------------
# These reach the same two halves as `build --graph-only` / `build --index-only`,
# exposed under the names pycodekg uses so the two CLIs read alike. Unlike
# `build`/`update` they keep `--wipe`: a stage is a lower-level tool than a
# verb, and pycodekg's stages carry the flag too.
#
# One deliberate divergence: pycodekg names this option `--db` on build-sqlite
# but `--sqlite` on build-index, an inconsistency its own skill documents as a
# common mistake. Both spellings are accepted here, so muscle memory from
# either CLI works and neither is a trap.


@click.command("build-sqlite")
@click.option("--repo", default=".", show_default=True, help="Repository root directory.")
@click.option(
    "--db",
    "--sqlite",
    "db",
    default=None,
    help="SQLite database path (default: <repo>/.swiftkg/graph.sqlite).",
)
@click.option(
    "--wipe",
    is_flag=True,
    default=False,
    help="Clear existing graph data before extracting.",
)
@include_option
@exclude_option
def build_sqlite(
    repo: str,
    db: str | None,
    wipe: bool,
    include_dir: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Extract a Swift knowledge graph and store it in SQLite.

    The graph half of `build`; skips the vector index.
    """
    _run(
        repo=repo,
        db=db,
        vectors=None,
        graph_only=True,
        index_only=False,
        include_dir=include_dir,
        exclude_dir=exclude_dir,
        wipe=wipe,
    )


@click.command("build-index")
@click.option("--repo", default=".", show_default=True, help="Repository root directory.")
@click.option(
    "--sqlite",
    "--db",
    "db",
    default=None,
    help="Path to the existing SQLite graph (default: <repo>/.swiftkg/graph.sqlite).",
)
@click.option(
    "--vectors",
    default=None,
    help="sqlite-vec store path (default: <repo>/.swiftkg/vectors.sqlite).",
)
@click.option(
    "--wipe",
    is_flag=True,
    default=False,
    help="Clear the existing vector store before indexing.",
)
def build_index(repo: str, db: str | None, vectors: str | None, wipe: bool) -> None:
    """Build the sqlite-vec semantic index from an existing SQLite graph.

    The index half of `build`; the graph must already exist.
    """
    _run(
        repo=repo,
        db=db,
        vectors=vectors,
        graph_only=False,
        index_only=True,
        wipe=wipe,
    )
