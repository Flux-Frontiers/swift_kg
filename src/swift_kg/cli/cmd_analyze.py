"""
cli/cmd_analyze.py — swiftkg analyze command: thorough repository analysis.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command("analyze")
@click.argument("repo_root", default=".", required=False)
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="SQLite knowledge graph path (default: <repo>/.swiftkg/graph.sqlite).",
)
@click.option(
    "--vectors",
    default=None,
    type=click.Path(),
    help="sqlite-vec vector store path (default: <repo>/.swiftkg/vectors.sqlite).",
)
@click.option(
    "--report",
    "-o",
    "report_path",
    default=None,
    type=click.Path(),
    help="Markdown report output path (omit to print to stdout).",
)
@click.option(
    "--write-centrality",
    is_flag=True,
    help="Persist SIR centrality scores to the centrality_scores table in the SQLite graph.",
)
def analyze(
    repo_root: str,
    db: str | None,
    vectors: str | None,
    report_path: str | None,
    write_centrality: bool,
) -> None:
    """Run a thorough analysis of a Swift repository.

    Analyzes fan-in/fan-out, module coupling, CodeRank, SIR centrality,
    doc-comment coverage, type/conformance hierarchy, and other health signals.
    Outputs a Markdown report.
    """
    from swift_kg.analysis import SwiftKGAnalyzer  # pylint: disable=import-outside-toplevel
    from swift_kg.kg import SwiftKG  # pylint: disable=import-outside-toplevel

    kg = SwiftKG(
        repo_root=Path(repo_root).resolve(),
        db_path=db,
        vectors_path=vectors,
    )
    analyzer = SwiftKGAnalyzer(kg, console=console)
    analyzer.run_analysis(report_path=report_path, persist_centrality=write_centrality)

    if report_path:
        console.print(f"[green]Report written to {report_path}[/green]")
    else:
        console.print(analyzer.to_markdown())
