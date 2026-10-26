# MCP server

`swiftkg mcp` exposes the graph to any MCP-compatible agent over stdio or
streamable HTTP. It is built on the fleet's shared server base,
`kg_utils.mcp`, so it takes the same flags as every fleet KG server:

```bash
swiftkg mcp --repo /path/to/swift-repo
swiftkg mcp --repo REPO [--db FILE] [--vectors FILE] [--model NAME] \
            [--transport stdio|streamable-http] [--host H] [--port N]
swiftkg mcp --repo REPO --manifest   # print the tool list as JSON and exit
```

`--db` and `--vectors` default to `.swiftkg/graph.sqlite` and
`.swiftkg/vectors.sqlite`; a relative path is taken from `--repo`.
`--manifest` answers without opening the graph. `swiftkg-mcp` is the same
command under the name older configs use.

Build the graph first. A session is refused when `.swiftkg/graph.sqlite` does
not exist, rather than served an empty graph.

## Client configuration

### Claude Code / Kilo Code — `.mcp.json`

```json
{
  "mcpServers": {
    "swiftkg": {
      "command": "swiftkg",
      "args": ["mcp", "--repo", "/path/to/swift-repo"]
    }
  }
}
```

### GitHub Copilot — `.vscode/mcp.json`

```json
{
  "servers": {
    "swiftkg": {
      "type": "stdio",
      "command": "swiftkg",
      "args": ["mcp", "--repo", "${workspaceFolder}"]
    }
  }
}
```

### Claude Desktop — `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "swiftkg": {
      "command": "/absolute/path/to/.venv/bin/swiftkg-mcp",
      "args": ["--repo", "/absolute/path/to/swift-repo"]
    }
  }
}
```

Claude Desktop does not inherit your shell `PATH`, so use absolute paths.

## Tools

### Swift-specific

**`type_hierarchy(node_id)`** — everything about one type at once: its
conformers (if a protocol), subclasses, the extensions declared on it — which
in Swift routinely live in other files — and what it declares for itself.
Three `callers()` calls return the same facts; this returns them together,
labelled, because for a Swift type they are one question. Start here for any
question about a type or protocol.

**`public_api(module_path, limit)`** — the declared `public` / `open` surface.
Swift states access level with a keyword and SwiftKG stores it, so this reads
the graph rather than guessing.

### Canonical (the same names on every fleet KG server)

| Tool | Purpose |
|------|---------|
| `stats()` | Node/edge counts in the fleet shape (`kind`, `nodes.by_kind`, `edges.by_rel`), plus doc coverage and meaningful nodes. Start here. |
| `query(q, k, hop, rels, max_nodes, min_score, max_per_module, rerank_mode, ...)` | Hybrid semantic + structural search; JSON |
| `pack(q, k, hop, rels, context, max_lines, max_nodes, ...)` | Same search, returning source as a Markdown context pack |
| `get_node(node_id)` | Precise lookup by stable ID |
| `neighbors(node_id, rels, direction, limit)` | A node's one-hop neighborhood: its edges and the nodes at their far ends |

`rels` is a list (`["CALLS", "CONFORMS"]`); omitted, `query` and `pack`
follow all six Swift relations.

### Other code-graph tools

| Tool | Purpose |
|------|---------|
| `callers(node_id, rel, paths)` | Reverse lookup through any relation, resolving `sym:` stubs |
| `list_nodes(module_path, kind)` | Filter by path prefix and/or kind |
| `find_node(name, kind)` | Find by name when the ID is unknown |
| `centrality(top, kinds, group_by)` | SIR weighted PageRank |
| `bridge_centrality(top, include_imports)` | File-to-file coupling |
| `framework_nodes(top)` | Repo-defining hub files |
| `find_definition_at(file, line)` | Reverse-resolve a source location |
| `analyze_repo()` | The full Markdown analysis report |
| `explain(node_id, limit)` | Natural-language explanation of a node |
| `rank_nodes` / `query_ranked` / `explain_rank` | CodeRank global and query-conditioned ranking |
| `snapshot_list` / `snapshot_show` / `snapshot_diff` | Temporal metric snapshots |

## Relations

`callers()` inverts any of `CALLS`, `IMPORTS`, `CONTAINS`, `INHERITS`,
`CONFORMS`, `EXTENDS`.

`CONFORMS` and `INHERITS` are separate relations because Swift writes them
identically and separating them is most of what the extractor's two-pass
resolver is for. `callers(node_id, rel="CONFORMS")` is "who implements this
protocol"; `rel="INHERITS"` is "what subclasses this". Asking for
`IMPLEMENTS` — the TypeScript module's spelling — raises rather than silently
returning nothing.

## Workflows

- **Explore an unfamiliar repo** -- `stats` -> `query` -> `pack`
- **Understand a type** — `find_node(name)` → `type_hierarchy(node_id)`
- **Find a protocol's implementations** — `find_node(name)` → `type_hierarchy(node_id)`
- **Review a module's exposed surface** — `public_api(module_path="Sources/Networking")`
- **Trace a symbol's use** — `find_node(name)` → `callers(node_id)`
- **Find structural hotspots** — `centrality(top=20)` or `centrality(group_by="module")`

## Notes

The server opens the graph when a session starts and closes it when the
session ends. Under stdio, stray output from a tool goes to stderr and cannot
corrupt the protocol stream. Inputs are bounded — `k` 1–100, `hop` 0–5, `max_nodes`
1–500, queries ≤ 500 characters — and validated in the `SwiftKG` methods
themselves, so the CLI and this server are covered by one set of checks. The
streamable HTTP transport can serve beyond a trusted local environment, which is why those
are real bounds rather than ergonomics.

## Keeping the docs in sync

The server's instructions are generated: the hand-written `PREAMBLE` in
`src/swift_kg/mcp_server.py` followed by one line per tool, taken from each
tool's docstring. Nothing lists the tools by hand, so a tool's docstring is
its documentation; a change to a tool's signature, parameters, defaults or
behavior updates its docstring in the same commit. `swiftkg mcp --manifest`
prints the live tool list, and `tests/test_mcp_server.py` checks that this
page and `skills/swiftkg/SKILL.md` name every tool in it.
