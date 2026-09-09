"""
cli/cmd_explain.py — swiftkg explain command.

  explain — get a natural-language explanation of a code node by its ID
"""

from __future__ import annotations

from pathlib import Path

import click


@click.command("explain")
@click.argument("node_id", metavar="NODE_ID")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="SQLite knowledge graph path (default: <repo>/.swiftkg/graph.sqlite).",
)
@click.option(
    "--out",
    type=click.Path(),
    default=None,
    help="Output file path (default: stdout).",
)
def explain(node_id: str, repo: str, db: str | None, out: str | None) -> None:
    """Get a natural-language explanation of a code node.

    NODE_ID is the stable identifier of a node, e.g.:
    fn:Sources/SampleKit/Storage.swift:logAccess
    """
    from swift_kg.explain import render_explain  # pylint: disable=import-outside-toplevel
    from swift_kg.kg import SwiftKG  # pylint: disable=import-outside-toplevel

    kg = SwiftKG(repo_root=Path(repo).resolve(), db_path=db)

    # Fail fast for scripting: distinguish missing-node from rendered output.
    if kg.node(node_id) is None:
        click.echo(f"[ERROR] Node not found: {node_id}", err=True)
        kg.close()
        raise SystemExit(1)

    markdown_output = render_explain(
        kg,
        node_id,
        snippets_hint="swiftkg pack",
    )

    if out:
        Path(out).write_text(markdown_output)
        click.echo(f"[OK] Explanation written to {out}")
    else:
        click.echo(markdown_output)

    kg.close()
