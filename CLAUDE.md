# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Agent Identity

This repository is **Python** code — SwiftKG is a Python tool that indexes
Swift repositories. To explore *this* codebase, always use the **PyCodeKG**
MCP tools before reading files; SwiftKG cannot index itself. The SwiftKG
toolkit below is the product surface, used on Swift repositories.

```bash
# Index this repo with PyCodeKG (one-time setup; installs the pycodekg
# pre-commit hook that rebuilds the index and snapshots on every commit)
pycodekg init --repo .
```

---

## Project Overview

**Name:** swift_kg
**Description:** A tool that indexes Swift codebases into a knowledge graph and exposes it via MCP for AI agents
**Stack:** Python/Poetry (tree-sitter extraction, kgmodule-utils SDK)
**Status:** In development

---

## Partnership & Values

**CRITICAL PRINCIPLE:** Consistency is essential. Every decision, pattern and
structure must maintain alignment across the codebase — and with PyCodeKG and
TypeScriptKG, the reference implementations of the KG-module approach.
Inconsistency creates confusion, technical debt, and friction.

**Our Goal:** Write the cleanest, most efficient, beautiful code possible. Not
just functional — exceptional.

---

## SwiftKG toolkit

### MCP tools (query the live index)

Always use these first — they are faster and source-grounded.

| Tool | Purpose |
|------|---------|
| `graph_stats` | Node/edge counts by kind and relation |
| `query_codebase(q, k, hop, rels, …)` | Hybrid semantic + structural query |
| `pack_snippets(q, k, hop, …)` | Source-grounded snippet packs |
| `type_hierarchy(node_id)` | **Swift-specific.** Conformers, subclasses, extensions and declared supertypes of one type |
| `public_api(module_path, limit)` | **Swift-specific.** The declared `public`/`open` surface, read from access levels |
| `callers(node_id, rel)` | Reverse lookup through any relation, resolving `sym:` stubs |
| `get_node` / `list_nodes` / `find_node` | Precise lookup |
| `centrality` / `bridge_centrality` / `framework_nodes` | Structural rankings |
| `explain(node_id)` | Natural-language explanation of a node |
| `find_definition_at(file, line)` | Reverse-resolve a source location |
| `analyze_repo` | Full Markdown analysis |
| `rank_nodes` / `query_ranked` / `explain_rank` | CodeRank |
| `snapshot_list` / `snapshot_show` / `snapshot_diff` | Temporal snapshots |

### CLI

`swiftkg <subcommand>`, or the `swiftkg-<name>` script aliases:

`init`, `build`, `update`, `build-sqlite`, `build-index`, `query`, `pack`,
`analyze`, `explain`, `centrality`, `bridges`, `framework-nodes`, `snapshot`,
`install-hooks`, `download-model`, `mcp`.

`viz`, `viz3d` and `viz-timeline` are registered but not yet implemented; they
report that rather than erroring. See the CHANGELOG's Unreleased section.

All `swiftkg` commands operate on **Swift** repositories — point them at a
Swift repo, not at this one.

```bash
swiftkg init --repo /path/to/swift-repo
swiftkg build --repo /path/to/swift-repo
swiftkg query "networking layer"
swiftkg analyze /path/to/swift-repo
```

---

## Skills

Repo-local Claude Code skills live in `skills/` (this repo does not commit
`.claude/`):

| Skill | Purpose |
|-------|---------|
| `swiftkg` | Install, configure and use the SwiftKG MCP server and CLI |
| `swiftkg-thorough-analysis` | Run and interpret `swiftkg analyze` |
| `setup-swiftkg-mcp` | Wire up `.mcp.json` / IDE configs and verify the server |
| `sync-mcp-docs` | Keep MCP docstrings and instructions in sync (required rule below) |

---

## Project-specific rules

### No time estimates

All plans, roadmaps and task breakdowns MUST omit time estimates. Use phases,
priorities, complexity ratings and dependencies instead of dates or durations.

- Prefer `:param:` style docstrings.
- No per-file `Last Revision:` headers. Keep `Author:` and `License:`, which
  do not decay; `git log -1 --format=%cd -- <file>` is exact and free.

### MCP instruction sync (required)

- Any change to MCP tool signatures, parameters, defaults or behaviour in
  `src/swift_kg/mcp_server.py` must include a matching update to the
  `mcp = FastMCP(..., instructions=(...))` tool descriptions **in the same
  commit**.
- Keep the module docstring "Tools" list and the `FastMCP` instructions block
  aligned with the runtime tool API. `tests/test_mcp_server.py` asserts this.

### Fleet parity

SwiftKG mirrors PyCodeKG and TypeScriptKG: same MCP tool surface, same CLI
conventions, same snapshot/hook workflow, same repo hygiene. When adding or
changing behaviour, check how they do it first and stay consistent **unless
there is a Swift-specific reason to diverge** — then document the divergence
in the CHANGELOG and in a comment where it lives.

The divergences that already exist, and why:

| Divergence | Reason |
|---|---|
| `CONFORMS` instead of `IMPLEMENTS`, separate from `INHERITS` | Swift writes both with identical syntax; separating them is what the two-pass resolver is for |
| Two-pass, repo-wide extraction | Swift has no per-file imports within a module, so the repository is the correct resolution scope |
| `extension` is its own node kind | Extensions are a unit of authorship, routinely in a different file from the type |
| Visibility stored on every node | Swift states access level with a keyword; it is a fact, not a naming convention |
| Bridge centrality counts `CONFORMS`/`EXTENDS` | A Swift `import` names a module, not a file, so `IMPORTS` edges carry no file coupling |
| Public-API analysis is SQL, not a source grep | Access levels are already in the graph |

### Swift grammar

Before touching `src/swift_kg/extractor.py`, read `docs/SWIFT_GRAMMAR.md`.
Three properties of `tree-sitter-swift` produce a silently wrong graph rather
than an error, and all three are load-bearing:

1. `class_declaration` covers class, struct, enum, actor **and** extension,
   distinguished only by the `declaration_kind` field.
2. `function_declaration` carries two `name` fields (name and return type);
   `subscript_declaration` carries only the return-type one.
3. `call_expression` has no `function` field, and a subscript access parses as
   a call.

### Running the checks

Run them with the environment cleaned — an inherited `VIRTUAL_ENV` from
another repo silently redirects the hooks:

```bash
env -u VIRTUAL_ENV -u POETRY_ACTIVE pre-commit run --all-files
env -u VIRTUAL_ENV -u POETRY_ACTIVE git commit -m "..."
```
