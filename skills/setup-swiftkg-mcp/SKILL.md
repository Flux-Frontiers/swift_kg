---
name: setup-swiftkg-mcp
description: Set up and verify the SwiftKG MCP server for a target repository — install swift-kg, build the knowledge graph, smoke-test the query pipeline, and configure MCP clients (.mcp.json for Claude Code / Kilo Code, .vscode/mcp.json for GitHub Copilot, claude_desktop_config.json for Claude Desktop). Use this skill when the user says: "set up swiftkg for this repo", "configure the SwiftKG MCP server", "add swiftkg to .mcp.json", "index this Swift repo with swiftkg", "get swiftkg working in Claude Code / Claude Desktop / Copilot", or "verify the swiftkg server responds".
---

# SwiftKG MCP Setup & Verification

Set up the SwiftKG MCP server for a target repository and configure it for use with Claude Code and/or Claude Desktop. Execute the following steps in sequence.

## Argument Handling

This skill accepts an optional repository path argument:

- No argument — Interactive mode; ask for the target repository path
- `/setup-swiftkg-mcp /path/to/repo` — Set up SwiftKG MCP for the specified repository

---

## Step 0: Resolve the Target Repository

1. If a path argument was provided, use it as `REPO_ROOT`.
2. If not, ask the user:
   > "Which repository do you want to index with SwiftKG? Please provide the absolute path."
3. Verify the path exists and contains at least one Swift file:
   ```bash
   find "$REPO_ROOT" -name "*.swift" \
     -not -path "*/.build/*" -not -path "*/DerivedData/*" -not -path "*/Pods/*" | head -5
   ```
4. If no Swift files are found, stop and report the issue.

All artifact paths default relative to `REPO_ROOT`:
- `DB_PATH` → `$REPO_ROOT/.swiftkg/graph.sqlite`
- `VECTORS_PATH` → `$REPO_ROOT/.swiftkg/vectors.sqlite`

Do not pass `--db` or `--vectors` flags — the commands default to `.swiftkg/` automatically.

---

## Step 1: Verify SwiftKG Installation

Prefer `poetry run` in Poetry projects. If `poetry run` fails with a **Python version conflict** (e.g. "Current Python version is not allowed by the project"), fall back to the `.venv` binaries directly.

```bash
# Try poetry run first
poetry run swiftkg --version 2>&1
```

If that prints a version, set `RUNNER="poetry run"`. Otherwise use the venv binary directly:

```bash
$REPO_ROOT/.venv/bin/swiftkg --version
```

In pip environments, plain `swiftkg --version` suffices. Document which runner was used in the final report.

1. Check that the `swiftkg` entry point resolves:
   ```bash
   $RUNNER swiftkg --version
   ```
2. If not found, check whether the package is installed:
   ```bash
   $RUNNER python -m pip show swift-kg 2>/dev/null
   ```
3. If missing, instruct the user to install it — build/query/MCP all ship in the
   base package, so no extra is needed:
   ```bash
   pip install swift-kg
   # or, in Poetry projects:
   poetry add swift-kg
   ```
   Then stop — the user must install before continuing.

4. Confirm the `mcp` Python package is importable:
   ```bash
   $RUNNER python -c "import mcp; print('mcp OK')"
   ```
   If this fails, the install is incomplete — reinstall with `pip install swift-kg`.

5. Check the SwiftKG version:
   ```bash
   $RUNNER python -c "import swift_kg; print(swift_kg.__version__)"
   ```

---

## Step 2: Build the Knowledge Graph

SwiftKG builds the SQLite graph **and** the sqlite-vec index in one command — there are no separate `build-sqlite` / `build-index` steps.

1. Check whether the graph already exists:
   ```bash
   ls -lh "$REPO_ROOT/.swiftkg/graph.sqlite" 2>/dev/null
   ```
2. If it exists, ask the user:
   > "A knowledge graph already exists at `$REPO_ROOT/.swiftkg/graph.sqlite`. Rebuild it from scratch (wipe), or keep the existing graph?"
   - **Rebuild**: just run the build — it rebuilds in full by default
   - **Keep**: skip to Step 3

3. Run the build:
   ```bash
   $RUNNER swiftkg build --repo "$REPO_ROOT"
   ```
   (Use `--graph-only` / `--index-only` only if a single stage needs rebuilding.)

4. Verify both artifacts were created and are non-empty:
   ```bash
   sqlite3 "$REPO_ROOT/.swiftkg/graph.sqlite" "SELECT COUNT(*) FROM nodes; SELECT COUNT(*) FROM edges;"
   ls -lh "$REPO_ROOT/.swiftkg/vectors.sqlite"
   ```
5. Report the node and edge counts. If both are zero, warn the user — the repo may have no indexable Swift files, or `[tool.swiftkg] include` may be excluding everything.

---

## Step 3: Smoke-Test the Query Pipeline

Run a quick end-to-end test to confirm the full pipeline works before configuring any agent:

1. Graph stats check:
   ```bash
   $RUNNER python -c "
   from swift_kg.kg import SwiftKG
   import json
   kg = SwiftKG(repo_root='$REPO_ROOT')
   print(json.dumps(kg.stats(), indent=2))
   "
   ```

2. Sample query (run from `$REPO_ROOT` so `.swiftkg/` defaults resolve):
   ```bash
   cd "$REPO_ROOT" && $RUNNER swiftkg query "module structure"
   ```

3. Verify the MCP server starts and announces its config (Ctrl-C after the banner):
   ```bash
   cd "$REPO_ROOT" && timeout 10 $RUNNER swiftkg mcp --repo "$REPO_ROOT" </dev/null || true
   # Expect stderr banner: "SwiftKG MCP server starting" with repo/db/vectors/model/transport
   # and NO "WARNING: SQLite database not found"
   ```

4. If any command errors, diagnose and report the issue before proceeding.

---

## Step 4: Configure MCP Clients

The SwiftKG MCP server is started with `swiftkg mcp --repo <REPO_ROOT>` (transport `stdio` by default; `--transport sse` for HTTP clients). Always use absolute paths.

### MCP config by agent — quick reference

| Agent | Config file | Per-repo? | Key name |
|-------|-------------|-----------|----------|
| **Claude Code** | `.mcp.json` (project root) | ✅ Yes | `"mcpServers"` |
| **Kilo Code** | `.mcp.json` (project root) | ✅ Yes | `"mcpServers"` |
| **GitHub Copilot** | `.vscode/mcp.json` | ✅ Yes | `"servers"` |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` | ❌ Global only | `"mcpServers"` |
| **Cline** | `~/...saoudrizwan.claude-dev/settings/cline_mcp_settings.json` | ❌ Global only | `"mcpServers"` |

> ⚠️ **Do NOT add `swiftkg` to any global settings file.** Global files are shared across all windows — hardcoded paths point every window to the same repo. Use per-repo config files. For Cline, use a uniquely-named entry per repo (e.g. `swiftkg-myproject`).

### 4a: Claude Code / Kilo Code (.mcp.json)

1. Check if `.mcp.json` exists in `$REPO_ROOT`:
   ```bash
   cat "$REPO_ROOT/.mcp.json" 2>/dev/null
   ```
2. If an existing `swiftkg` entry is found under `mcpServers`, ask the user to replace or keep it.
3. Resolve the binary path (`which swiftkg` in the active environment, or `poetry env info --path` → `<venv>/bin/swiftkg`).
4. The entry to add/update:
   ```json
   "swiftkg": {
     "command": "<abs_path>/swiftkg",
     "args": ["mcp", "--repo", "<REPO_ROOT>"]
   }
   ```
5. Merge into the existing `mcpServers` object — do not overwrite other entries.
6. Verify no `swiftkg` entry exists in global settings (`~/.claude/settings.json`, Kilo Code `mcp_settings.json`); remove it if found.

### 4b: GitHub Copilot (.vscode/mcp.json)

Uses the `"servers"` key and requires `"type": "stdio"`:

```json
{
  "servers": {
    "swiftkg": {
      "type": "stdio",
      "command": "<abs_path>/swiftkg",
      "args": ["mcp", "--repo", "<REPO_ROOT>"]
    }
  }
}
```

Merge into the existing `servers` object. After saving, VS Code prompts you to trust the MCP server — click **Trust**.

### 4c: Claude Desktop (claude_desktop_config.json)

Claude Desktop does not inherit shell PATH — use the absolute binary path.

Config path:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
"swiftkg": {
  "command": "<abs_path>/swiftkg",
  "args": ["mcp", "--repo", "<REPO_ROOT>"]
}
```

Merge into the existing `mcpServers` object.

### 4d: Optional Extras

- Install the pre-commit snapshot hook: `$RUNNER swiftkg install-hooks --repo "$REPO_ROOT"` (skip per-commit with `TSCODEKG_SKIP_SNAPSHOT=1`).
- Add `.swiftkg/` to the repo's `.gitignore` if not already there.
- Copy the `swiftkg` skill (this repo's `skills/swiftkg/`) to `~/.claude/skills/swiftkg/` so all sessions get expert SwiftKG knowledge.

---

## Step 5: Final Report

Present a summary of everything that was done:

```
✓ SwiftKG version:  <version>
✓ Runner used:           poetry run / pip env / .venv/bin/swiftkg
✓ Repository indexed:    <REPO_ROOT>
✓ SQLite graph:          <REPO_ROOT>/.swiftkg/graph.sqlite  (<N> nodes, <M> edges)
✓ sqlite-vec index:      <REPO_ROOT>/.swiftkg/vectors.sqlite
✓ Smoke test:            passed (query + server banner)
✓ Claude Code config:    <REPO_ROOT>/.mcp.json  (swiftkg entry)
✓ Claude Desktop config: <CONFIG_PATH>  (swiftkg entry / skipped)

Restart Claude Code / Claude Desktop to activate the swiftkg MCP server.

Available tools once active:
  • graph_stats()                — codebase size and shape
  • query_codebase(q)            — semantic + structural exploration
  • pack_snippets(q)             — source-grounded code snippets
  • get_node(node_id)            — single node metadata + neighborhood
  • list_nodes(module_path, kind) — enumerate nodes in a module
  • find_node(name, kind)        — locate nodes by name
  • find_definition_at(path, line) — definition at a file:line position
  • callers(node_id)             — fan-in lookup
  • explain(node_id)             — natural-language node orientation
  • centrality(top) / bridge_centrality(top) / framework_nodes(top)
                                 — structural importance rankings
  • rank_nodes / query_ranked / explain_rank — CodeRank tools
  • analyze_repo()               — full architectural analysis
  • snapshot_list / snapshot_show / snapshot_diff — temporal tracking

Suggested first query after restart:
  graph_stats()
```

---

## Important Rules

- **Do NOT modify source files** in the target repository.
- **Do NOT run `git commit`** or any destructive git operations.
- Use **absolute paths** everywhere — relative paths will break MCP clients.
- The `mcp` package ships in the base install — plain `pip install swift-kg` is enough.
- If any step fails, stop and report the error clearly before proceeding.
- If the user's repo is very large, warn that the build and embedding steps take a while on first run (model download + embedding).

| Error | Fix |
|-------|-----|
| `swiftkg: command not found` | `pip install swift-kg` or use the absolute venv binary |
| `Current Python version is not allowed by the project` | Use `.venv/bin/swiftkg` directly instead of `poetry run swiftkg` |
| `ModuleNotFoundError: No module named 'mcp'` | Install the extra: `pip install swift-kg` |
| `WARNING: SQLite database not found` | Run `swiftkg build --repo "$REPO_ROOT"` first |
| Empty query results | `swiftkg build --repo "$REPO_ROOT" --index-only` |
| Server not appearing in Claude Code | Absolute binary path in `.mcp.json`; restart Claude Code |
| `Command not found` in VS Code MCP log | Extension host doesn't inherit shell PATH — use the absolute binary path |

---

## Rebuilding After Code Changes

When the target codebase changes, the graph must be rebuilt:

```bash
$RUNNER swiftkg build --repo "$REPO_ROOT"
```

The MCP client configs do not need to change — they point to the same file paths.
