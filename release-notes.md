# Release Notes -- v0.5.0

> Released: 2026-10-26

SwiftKG's MCP server now runs on the fleet's shared base, `kg_utils.mcp`, so
its first five tools have the same names on every fleet KG server: `stats`,
`query`, `pack`, `get_node` and `neighbors`. Its 17 domain tools, including
`type_hierarchy` and `public_api`, keep their names. Tool names, some
arguments and the shape of `stats()` change, so read Upgrading before you
install.

## What changed

**Canonical tool names.** `graph_stats` is `stats`, `query_codebase` is
`query`, `pack_snippets` is `pack`, and `get_node(include_edges=True)` is
`get_node` followed by the new `neighbors`. There are no aliases. `query` and
`pack` keep SwiftKG's hybrid reranking and per-module cap, and when `rels` is
omitted they follow all six Swift relations.

**One command, standard flags.** `swiftkg mcp` and `swiftkg-mcp` are the same
command, with `--repo`, `--db`, `--vectors`, `--model`,
`--transport stdio|streamable-http`, `--host`, `--port` and `--manifest`. The
graph opens per session and closes after, and a repository with no graph is
refused instead of served empty. The server's instructions are generated from
the tools' docstrings.

**Statistics in the fleet shape.** `SwiftKG.stats()` returns `kind`, `nodes`
(`total`, `by_kind`) and `edges` (`total`, `by_rel`), plus the module's own
measures. Snapshots keep their flat keys.

**Fixed:** `analyze_repo` failed on every call, and `list_nodes` and
`find_node` answered "No database store available" as a session's first call.
All three work now.

## Upgrading

Rename the tools in agent instructions and scripts, pass `rels` as a list,
and drop `format="markdown"` from `query` calls and `--transport sse` from
configs. Code that read `stats()["total_nodes"]` reads `["nodes"]["total"]`
instead. swift-kg now needs kgmodule-utils 0.29.0, whose `[mcp]` extra brings
the MCP SDK.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
