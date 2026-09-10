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


class TestBoundaryValidation:
    """Per FLEET_STANDARDS (settled 2026-08-24), the MCP surface is reachable
    over SSE beyond a trusted local environment, so its arguments are real
    external inputs.

    The tools that route through ``SwiftKG.query``/``pack``/``node``/``callers``
    are validated by those overrides. These cover the Swift-specific tools that
    read the graph directly and so had no validated path.
    """

    def _call(self, server, tool: str, args: dict) -> str:
        return asyncio.run(server.mcp.call_tool(tool, args))[0][0].text

    @pytest.mark.parametrize(
        ("tool", "kwargs"),
        [
            ("public_api", {"limit": 10_000}),
            ("list_nodes", {"limit": 10_000}),
            ("find_node", {"name": "x", "limit": 10_000}),
            ("centrality", {"top": 10_000}),
            ("framework_nodes", {"top": 10_000}),
            ("rank_nodes", {"top": 10_000}),
            ("find_definition_at", {"file": "a.swift", "line": 0}),
            ("snapshot_list", {"limit": 10_000}),
        ],
    )
    def test_an_out_of_range_argument_is_reported_not_clamped(
        self, server, tool: str, kwargs: dict
    ) -> None:
        """A truncated result that looks complete is worse than an error."""
        out = self._call(server, tool, kwargs)
        assert "must be between" in out, out

    @pytest.mark.parametrize("tool", ["type_hierarchy", "explain", "explain_rank"])
    def test_an_empty_node_id_is_rejected(self, server, tool: str) -> None:
        out = self._call(server, tool, {"node_id": "  "})
        assert "node_id" in out and "empty" in out

    def test_find_node_rejects_an_empty_name(self, server) -> None:
        """A bare name would become `LIKE '%%'` and match the whole graph."""
        out = self._call(server, "find_node", {"name": "   "})
        assert "empty" in out

    def test_validation_failures_do_not_raise_out_of_the_tool(self, server) -> None:
        """An MCP tool reports a bad argument; it does not fail the protocol."""
        out = self._call(server, "public_api", {"limit": -5})
        assert "Invalid" in out or "error" in out

    def test_the_instructions_state_the_bounds(self, server) -> None:
        """An agent should not have to discover the ranges by trial and error."""
        instructions = server.mcp.instructions or ""
        assert "Argument bounds" in instructions
        for bound in ("`k` 1-100", "`hop` 0-5", "`top` 1-1000"):
            assert bound in instructions

    def test_the_instructions_list_every_tools_parameters(self, server) -> None:
        """The repo rule: signatures and the instructions block stay aligned."""
        import inspect

        instructions = server.mcp.instructions or ""
        for name in ("list_nodes", "find_node", "public_api"):
            for param in inspect.signature(getattr(server, name)).parameters:
                assert param in instructions, f"{name}({param}) missing from instructions"
