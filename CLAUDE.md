# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Agent Identity

This repository is **Python** code — SwiftKG is a Python tool that indexes
Swift repositories. To explore *this* codebase, always use the **PyCodeKG**
MCP tools before reading files; SwiftKG cannot index itself. The SwiftKG
toolkit below is the product surface, used on Swift repositories.

```bash
# Index this repo with PyCodeKG (one-time setup). This also installs the
# pycodekg pre-commit hook, which runs the quality checks from
# .pre-commit-config.yaml and nothing else by default: the index rebuild and
# metrics snapshot are opt-in (PYCODEKG_SNAPSHOT=1) and run only on the
# default branch. Snapshots have been off by default fleet-wide since
# 2026-08-18 -- see kgrag_priv/docs/SNAPSHOT_STRATEGY.md.
#
# The hook owns .git/hooks/pre-commit, the same file `pre-commit install`
# writes. It already delegates to pre-commit, so do not run `pre-commit
# install` afterwards -- that would replace it and drop the rebuild path.
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
| `stats` | Node/edge counts by kind and relation (fleet stats shape) |
| `query(q, k, hop, rels, ...)` | Hybrid semantic + structural query |
| `pack(q, k, hop, ...)` | Source-grounded snippet packs |
| `type_hierarchy(node_id)` | **Swift-specific.** Conformers, subclasses, extensions and declared supertypes of one type |
| `public_api(module_path, limit)` | **Swift-specific.** The declared `public`/`open` surface, read from access levels |
| `callers(node_id, rel)` | Reverse lookup through any relation, resolving `sym:` stubs |
| `get_node` / `list_nodes` / `find_node` | Precise lookup |
| `neighbors(node_id, rels, direction, limit)` | A node's one-hop neighborhood |
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

### MCP tool docs (required)

- The server is built on `kg_utils.mcp`. Its instructions are generated: the
  hand-written `PREAMBLE` in `src/swift_kg/mcp_server.py` followed by one line
  per tool, taken from each tool's docstring. Nothing lists the tools by hand,
  so a tool's docstring *is* its documentation: any change to a tool's
  signature, parameters, defaults or behavior updates its docstring in the
  same commit.
- `stats`, `query`, `pack`, `get_node` and `neighbors` are the fleet's
  canonical tools, the same names on every KG server. `query` and `pack` are
  SwiftKG's richer versions, registered with `server.canonical(...)`, which
  refuses any change that drops or retypes a canonical parameter. New tools go
  in `EXTRA_TOOLS`.
- `swiftkg mcp --manifest` prints the live tool list as JSON; generate tool
  references from it rather than writing them by hand.
  `tests/test_mcp_server.py` checks that `docs/MCP.md` and
  `skills/swiftkg/SKILL.md` name every tool in it.

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
| Ambiguous symbol resolutions are dropped, not kept at low confidence | Swift member names are short and overloaded across unrelated types, so a bare-name match is usually unresolvable rather than uncertain: `sym:init` matches 96 definitions in Alamofire, and 85% of raw resolutions there are ambiguous. See `swift_kg.resolution` |

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
