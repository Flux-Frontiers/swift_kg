"""
cli/cmd_viz.py — swiftkg viz / viz3d / viz-timeline commands.

The visualization surface is not in SwiftKG's first release. These commands
exist anyway, and report that, rather than being absent: every other module in
the fleet registers them, so a user coming from ``pycodekg`` or ``tscodekg``
will type ``swiftkg viz`` and deserves an answer better than
``Error: No such command``. An unimplemented command that names what is
missing and what to use instead is a better artifact than a CLI whose help
text differs from its siblings for reasons the user cannot see.

Tracked in the CHANGELOG's Unreleased section. When the port lands, these
bodies are replaced; the command names, options and registration do not change.
"""

from __future__ import annotations

import click

_NOT_YET = (
    "The SwiftKG visualizers are not part of this release.\n"
    "\n"
    "The graph itself is complete and queryable — `swiftkg analyze` produces a\n"
    "full Markdown report, and `swiftkg centrality`, `swiftkg bridges` and\n"
    "`swiftkg framework-nodes` cover the structural rankings the visualizers\n"
    "render.\n"
    "\n"
    "Progress is tracked in this repository's CHANGELOG under Unreleased."
)


def _unavailable(what: str) -> None:
    click.echo(f"[swiftkg] {what} is not yet available.\n", err=True)
    click.echo(_NOT_YET, err=True)
    raise SystemExit(2)


@click.command("viz")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
@click.option("--db", default=None, help="SQLite graph path.")
@click.option("--port", default=8501, show_default=True, help="Streamlit server port.")
def viz(repo: str, db: str | None, port: int) -> None:
    """Launch the Streamlit graph explorer (not yet available)."""
    del repo, db, port
    _unavailable("The Streamlit graph explorer")


@click.command("viz3d")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
@click.option("--db", default=None, help="SQLite graph path.")
def viz3d(repo: str, db: str | None) -> None:
    """Launch the 3-D PyVista visualizer (not yet available)."""
    del repo, db
    _unavailable("The 3-D visualizer")


@click.command("viz-timeline")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
@click.option("--out", default=None, help="Output HTML path.")
def viz_timeline(repo: str, out: str | None) -> None:
    """Plot snapshot metrics over time (not yet available)."""
    del repo, out
    _unavailable("The snapshot timeline plot")
