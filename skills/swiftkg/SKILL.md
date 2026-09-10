---
name: swiftkg
description: Expert knowledge for installing, configuring, and using the SwiftKG MCP server — a hybrid semantic + structural knowledge graph for Swift codebases. Use this skill when the user asks about: setting up SwiftKG in a project, installing swift-kg with pip or Poetry (pip install swift-kg), building the SQLite graph or sqlite-vec vector index, configuring .mcp.json for Claude Code or Kilo Code, configuring .vscode/mcp.json for GitHub Copilot, configuring claude_desktop_config.json for Claude Desktop, using the swiftkg CLI (swiftkg init, swiftkg build, swiftkg query, swiftkg pack, swiftkg analyze, swiftkg centrality, swiftkg bridges, swiftkg framework-nodes, swiftkg explain, swiftkg snapshot, swiftkg install-hooks, swiftkg download-model, swiftkg mcp), using the graph_stats / query_codebase / pack_snippets / callers / get_node / list_nodes / find_node / centrality / bridge_centrality / framework_nodes / find_definition_at / analyze_repo / explain / rank_nodes / query_ranked / explain_rank / snapshot_list / snapshot_show / snapshot_diff MCP tools, or troubleshooting SwiftKG errors.
---

# SwiftKG Skill

> **Use SwiftKG first — before grep, Glob, or file reads.**
>
> Grep and file search find text. SwiftKG understands code. It knows what calls what, which types conform to which protocol, which modules are imported where, and surfaces the most semantically relevant source snippets in a single query. One `pack_snippets` call replaces five rounds of grep-and-read and gives the agent real structural insight into the codebase — not just line matches.

SwiftKG (package `swift-kg`, import `swift_kg`) indexes Swift repos into a hybrid knowledge graph (SQLite + sqlite-vec) via tree-sitter AST extraction on the shared kgmodule-utils SDK, and exposes it as MCP tools for AI agents.

## Installation

```bash
# pip — full KG stack (graph store + sqlite-vec index + hybrid query + MCP server)
pip install swift-kg

# Poetry
poetry add swift-kg

# From source
poetry add "swift-kg @ git+https://github.com/Flux-Frontiers/swift_kg.git"
```

The base package carries the whole stack — `kgmodule-utils[semantic,sqlite-vec]`, `mcp`, and `networkx` — so build/query/analyze/MCP all work from a plain install. Optional extras cover cross-KG (`kgdeps`) and the visualizers (`viz`, `viz3d`).

## One-Command Setup

```bash
# Downloads the embedding model, builds graph + index, installs the
# pre-commit hook, and captures an initial snapshot
swiftkg init --repo .
```

Flags: `--model` (embedding model), `--skip-hooks`, `--skip-snapshot`, `--force`.

## Build the Knowledge Graph

SwiftKG has a **single build command** — there is no `build-sqlite` / `build-index` split:

```bash
# Graph + vector index in one step
swiftkg build --repo .

# Graph only (skip embeddings)
swiftkg build --repo . --graph-only

# Vector index only (graph must already exist)
swiftkg build --repo . --index-only

# Rebuild from scratch
swiftkg build --repo .
```

Artifacts (all under `.swiftkg/`):

| Artifact | Path |
|---|---|
| SQLite graph | `.swiftkg/graph.sqlite` |
| sqlite-vec vector store | `.swiftkg/vectors.sqlite` |
| Temporal snapshots | `.swiftkg/snapshots/` |

Override with `--db` and `--vectors` if needed — defaults resolve relative to `--repo`.

## Rebuilding After Code Changes

The knowledge graph is a snapshot of the codebase at build time. It does **not** update automatically. Stale data causes misleading query results — especially after renames, deletions, or large refactors.

```bash
# Full rebuild (recommended after any structural change)
swiftkg build --repo .
```

> **Why `build` always wipes:** deleted or renamed nodes would otherwise remain as phantom entries. The vector store upserts by node ID, so a renamed symbol keeps its old entry forever. `build` clears both stores unconditionally; use `update` only when you are sure nothing was deleted or renamed. Same split as `pycodekg`.

## CLI Commands

Each command is available as `swiftkg <subcommand>` **or** a dedicated `swiftkg-<name>` script — both forms are equivalent:

| Subcommand / Script alias | Purpose |
|---|---|
| `init` / `swiftkg-init` | One-command setup: model, build, hooks, snapshot |
| `build` / `swiftkg-build` | Full rebuild — wipes, then SQLite graph + sqlite-vec index (`--graph-only`, `--index-only`, `--include-dir`/`--exclude-dir`) |
| `update` / `swiftkg-update` | Incremental upsert; same options as `build`, no wipe |
| `build-sqlite` / `swiftkg-build-sqlite` | Graph stage only (`--wipe` to clear first) |
| `build-index` / `swiftkg-build-index` | Vector-index stage only; graph must exist (`--wipe` to clear first) |
| `query` / `swiftkg-query` | Hybrid semantic + structural query (`-k`, `--hop`, `--max-nodes`, `--rerank` hybrid/semantic/legacy) |
| `pack` / `swiftkg-pack` | Source-grounded snippet packs (`--max-lines`, `--out` file.md/.json) |
| `analyze` / `swiftkg-analyze` | Thorough 14-phase architectural analysis (`-o report.md`, `-j results.json`, `-q`, `--write-centrality`, `--include-dir`/`--exclude-dir`) |
| `centrality` / `swiftkg-centrality` | SIR PageRank — rank nodes or modules by structural importance |
| `bridges` | Module connectivity ranking — orchestrator/hub modules |
| `framework-nodes` | Framework-like hubs: high SIR + high connectivity |
| `explain` | Natural-language explanation of a node by ID |
| `viz` / `swiftkg-viz` | Streamlit interactive graph explorer (`--port`, `--no-browser`; needs `[viz]` extra) |
| `viz3d` / `swiftkg-viz3d` | 3-D PyVista visualizer (`--layout` allium/funnel; needs `[viz3d]` extra) |
| `viz-timeline` / `swiftkg-viz-timeline` | Plotly timeline of snapshot metrics (`--type` 2d/3d; needs `[viz]` extra) |
| `snapshot save [VERSION]` | Capture a metrics snapshot (branch/tree-hash auto-detected) |
| `snapshot list` | List snapshots newest-first (`--json`) |
| `snapshot show <key>` | Full details for one snapshot |
| `snapshot diff <a> <b>` | Compare two snapshots side-by-side |
| `snapshot prune` | Remove stale snapshots (`--dry-run`) |
| `install-hooks` / `swiftkg-install-hooks` | Install pre-commit git hook for automatic snapshots |
| `download-model` / `swiftkg-download-model` | Pre-download embedding model for offline use |
| `mcp` / `swiftkg-mcp` | Start MCP server (`--repo`, `--db`, `--vectors`, `--transport` stdio/sse) |

For detailed options: `swiftkg <command> --help`.

## Directory Includes / Excludes

Configure via `[tool.swiftkg]` in `pyproject.toml`:

```toml
[tool.swiftkg]
include = ["src"]        # top-level dirs to index (unset = all)
exclude = ["tests"]      # extra dir names excluded at every depth
```

Excluding `tests/` keeps fan-in metrics, orphan detection, and doc-comment coverage grounded in production code.

## Snapshots & Pre-Commit Hook

```bash
swiftkg install-hooks --repo .        # install the pre-commit snapshot hook (--force to overwrite)
TSCODEKG_SKIP_SNAPSHOT=1 git commit    # skip the hook for one commit
```

Snapshots live in `.swiftkg/snapshots/` and power the `snapshot_*` MCP tools.

## Offline Setup

```bash
# Pre-download the embedding model (CI, air-gapped nets, HF rate limits)
swiftkg download-model
```

Subsequent builds and queries use the cached local copy without network access.

## Configure Claude Code / Kilo Code (.mcp.json)

Both read per-repo config from `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "swiftkg": {
      "command": "swiftkg",
      "args": [
        "mcp",
        "--repo", "/absolute/path/to/repo",
        "--db",   "/absolute/path/to/repo/.swiftkg/graph.sqlite"
      ]
    }
  }
}
```

Always use **absolute paths**. Merge into existing `mcpServers` — don't overwrite other entries.

> ⚠️ Do NOT add `swiftkg` to any global settings file — use per-repo `.mcp.json` only.

## Configure GitHub Copilot (.vscode/mcp.json)

GitHub Copilot uses a different schema — `"servers"` key and `"type": "stdio"` required:

```json
{
  "servers": {
    "swiftkg": {
      "type": "stdio",
      "command": "swiftkg",
      "args": [
        "mcp",
        "--repo", "/absolute/path/to/repo",
        "--db",   "/absolute/path/to/repo/.swiftkg/graph.sqlite"
      ]
    }
  }
}
```

VS Code will prompt you to **Trust** the server on first use.

## Configure Claude Desktop (claude_desktop_config.json)

Claude Desktop has no Poetry/venv on PATH — use the absolute binary:

```bash
poetry env info --path
# → /path/to/venv ; binary: /path/to/venv/bin/swiftkg
```

Config path: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

```json
{
  "mcpServers": {
    "swiftkg": {
      "command": "/path/to/venv/bin/swiftkg",
      "args": ["mcp", "--repo", "/abs/path", "--db", "/abs/path/.swiftkg/graph.sqlite"]
    }
  }
}
```

## MCP Tools

| Tool | When to use |
|---|---|
| `graph_stats()` | First call — understand codebase size/shape |
| `query_codebase(q, k, hop, rels, max_nodes, min_score, max_per_module, rerank_mode)` | Explore graph structure, find relevant nodes; tune precision with `min_score`, diversity with `max_per_module` |
| `pack_snippets(q, k, hop, rels, context, max_lines, ...)` | Read actual source code (prefer over query_codebase) |
| `get_node(node_id, include_edges)` | Fetch node metadata; `include_edges=True` also returns outgoing edges + incoming callers |
| `list_nodes(module_path, kind)` | List nodes filtered by module path prefix and/or kind |
| `find_node(name, kind)` | Find nodes by plain name or qualname substring |
| `find_definition_at(path, line)` | Resolve the definition enclosing a file:line position — IDE-style "go to definition" |
| `callers(node_id, rel, paths)` | Fan-in lookup, resolving cross-module `sym:` stubs with import-aware filtering for ambiguous names |
| `explain(node_id)` | Natural-language explanation of a node: role, doc-comment, callers, callees |
| `centrality(top, kinds, group_by)` | SIR PageRank — rank nodes or modules by structural importance; use before refactoring |
| `bridge_centrality(top, include_imports)` | Module connectivity ranking — orchestrator/hub modules |
| `framework_nodes(top)` | Framework-like hub modules: high SIR + high connectivity |
| `analyze_repo()` | Full architectural analysis — coupling, coverage, orphans, quality grade |
| `snapshot_list(limit, branch)` | List saved metric snapshots newest-first |
| `snapshot_show(key)` | Full metrics for a snapshot key (tree hash) or `"latest"`, with freshness check vs. the live graph |
| `snapshot_diff(key_a, key_b)` | Compare two snapshots — node/edge/coverage/issues delta |

## CodeRank Tools

Structure-aware ranking that blends PageRank with semantic search.

| Tool | When to use |
|---|---|
| `rank_nodes(top, rels, persist_metric, exclude_tests)` | Global weighted CodeRank (PageRank) — most structurally important nodes across the repo |
| `query_ranked(q, k, mode, top, rels, radius, exclude_tests)` | CodeRank-enhanced query: `hybrid` (semantic + centrality + proximity) or `ppr` (personalized PageRank + semantic) |
| `explain_rank(node_id, q)` | Explain why a node ranked where it did — inbound counts, global rank, query-conditioned scores |

**CodeRank workflows:**
- Find most important nodes globally: `rank_nodes(top=25)` → `explain_rank`
- Persist global rank for later queries: `rank_nodes(persist_metric='coderank_global')`
- Structure-aware query: `query_ranked(q='request middleware', mode='hybrid')`

## Query Strategy Guide

### Choosing `k` and `hop`

| Goal | Settings |
|---|---|
| Narrow, precise lookup | `k=4, hop=0` |
| Standard exploration | `k=8, hop=1` (default) |
| Broad context sweep | `k=12, hop=2` |
| Deep dependency trace | `k=8, hop=2, rels="CALLS,IMPORTS"` |

### Choosing `rels`

| Relation | When to include |
|---|---|
| `CONTAINS` | Almost always — structural context |
| `CALLS` | Tracing execution flow |
| `IMPORTS` | Dependency analysis (module → module) |
| `INHERITS` | Class hierarchy (`class extends class`) |
| `CONFORMS` | Type or extension → protocol |
| `EXTENDS` | Extension → the type it extends |
| `RESOLVES_TO` | Connecting `sym:` stubs to definitions — used internally by `callers()`; include for traversal through import aliases |

### Typical session workflow

```
1. graph_stats()                                              → orientation
2. query_codebase("auth middleware", k=8, hop=1)              → find nodes
3. explain("cls:Sources/Networking/Client.swift:HTTPClient")       → understand before reading
4. pack_snippets("JWT validation", k=6, hop=1)                → read source
5. get_node("meth:Sources/Networking/Client.swift:HTTPClient.send", include_edges=True)
                                                              → node detail + neighborhood in one call
6. pack_snippets("error handling", k=4, hop=2, rels="CALLS")  → deeper
7. snapshot_list() / snapshot_diff("a", "b")                  → track codebase evolution
```

### Structural importance workflows

```
centrality(top=20)                                → SIR ranking by node
centrality(top=10, group_by="module")             → SIR ranking by module
bridge_centrality(top=10)                         → hub modules by connectivity
framework_nodes(top=10)                           → most critical hub modules

rank_nodes(top=25)                                → global PageRank ranking
query_ranked("request routing", mode="hybrid")    → structure-aware query
explain_rank("fn:Sources/App/Router.swift:route")      → why did this rank here?
```

## .gitignore Setup

The `.swiftkg/` directory holds the SQLite graph, sqlite-vec store, and snapshots. Graph and index are reproducible artifacts:

```gitignore
.swiftkg/
```

If you want snapshot history in git, un-ignore `.swiftkg/snapshots/` — the pre-commit hook stages snapshots atomically with each commit.

## Key Defaults

- `k=8, hop=1`; default rels: `CONTAINS,CALLS,IMPORTS,INHERITS` (add `CONFORMS,EXTENDS` for Swift type structure)
- Node kinds: `module`, `class`, `struct`, `enum`, `protocol`, `actor`, `extension`, `function`, `method`, `property`, `typealias`
- Node ID format: `<prefix>:<module_path>:<qualname>` — e.g. `struct:Sources/Model/Point.swift:Point`, `meth:Sources/Networking/Client.swift:HTTPClient.send`
- Prefixes: `mod:` file, `cls:` class, `struct:` struct, `enum:` enum, `proto:` protocol, `actor:` actor, `ext:` extension, `fn:` function, `meth:` method, `prop:` property, `type:` typealias, `sym:` unresolved symbol
- There is no `IMPLEMENTS`: Swift conformance is `CONFORMS`, and `EXTENDS` means an extension, not protocol refinement
- Transport: `stdio` (Claude Code/Desktop), `sse` (HTTP clients)

## Troubleshooting

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'mcp'` | Install the extra: `pip install swift-kg` |
| `WARNING: SQLite database not found` | Run `swiftkg build --repo .` first |
| MCP server not appearing | Use absolute paths in `.mcp.json`; restart Claude Code |
| Empty query results | Rebuild the index: `swiftkg build --repo . --index-only` |
| Pre-commit hook slow / unwanted for one commit | `TSCODEKG_SKIP_SNAPSHOT=1 git commit ...` |
| Wrong files indexed | Set `[tool.swiftkg] include` / `exclude` in `pyproject.toml`, then `swiftkg build` (not `update`) |

## Full Reference

See `references/installation.md` for complete CLI flags, MCP config templates, gitignore recommendations, and the troubleshooting table. See `references/CHEATSHEET.md` for a query cookbook covering all MCP tools.
