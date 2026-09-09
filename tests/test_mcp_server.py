"""
test_mcp_server.py — import-level and registration regression tests.

The MCP server builds its ``FastMCP`` instance and registers every tool with
module-level decorators, so an incompatible ``mcp`` release breaks it at
*import* time rather than at call time — and only for people who installed
from PyPI, since a developer's pinned lock keeps working.

mcp 2.0 removed the bundled ``mcp.server.fastmcp`` module (FastMCP moved to
the standalone ``fastmcp`` package). ``pyproject.toml`` pins ``mcp<2`` for that
reason; these tests fail loudly if the pin is lifted without porting the
server, instead of shipping a broken console script.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

#: Every tool the server is expected to expose. Named rather than counted, so
#: a rename or an accidental deletion is a failure with a readable message.
EXPECTED_TOOLS = {
    "query_codebase",
    "pack_snippets",
    "callers",
    "type_hierarchy",
    "public_api",
    "get_node",
    "graph_stats",
    "list_nodes",
    "find_node",
    "centrality",
    "bridge_centrality",
    "framework_nodes",
    "find_definition_at",
    "analyze_repo",
    "explain",
    "rank_nodes",
    "query_ranked",
    "explain_rank",
    "snapshot_list",
    "snapshot_show",
    "snapshot_diff",
}


@pytest.fixture(scope="module")
def server():
    return importlib.import_module("swift_kg.mcp_server")


@pytest.fixture(scope="module")
def tool_names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.mcp.list_tools())}


class TestImportability:
    def test_server_module_imports(self, server) -> None:
        assert server is not None

    def test_fastmcp_import_path_exists(self) -> None:
        """Asserted directly so a failure names the incompatibility."""
        importlib.import_module("mcp.server.fastmcp")

    def test_entry_point_target_is_callable(self, server) -> None:
        """``swiftkg-mcp`` resolves to swift_kg.mcp_server:main."""
        assert callable(server.main)


class TestToolRegistration:
    def test_every_expected_tool_is_registered(self, tool_names: set[str]) -> None:
        assert EXPECTED_TOOLS <= tool_names

    def test_no_unexpected_tools(self, tool_names: set[str]) -> None:
        """An unlisted tool means this file and the server have drifted."""
        assert tool_names <= EXPECTED_TOOLS

    def test_swift_specific_tools_are_present(self, tool_names: set[str]) -> None:
        assert {"type_hierarchy", "public_api"} <= tool_names

    def test_every_tool_has_a_description(self, server) -> None:
        for tool in asyncio.run(server.mcp.list_tools()):
            assert tool.description, f"{tool.name} has no description"


class TestInstructionsStayInSync:
    """The repo rule: tool changes update the instructions in the same commit."""

    def test_instructions_mention_every_tool(self, server, tool_names: set[str]) -> None:
        instructions = server.mcp.instructions or ""
        missing = sorted(name for name in tool_names if name not in instructions)
        assert not missing, f"tools absent from the FastMCP instructions block: {missing}"

    def test_module_docstring_mentions_every_tool(self, server, tool_names: set[str]) -> None:
        doc = server.__doc__ or ""
        missing = sorted(name for name in tool_names if name not in doc)
        assert not missing, f"tools absent from the module docstring Tools list: {missing}"

    def test_instructions_use_swift_relations(self, server) -> None:
        instructions = server.mcp.instructions or ""
        assert "CONFORMS" in instructions
        assert "IMPLEMENTS" not in instructions


class TestUninitialisedServer:
    def test_tools_fail_clearly_before_main_runs(self, server) -> None:
        """The error must name the fix, not surface as an AttributeError."""
        if server._kg is not None:  # another test initialised it
            pytest.skip("server already initialised")
        with pytest.raises(RuntimeError, match="swiftkg-mcp"):
            server._get_kg()


class TestLifespan:
    def test_a_lifespan_hook_is_wired(self, server) -> None:
        """FLEET_STANDARDS: close the SQLite handle on shutdown, not at exit."""
        assert server.mcp.settings.lifespan is not None
