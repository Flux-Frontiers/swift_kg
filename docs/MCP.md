# MCP server

`swiftkg mcp` exposes the graph to any MCP-compatible agent over stdio or SSE.

```bash
swiftkg mcp --repo /path/to/swift-repo
```

Build the graph first — the server warns and starts anyway if
`.swiftkg/graph.sqlite` is missing, so an agent gets an explanatory error
rather than a silent connection failure.

## Client configuration

### Claude Code / Kilo Code — `.mcp.json`

```json
{
  "mcpServers": {
    "swiftkg": {
      "command": "swiftkg-mcp",
      "args": ["--repo", "/path/to/swift-repo"]
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
      "command": "swiftkg-mcp",
      "args": ["--repo", "${workspaceFolder}"]
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

### Shared with the fleet

| Tool | Purpose |
|------|---------|
| `graph_stats()` | Node/edge counts by kind and relation, plus doc coverage. Start here. |
| `query_codebase(q, k, hop, rels, max_nodes, min_score, max_per_module, rerank_mode)` | Hybrid semantic + structural search |
| `pack_snippets(q, …)` | Same search, returning source as a Markdown context pack |
| `callers(node_id, rel, paths)` | Reverse lookup through any relation, resolving `sym:` stubs |
| `get_node(node_id, include_edges)` | Precise lookup by stable ID |
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

- **Explore an unfamiliar repo** — `graph_stats` → `query_codebase` → `pack_snippets`
- **Understand a type** — `find_node(name)` → `type_hierarchy(node_id)`
- **Find a protocol's implementations** — `find_node(name)` → `type_hierarchy(node_id)`
- **Review a module's exposed surface** — `public_api(module_path="Sources/Networking")`
- **Trace a symbol's use** — `find_node(name)` → `callers(node_id)`
- **Find structural hotspots** — `centrality(top=20)` or `centrality(group_by="module")`

## Notes

The server closes its SQLite handle on shutdown via a `lifespan` hook, which
covers both transports. Inputs are bounded — `k` 1–100, `hop` 0–5, `max_nodes`
1–500, queries ≤ 500 characters — and validated in the `SwiftKG` methods
themselves, so the CLI and this server are covered by one set of checks. The
SSE transport can serve beyond a trusted local environment, which is why those
are real bounds rather than ergonomics.

## Keeping the docs in sync

Any change to a tool's signature, parameters, defaults or behaviour in
`src/swift_kg/mcp_server.py` must update the module docstring's Tools list and
the `FastMCP(instructions=...)` block **in the same commit**.
`tests/test_mcp_server.py` asserts that every registered tool appears in both.
