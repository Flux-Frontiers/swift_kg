"""
cli/cmd_mcp.py -- the server builder behind ``swiftkg mcp``.

``swiftkg mcp`` is the fleet's standard MCP command, from :mod:`kg_utils.mcp`,
registered on the group in :mod:`swift_kg.cli.main`::

    swiftkg mcp [--repo DIR] [--db FILE] [--vectors FILE] [--model NAME]
                [--transport stdio|streamable-http] [--host H] [--port N]
                [--manifest]

Neither this module nor registering the command imports ``mcp`` or the
server module, so every other ``swiftkg`` command starts as fast as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kg_utils.mcp import KGServer


def build_server(repo: Path, db: Path | None, vectors: Path | None, model: str | None) -> KGServer:
    """Build the SwiftKG server; the server module is imported only here.

    :param repo: Repository root.
    :param db: Graph database, or ``None`` for the default under ``repo``.
    :param vectors: Vector store, or ``None`` for the default under ``repo``.
    :param model: Embedding model, or ``None`` for the default.
    :return: The server, with the graph not yet opened.
    """
    from swift_kg.mcp_server import build_server as _build  # noqa: PLC0415

    return _build(repo, db, vectors, model)
