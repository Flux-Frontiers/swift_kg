"""
test_mcp_server.py -- the SwiftKG MCP server on the fleet's shared base, ``kg_utils.mcp``.

Import-level regression tests first: an incompatible ``mcp`` release breaks
the server at import time, not call time, and only for people who installed
from PyPI (mcp 2.0 removed ``mcp.server.fastmcp``).

Then the surface step 2 of kgrag_priv's MCP centralization plan promises: the
five canonical tools first, under the same names as every fleet server, then
SwiftKG's own; ``query`` and ``pack`` keep SwiftKG's richer search; the
manifest answers without a graph and creates nothing; ``swiftkg``'s other
commands do not pay for importing ``mcp``; a real stdio subprocess serves; the
graph is opened per session and closed after; the first call of a session
works on a cold store; and the extras still answer and still report bad
arguments instead of clamping them.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from click.testing import CliRunner
from kg_utils.mcp import CANONICAL_TOOLS, manifest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

import swift_kg
from swift_kg.cli.main import cli
from swift_kg.extractor import _HAS_TREE_SITTER
from swift_kg.kg import SwiftKG
from swift_kg.mcp_server import EXTRA_TOOLS, build_server

_SRC = str(Path(swift_kg.__file__).resolve().parents[1])
_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).parent / "fixtures"

needs_tree_sitter = pytest.mark.skipif(
    not _HAS_TREE_SITTER, reason="tree-sitter-swift not installed"
)


def _built_repo(tmp_path: Path) -> Path:
    """Copy the Swift fixture repository and build its graph (no vector index).

    :param tmp_path: pytest temp directory.
    :return: The repository root, with ``.swiftkg/graph.sqlite`` written.
    """
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURES / "Sources", repo / "Sources")
    kg = SwiftKG(repo)
    kg.build_graph(wipe=True)
    kg.close()
    return repo


def _call(repo: Path, calls: list[tuple[str, dict]]) -> list:
    """Make each call, in order, in one fresh in-process session over *repo*.

    :param repo: A repository with a built graph.
    :param calls: ``(tool, arguments)`` pairs.
    :return: The ``CallToolResult`` of each call.
    """

    async def session():
        async with create_connected_server_and_client_session(build_server(repo)) as client:
            return [await client.call_tool(tool, args) for tool, args in calls]

    return anyio.run(session)


def _text(result) -> str:
    assert not result.isError, result.content
    return result.content[0].text


# ---------------------------------------------------------------------------
# Import level
# ---------------------------------------------------------------------------


def test_server_module_imports():
    """The module must import cleanly against the installed mcp release."""
    importlib.import_module("swift_kg.mcp_server")


def test_fastmcp_import_path_exists():
    """``mcp.server.fastmcp`` must exist -- mcp 2.0 removed it.

    Asserted directly so the failure names the actual incompatibility rather
    than surfacing as an opaque ImportError from kg_utils.mcp.
    """
    importlib.import_module("mcp.server.fastmcp")


def test_entry_point_target_exists():
    """``swiftkg-mcp`` resolves to swift_kg.mcp_server:main."""
    server = importlib.import_module("swift_kg.mcp_server")
    assert callable(server.main)


# ---------------------------------------------------------------------------
# The tool surface
# ---------------------------------------------------------------------------


def test_canonical_tools_come_first_then_swiftkgs_own(tmp_path):
    names = [t["name"] for t in manifest(build_server(tmp_path))["tools"]]
    assert names == [*CANONICAL_TOOLS, *(fn.__name__ for fn in EXTRA_TOOLS)]
    assert len(names) == 22
    assert {"type_hierarchy", "public_api"} <= set(names)


def test_the_server_reports_kind_code(tmp_path):
    info = manifest(build_server(tmp_path))
    assert (info["name"], info["kind"], info["version"]) == (
        "swiftkg",
        "code",
        swift_kg.__version__,
    )


def test_query_and_pack_keep_swiftkgs_richer_search(tmp_path):
    """Swapping in the plain canonical pair would have regressed ranking."""
    tools = {
        t["name"]: t["input_schema"]["properties"]
        for t in manifest(build_server(tmp_path))["tools"]
    }
    for name in ("query", "pack"):
        props = tools[name]
        assert props["rerank_mode"]["default"] == "hybrid", name
        assert props["max_per_module"]["default"] == 3, name
        assert "rerank_semantic_weight" in props and "min_score" in props, name
        assert "format" not in props, name
    assert "max_lines" in tools["pack"] and "context" in tools["pack"]


def test_every_tool_has_a_description(tmp_path):
    for spec in manifest(build_server(tmp_path))["tools"]:
        assert spec["description"], f"{spec['name']} has no description"


def test_instructions_carry_the_workflows_bounds_and_every_tool(tmp_path):
    text = build_server(tmp_path).instructions or ""
    assert "Recommended workflows" in text
    assert "Argument bounds" in text
    for bound in ("`k` 1-100", "`hop` 0-5", "`top` 1-1000"):
        assert bound in text
    assert "CONFORMS" in text and "IMPLEMENTS" not in text
    for name in (*CANONICAL_TOOLS, *(fn.__name__ for fn in EXTRA_TOOLS)):
        assert f"- `{name}`:" in text, name


def test_the_tool_docs_name_every_tool(tmp_path):
    """README-level docs drift silently; the manifest is the source of truth."""
    names = [t["name"] for t in manifest(build_server(tmp_path))["tools"]]
    for doc in ("docs/MCP.md", "skills/swiftkg/SKILL.md"):
        text = (_ROOT / doc).read_text(encoding="utf-8")
        missing = [n for n in names if not re.search(rf"(?<!\w){n}(?!\w)", text)]
        assert not missing, f"{doc} does not name {missing}"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_manifest_answers_without_a_graph_and_creates_nothing(tmp_path):
    result = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--manifest"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["canonical"] == list(CANONICAL_TOOLS)
    assert not (tmp_path / ".swiftkg").exists()


def test_manifest_is_fast(tmp_path):
    """The plan's budget is one second; the bound here leaves CI headroom."""
    start = time.perf_counter()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from swift_kg.mcp_server import main; main()",
            "--repo",
            str(tmp_path),
            "--manifest",
        ],
        check=True,
        capture_output=True,
    )
    assert time.perf_counter() - start < 5.0


def test_both_entry_points_are_the_same_command(tmp_path):
    via_cli = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--manifest"]).output
    via_script = subprocess.run(
        [
            sys.executable,
            "-c",
            "from swift_kg.mcp_server import main; main()",
            "--repo",
            str(tmp_path),
            "--manifest",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(via_cli) == json.loads(via_script)


def test_sse_is_no_longer_offered(tmp_path):
    result = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--transport", "sse"])
    assert result.exit_code == 2


def test_other_commands_do_not_import_mcp():
    """Registering ``swiftkg mcp`` must not slow every other command."""
    out = subprocess.run(
        [sys.executable, "-c", "import sys, swift_kg.cli.main; print('mcp' in sys.modules)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "False"


# ---------------------------------------------------------------------------
# A real stdio subprocess
# ---------------------------------------------------------------------------


@needs_tree_sitter
def test_stdio_subprocess_initializes_and_serves(tmp_path):
    repo = _built_repo(tmp_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from swift_kg.mcp_server import main; main()", "--repo", str(repo)],
        env={**os.environ, "PYTHONPATH": _SRC},
    )

    async def session():
        with open(tmp_path / "stderr.log", "w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as client:
                    init = await client.initialize()
                    tools = await client.list_tools()
                    stats = await client.call_tool("stats", {})
                    found = await client.call_tool("find_node", {"name": "Point"})
                    return init, tools, stats, found

    init, tools, stats, found = anyio.run(session)
    assert (init.serverInfo.name, init.serverInfo.version) == ("swiftkg", swift_kg.__version__)
    assert [t.name for t in tools.tools][:5] == list(CANONICAL_TOOLS)
    assert not stats.isError and stats.structuredContent["nodes"]["total"] > 0
    assert not found.isError and "Point" in found.content[0].text


# ---------------------------------------------------------------------------
# Lifespan: the graph is opened per session and closed after
# ---------------------------------------------------------------------------


@needs_tree_sitter
def test_the_session_opens_the_graph_and_closes_it(tmp_path, monkeypatch):
    repo = _built_repo(tmp_path)
    closed: list[SwiftKG] = []
    real_close = SwiftKG.close

    def counting_close(self: SwiftKG) -> None:
        closed.append(self)
        real_close(self)

    monkeypatch.setattr(SwiftKG, "close", counting_close)

    async def session():
        async with create_connected_server_and_client_session(build_server(repo)) as client:
            result = await client.call_tool("stats", {})
            assert not result.isError
            assert closed == [], "the graph stays open for the whole session"

    anyio.run(session)
    assert len(closed) == 1


def test_a_repo_without_a_graph_is_refused_not_served_empty(tmp_path):
    async def session():
        async with create_connected_server_and_client_session(build_server(tmp_path)) as client:
            await client.call_tool("stats", {})

    with pytest.raises(BaseException) as info:  # noqa: PT011 -- an ExceptionGroup from the task group
        anyio.run(session)
    assert "no graph at" in repr(info.value) or any(
        "no graph at" in str(e) for e in getattr(info.value, "exceptions", ())
    )
    assert not (tmp_path / ".swiftkg" / "graph.sqlite").exists()


# ---------------------------------------------------------------------------
# The canonical tools, through MCP
# ---------------------------------------------------------------------------


@needs_tree_sitter
def test_stats_answers_in_the_fleet_shape(tmp_path):
    (stats,) = _call(_built_repo(tmp_path), [("stats", {})])
    assert not stats.isError, stats.content
    data = stats.structuredContent
    assert data["kind"] == "code"
    assert data["nodes"]["by_kind"].get("protocol", 0) > 0
    assert data["edges"]["by_rel"].get("CONFORMS", 0) > 0
    assert "meaningful_nodes" in data


@needs_tree_sitter
def test_get_node_and_neighbors_accept_a_backticked_id(tmp_path):
    repo = _built_repo(tmp_path)
    (found,) = _call(repo, [("find_node", {"name": "Point", "kind": "struct"})])
    node_id = json.loads(_text(found))[0]["id"]
    node, near, missing = _call(
        repo,
        [
            ("get_node", {"node_id": f"`{node_id}`"}),
            ("neighbors", {"node_id": f"`{node_id}`", "direction": "both"}),
            ("get_node", {"node_id": "struct:Nowhere.swift:Nothing"}),
        ],
    )
    assert not node.isError and node.structuredContent["id"] == node_id
    assert not near.isError and near.structuredContent["edges"]
    assert missing.isError


# ---------------------------------------------------------------------------
# The extras still answer, including as a session's first call
# ---------------------------------------------------------------------------


@needs_tree_sitter
@pytest.mark.parametrize(
    ("tool", "args"),
    [("list_nodes", {"kind": "protocol"}), ("find_node", {"name": "Point"})],
)
def test_a_store_reading_tool_works_as_the_first_call(tmp_path, tool, args):
    """``KGModule.store`` is lazy; a tool that read ``_store`` saw ``None``."""
    (result,) = _call(_built_repo(tmp_path), [(tool, args)])
    payload = json.loads(_text(result))
    assert isinstance(payload, list) and payload, payload


@needs_tree_sitter
def test_type_hierarchy_and_public_api_answer(tmp_path):
    repo = _built_repo(tmp_path)
    (found,) = _call(repo, [("find_node", {"name": "Measurable", "kind": "protocol"})])
    proto_id = json.loads(_text(found))[0]["id"]
    hierarchy, api = _call(
        repo,
        [("type_hierarchy", {"node_id": proto_id}), ("public_api", {"limit": 50})],
    )
    data = json.loads(_text(hierarchy))
    assert data["node"]["id"] == proto_id
    assert {"conformers", "subclasses", "extensions", "conforms_to", "inherits_from"} <= set(data)
    assert json.loads(_text(api))["count"] > 0


@needs_tree_sitter
def test_analyze_repo_answers(tmp_path):
    """It imported a renderer under a name kg.py never defined, so every call failed."""
    (result,) = _call(_built_repo(tmp_path), [("analyze_repo", {})])
    assert "SwiftKG" in _text(result)


@needs_tree_sitter
def test_explain_and_snapshot_tools_answer(tmp_path):
    repo = _built_repo(tmp_path)
    (found,) = _call(repo, [("find_node", {"name": "Point", "kind": "struct"})])
    node_id = json.loads(_text(found))[0]["id"]
    explained, at, snaps = _call(
        repo,
        [
            ("explain", {"node_id": node_id}),
            ("find_definition_at", {"file": "Sources/SampleApp/Geometry.swift", "line": 6}),
            ("snapshot_list", {}),
        ],
    )
    assert "Point" in _text(explained) and "pack()" in _text(explained)
    assert "Point" in _text(at)
    assert json.loads(_text(snaps)) == []


# ---------------------------------------------------------------------------
# Boundary validation: the extras report bad arguments, never clamp them
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    if not _HAS_TREE_SITTER:
        pytest.skip("tree-sitter-swift not installed")
    return _built_repo(tmp_path_factory.mktemp("bounds"))


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
def test_an_out_of_range_argument_is_reported_not_clamped(built, tool, kwargs):
    """A truncated result that looks complete is worse than an error."""
    (result,) = _call(built, [(tool, kwargs)])
    assert "must be between" in result.content[0].text, result.content


@pytest.mark.parametrize("tool", ["type_hierarchy", "explain", "explain_rank"])
def test_an_empty_node_id_is_rejected(built, tool):
    (result,) = _call(built, [(tool, {"node_id": "  "})])
    out = result.content[0].text
    assert "node_id" in out and "empty" in out


def test_find_node_rejects_an_empty_name(built):
    """A bare name would become `LIKE '%%'` and match the whole graph."""
    (result,) = _call(built, [("find_node", {"name": "   "})])
    assert "empty" in result.content[0].text


def test_validation_failures_do_not_raise_out_of_the_tool(built):
    """An extra reports a bad argument; it does not fail the protocol."""
    (result,) = _call(built, [("public_api", {"limit": -5})])
    assert not result.isError
    assert "Invalid" in result.content[0].text or "error" in result.content[0].text


def test_a_canonical_tool_reports_a_bad_argument_as_a_tool_error(built):
    (result,) = _call(built, [("neighbors", {"node_id": "x", "limit": 10_000})])
    assert result.isError


# ---------------------------------------------------------------------------
# With the real model: query and pack through MCP
# ---------------------------------------------------------------------------


@needs_tree_sitter
@pytest.mark.slow
@pytest.mark.integration
def test_query_and_pack_with_the_real_model(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURES / "Sources", repo / "Sources")
    kg = SwiftKG(repo)
    kg.build(wipe=True)
    kg.close()

    found, packed = _call(
        repo,
        [
            ("query", {"q": "distance between two points", "k": 3}),
            ("pack", {"q": "distance between two points", "k": 3}),
        ],
    )
    assert not found.isError and found.structuredContent["returned_nodes"] >= 1
    assert found.structuredContent["nodes"][0]["relevance"]["mode"] == "hybrid"
    assert not packed.isError and "distance" in packed.content[0].text
