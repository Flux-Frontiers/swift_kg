"""
cli/main.py — SwiftKG CLI entry point.

Usage::

    swiftkg init --repo /path/to/ts-repo
    swiftkg build --repo /path/to/ts-repo
    swiftkg query "networking layer"
    swiftkg pack "error handling" --hop 2
    swiftkg analyze /path/to/ts-repo
    swiftkg snapshot save --repo /path/to/ts-repo
    swiftkg install-hooks --repo /path/to/ts-repo
    swiftkg mcp --repo /path/to/ts-repo
"""

from __future__ import annotations

import click

from swift_kg.cli.cmd_analyze import analyze
from swift_kg.cli.cmd_bridges import bridges
from swift_kg.cli.cmd_build import build, build_index, build_sqlite, update
from swift_kg.cli.cmd_centrality import centrality
from swift_kg.cli.cmd_explain import explain
from swift_kg.cli.cmd_framework_nodes import framework_nodes
from swift_kg.cli.cmd_hooks import install_hooks
from swift_kg.cli.cmd_init import init
from swift_kg.cli.cmd_mcp import mcp_cmd
from swift_kg.cli.cmd_model import download_model
from swift_kg.cli.cmd_query import pack, query
from swift_kg.cli.cmd_snapshot import snapshot
from swift_kg.cli.cmd_viz import viz, viz3d, viz_timeline


@click.group()
@click.version_option(package_name="swift-kg")
def cli() -> None:
    """SwiftKG — knowledge graph for Swift codebases."""


cli.add_command(init)
cli.add_command(build)
cli.add_command(update)
cli.add_command(build_sqlite)
cli.add_command(build_index)
cli.add_command(query)
cli.add_command(pack)
cli.add_command(analyze)
cli.add_command(explain)
cli.add_command(centrality)
cli.add_command(bridges)
cli.add_command(framework_nodes)
cli.add_command(snapshot)
cli.add_command(viz)
cli.add_command(viz3d)
cli.add_command(viz_timeline, name="viz-timeline")
cli.add_command(install_hooks)
cli.add_command(download_model)
cli.add_command(mcp_cmd, name="mcp")
