"""
cli/cmd_analyze.py — swiftkg analyze command: thorough repository analysis.

A thin wrapper over :func:`swift_kg.swiftkg_thorough_analysis.main`, which is
also the module's ``__main__`` entry point, so the CLI and a standalone run
behave identically.
"""

from __future__ import annotations

from pathlib import Path

import click

from swift_kg.cli.options import exclude_option, include_option


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
    "--json",
    "-j",
    "json_path",
    default=None,
    type=click.Path(),
    help="Write the analysis results as JSON to this path (omit to skip JSON output).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress the per-phase console progress.",
)
@click.option(
    "--write-centrality",
    is_flag=True,
    help="Persist SIR centrality scores to the centrality_scores table in the SQLite graph.",
)
@include_option
@exclude_option
def analyze(
    repo_root: str,
    db: str | None,
    vectors: str | None,
    report_path: str | None,
    json_path: str | None,
    quiet: bool,
    write_centrality: bool,
    include_dir: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Run a thorough analysis of a Swift repository.

    Analyzes fan-in/fan-out, module coupling, CodeRank, SIR centrality,
    doc-comment coverage, type/conformance hierarchy, and other health signals.
    Outputs a Markdown report, and a JSON snapshot with ``--json``.
    """
    from swift_kg.config import (  # pylint: disable=import-outside-toplevel
        load_exclude_dirs,
        load_include_dirs,
    )
    from swift_kg.swiftkg_thorough_analysis import (  # pylint: disable=import-outside-toplevel
        main as run_analysis,
    )

    repo_path = Path(repo_root).resolve()
    results = run_analysis(
        repo_root=str(repo_path),
        db_path=db,
        vectors_path=vectors,
        report_path=report_path,
        json_path=json_path,
        quiet=quiet,
        include=load_include_dirs(repo_path) | set(include_dir),
        exclude=load_exclude_dirs(repo_path) | set(exclude_dir),
        persist_centrality=write_centrality,
    )

    # An empty result means the graph was missing; main() has already said so.
    if not results:
        raise SystemExit(1)
