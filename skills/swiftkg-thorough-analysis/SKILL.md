---
name: swiftkg-thorough-analysis
description: Comprehensive architectural analysis of a Swift repository using SwiftKG's 14-phase analyzer — fan-in/fan-out hotspots, CodeRank (global PageRank), SIR structural centrality, module coupling, doc-comment coverage, type hierarchy and conformance, orphan detection, critical call chains, public API surface, snapshot history, and an overall quality grade. Use this skill when the user asks to: "analyze this repository thoroughly", "give me a complete swiftkg analysis", "swiftkg deep dive", "repository architecture report", "find hotspots in this codebase", "run swiftkg analyze", "what's the quality grade of this repo", or wants a structured Markdown report on the health of a Swift codebase.
---

# SwiftKG Thorough Repository Analysis Skill

## Overview

Performs comprehensive architectural analysis of any Swift repository using SwiftKG's graph traversal capabilities. Extracts metrics like:
- **Complexity hotspots** (highest fan-in/fan-out functions, CodeRank-seeded)
- **Structural importance** (CodeRank global PageRank + SIR centrality)
- **Architectural patterns** (core modules, hub/orchestrator modules, module coupling)
- **Code quality signals** (orphaned declarations, doc-comment coverage, type hierarchy and conformance depth)
- **Overall quality grade** (A–F with score and label)

## Trigger Phrases

- "analyze this repository thoroughly"
- "give me a complete swiftkg analysis"
- "swiftkg deep dive"
- "repository architecture report"
- "find hotspots in this codebase"

## The 14 Phases

`swiftkg analyze` runs all phases automatically, in order:

| Phase | Name | What it computes |
|---|---|---|
| 1 | Baseline metrics | Node/edge counts by kind and relation |
| 2 | CodeRank (global PageRank) | Weighted PageRank over CALLS + IMPORTS + INHERITS; seeds later phases |
| 3 | Fan-in analysis | Most-called functions/methods (CodeRank-seeded; SQL fallback) |
| 4 | Fan-out analysis | Functions that call the most others — orchestrators, god functions |
| 5 | Orphan detection | Declarations with zero callers (entry-point aware for TS) |
| 6 | Pattern detection | Core modules and architectural coupling patterns |
| 7 | Module coupling | IMPORTS + cross-module CALLS; cohesion scores per module |
| 8 | Critical call chains | Deepest high-traffic call paths |
| 9 | Public API surface | Exported, high fan-in declarations |
| 10 | doc-comment coverage | Documentation coverage across all node kinds — drives semantic retrieval quality |
| 11 | Type hierarchy and conformance | INHERITS / CONFORMS / EXTENDS depth and breadth |
| 12 | Generate insights | Issues, warnings, strengths compiled from all prior phases |
| 13 | Snapshot history | Trend context from `.swiftkg/snapshots/` |
| 14 | Structural centrality (SIR) | SIR PageRank ranking; optional persistence via `--write-centrality` |

The report ends with an **overall quality grade**: a numeric score mapped to `A Excellent / B Good / C Fair / D Needs Work / F Critical`.

## Implementation Steps

### 1. Run the analyzer — it does the heavy lifting

```bash
# All 14 phases; Markdown report to stdout
swiftkg analyze /path/to/repo

# Write the report to a file
swiftkg analyze /path/to/repo -o analysis.md

# Also persist SIR centrality scores to the SQLite graph
# (centrality_scores table — powers later centrality queries)
swiftkg analyze /path/to/repo -o analysis.md --write-centrality

# Non-default artifact paths
swiftkg analyze /path/to/repo --db /path/to/graph.sqlite --vectors /path/to/vectors.sqlite
```

Prerequisite: the graph must exist (`swiftkg build --repo /path/to/repo`). If results look stale, re-run `build` — it always wipes first.

Alternatively, from an MCP session simply call `analyze_repo()` — same analysis, returned as Markdown.

### 2. Interpret the report

| Signal | How to read it |
|---|---|
| **High fan-in** | Core functionality and integration points — changes here ripple everywhere; prioritize test coverage |
| **High fan-out** | Orchestrators / coordination hubs; extreme values suggest god functions worth splitting |
| **CodeRank top nodes** | The structurally most important declarations repo-wide — review these first before refactoring |
| **SIR centrality** | Independent structural-importance ranking; agreement with CodeRank strengthens the signal |
| **Orphans** | Dead-code candidates — but Swift's framework-driven entry points are excluded — `public`/`open` declarations, protocol witnesses, SwiftUI `body`, UIKit lifecycle methods and test code. Not every zero-caller node is dead, and in Swift most of them are not |
| **Module coupling** | High cross-module CALLS + IMPORTS with low cohesion = tight coupling; candidates for boundary cleanup |
| **doc-comment coverage** | Directly determines semantic retrieval quality: good coverage → strong `query_codebase`/`pack_snippets` results; low coverage → degraded semantic queries |
| **Hierarchy depth** | Deep INHERITS/EXTENDS chains signal fragile base-class problems |
| **Quality grade** | A/B = healthy; C = act on top warnings; D/F = structural work needed before feature work |

### 3. Compile findings into an actionable summary

```markdown
# SwiftKG Repository Analysis Report

## Quick Stats
- Total nodes/edges, modules analyzed, quality grade

## Complexity Hotspots
### Most Called (Fan-In)
| Declaration | Callers | Module | Risk |
### Most Calling (Fan-Out)
| Declaration | Calls | Module | Role |

## Structural Importance
- CodeRank top nodes, SIR top modules, hub/bridge modules

## Architectural Patterns
- Core modules and why they're core
- Coupling hot pairs, cohesion outliers

## Code Quality Signals
- Orphaned declarations (dead-code candidates)
- doc-comment coverage by kind, and its impact on semantic search
- Deep class hierarchies, or protocols with very wide conformance

## Opportunities
- Refactoring candidates (split high fan-out, decouple hot pairs)
- Documentation targets (highest-CodeRank undocumented nodes first)

## Recommendations
1. ...
```

## Output Format

**Terminal:** Rich progress per phase (`▶ Phase N/14: ...` with per-phase results), then the report.

**File:** Markdown report via `-o` / `--report`; stdout when omitted.

## Example Invocations

```bash
swiftkg analyze .                                   # current directory
swiftkg analyze /path/to/repo -o /tmp/analysis.md   # custom report path
swiftkg analyze . --write-centrality                # persist SIR scores
swiftkg-analyze /path/to/repo                       # script-alias form
```

## Follow-Up Deep Dives (MCP)

After reading the report, drill into specifics with the MCP tools:

```
centrality(top=20)                         → confirm SIR hotspots
callers("meth:Sources/Store/Storage.swift:Storage.fetch")    → who depends on a hotspot
explain("cls:Sources/Networking/Client.swift:HTTPClient")  → orient before refactoring
snapshot_diff("abc1234", "def5678")        → did the last refactor improve metrics?
rank_nodes(top=25) / explain_rank(...)     → CodeRank detail
```

## Edge Cases

- **Large repos** → phases degrade gracefully; missing optional data (e.g. no snapshots) is skipped with a warning, not a failure
- **No CodeRank available** → fan-in falls back to a direct SQL scan
- **Mixed Swift codebases** → both are indexed; use `[tool.swiftkg]` include/exclude to scope
- **Tests polluting metrics** → `exclude = ["tests"]` in `[tool.swiftkg]`, rebuild, re-run
