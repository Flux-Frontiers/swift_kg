---
name: sync-mcp-docs
description: Synchronize SwiftKG's MCP documentation (README.md, docs/MCP.md, CLAUDE.md, AGENTS.md and the swiftkg skill files) with the live tool list that `swiftkg mcp --manifest` prints. The server's own instructions are generated from the tool docstrings, so only the docs outside mcp_server.py drift. Use this skill when the user says: "sync the MCP docs", "update the tool descriptions", "the MCP docs are stale", "I added/renamed/removed an MCP tool", or after any edit to the tools in src/swift_kg/mcp_server.py.
---

# Sync MCP Documentation

You are updating all SwiftKG MCP documentation to reflect the live tool list of `src/swift_kg/mcp_server.py`. Execute the following steps in order.

> **Project rule (from CLAUDE.md):** A tool's docstring is its documentation: the server's instructions and `swiftkg mcp --manifest` are generated from it. Any change to a tool's signature, parameters, defaults or behavior updates its docstring in the same commit, and the docs below follow the manifest.

---

## Step 0: Establish the Source of Truth

The server is built on `kg_utils.mcp`, and its tool list is generated, not
written by hand. Print it:

```bash
swiftkg mcp --repo . --manifest
```

The JSON lists every tool in registration order (the five canonical tools,
then `EXTRA_TOOLS`) with its description (the tool function's docstring) and
input schema (its parameters and defaults). It needs no built graph.

For each tool, record:
- **Name** and **parameters** with defaults (from `input_schema`)
- **One-line description** (the first line of `description`)
- **Return type** (JSON vs Markdown; read the function in `mcp_server.py`)

Print the complete tool inventory before proceeding. This is your ground truth.

**Example format:**
```
TOOL INVENTORY (from swiftkg mcp --manifest):
  1. stats()                                 -> JSON -- node/edge counts, fleet stats shape
  2. query(q, k, hop, rels, max_nodes, min_score, max_per_module, rerank_mode, ...)
                                             -> JSON -- hybrid semantic + structural search
  3. pack(q, k, hop, rels, context, max_lines, max_nodes, ...)
                                             -> MD   -- source-grounded snippet extraction
  4. get_node(node_id)                       -> JSON -- single node lookup
  5. neighbors(node_id, rels, direction, limit) -> JSON -- one-hop neighborhood
  6. callers(node_id, rel, paths)            -> JSON -- reverse edge lookup / fan-in
  ...
  N. snapshot_diff(key_a, key_b)             -> JSON -- side-by-side snapshot comparison
```

Never work from a remembered list.

---

## Step 1: mcp_server.py Needs No Separate Sync

There is no hand-kept tool list in `src/swift_kg/mcp_server.py` to update.
The server's instructions are the hand-written `PREAMBLE` (workflows and
argument bounds) followed by one generated line per tool, and the manifest
reads each tool's docstring. So:

- A tool's docstring *is* its documentation. A changed signature, default or
  behavior updates that docstring in the same commit.
- Update `PREAMBLE` only if a recommended workflow or an argument bound
  changed.
- `stats`, `query`, `pack`, `get_node` and `neighbors` are canonical fleet
  names; never rename them.

---

## Step 2: Update Repository Documentation

### 2a. `README.md`

- **"MCP tools" section** — every tool must appear with correct signature and one-line description; update the tool count if stated.
- Add missing tools; update changed signatures; remove phantom tools.

### 2b. `skills/swiftkg/SKILL.md`

- **Frontmatter `description:` field** — the `using the stats / ... MCP tools` slash-separated list must name every tool.
- **"## MCP Tools" and "## CodeRank Tools" tables** — every tool appears with correct signature; add/update/remove rows in place.
- **"### Typical session workflow"** — update numbered steps if the recommended sequence changes.

### 2c. `skills/swiftkg/references/CHEATSHEET.md`

- **"Tools at a Glance" tables** — add/remove rows to match the inventory.
- **Per-tool sections** — a section (or shared section) must exist for every tool; use the existing compact, examples-first style.
- **"Parameter Quick Reference"** — parameter names and defaults must match `mcp_server.py`.

### 2d. `CLAUDE.md` (if present)

Check the repo-root `CLAUDE.md` for MCP tool tables or lists. If found, apply the same updates (tool count, signatures, descriptions) following that file's existing format.

---

## Step 3: Consistency Check

After all edits, verify:

1. **Tool count** — the count in each file matches the number of tools in the manifest.
2. **Signatures** — every file uses the same parameter names and defaults as `mcp_server.py`.
3. **No phantom tools** — no file references a tool name that no longer exists.
4. **No missing tools** — every tool in the manifest appears in every file. `tests/test_mcp_server.py` checks this for `docs/MCP.md` and `skills/swiftkg/SKILL.md`.

If inconsistencies are found, fix them before proceeding.

---

## Step 4: Stage and Prepare Commit

1. Stage all modified files:
   ```bash
   git add README.md docs/MCP.md \
           skills/swiftkg/SKILL.md \
           skills/swiftkg/references/CHEATSHEET.md
   ```
   Add `CLAUDE.md` if it was modified.

2. Write `commit.txt` with a conventional commit message:
   ```
   docs(mcp): sync all provider docs to N-tool MCP surface

   Updated tool inventory: [list added/removed/changed tools]

   Files updated:
   - docs/MCP.md: ...
   - README.md: ...
   - skills/swiftkg/SKILL.md: ...
   - skills/swiftkg/references/CHEATSHEET.md: ...
   ```

Do **not** run `git commit` — the user commits with `git commit -F commit.txt`.

---

## Completion

After all steps, print a summary:

```
✓ Source of truth: N tools from swiftkg mcp --manifest
✓ docs/MCP.md               — updated (tool tables)
✓ README.md                 — updated (MCP tools section)
✓ skills/swiftkg/SKILL.md  — updated (frontmatter + tool tables)
✓ references/CHEATSHEET.md  — updated (N tools)

Files staged. Ready to commit with: git commit -F commit.txt
```

---

## Rules

- **The manifest is always the source of truth.** Never invent tool names or parameters.
- **Tool docstrings are the documentation** -- fix a wrong description in the docstring, not only in the docs.
- **Preserve each file's style.** Don't homogenize formats across files.
- **Minimal diffs.** Only change what is wrong or missing; don't rewrite sections that are correct.
- **Compact style in SKILL.md** (one line per tool in tables); **examples style in CHEATSHEET.md** (actual call syntax).
