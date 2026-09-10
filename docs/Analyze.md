# `swiftkg analyze`

```bash
swiftkg analyze REPO                          # print to stdout
swiftkg analyze REPO -o report.md             # write a file
swiftkg analyze REPO --write-centrality       # persist SIR scores to SQLite
swiftkg analyze REPO --include-dir Source     # scope the report's metadata
swiftkg analyze REPO -j results.json          # machine-readable results
swiftkg analyze REPO -o report.md --quiet     # no per-phase progress
```

`main()` in `swift_kg/swiftkg_thorough_analysis.py` is the single entry point
behind the CLI, the module's `__main__` guard and any programmatic caller, so
all three behave identically:

```bash
python src/swift_kg/swiftkg_thorough_analysis.py   # analyzes the cwd
```

The JSON written by `-j` carries the same results the report renders, including
the headline `quality` block (`score`, `grade`, `label`). Omit the flag and no
JSON is written. A missing graph is reported with the command that fixes it and
exits non-zero rather than producing a misleading partial report.

Scope the graph at build time, not here: `--include-dir` / `--exclude-dir`
describe what was indexed, so the report header states it accurately, but the
numbers come from whatever the graph holds. Indexing `Tests/` alongside
`Source/` drags doc-comment coverage down and puts test-support files at the
top of every ranking, so build with `swiftkg build --include-dir Source` first
and pass the same flags here.

Fourteen phases over the SQLite graph. Thirteen are pure SQL; only fan-out
seeds on a semantic query, so a graph built with `build-sqlite` still produces
a near-complete report — with an **Incomplete Analysis** section naming the
missing phase and the command that fixes it, rather than aborting.

## Phases

| # | Phase | What it answers |
|---|---|---|
| 1 | Baseline metrics | How large is the graph |
| 2 | CodeRank | Weighted global PageRank |
| 3 | Fan-in | What is most depended upon |
| 4 | Fan-out | What coordinates the most *(needs the vector index)* |
| 5 | Orphan detection | What is never referenced |
| 6 | Pattern detection | Which files are core |
| 7 | Module coupling | Which files are entangled |
| 8 | Critical call chains | The longest resolved call paths |
| 9 | Public API surface | What is declared `public` or `open` |
| 10 | Doc-comment coverage | How much of the graph carries text to embed |
| 11 | Type hierarchy & conformance | Inheritance depth, conformance breadth |
| 12 | Insights | Issues and strengths from phases 1–11 |
| 13 | Snapshot history | Movement since the last snapshot |
| 14 | Structural centrality (SIR) | Deterministic importance ranking |

## The two phases that are Swift's, not a port

**Phase 9, public API.** The Python and TypeScript modules grep the source for
an `export` keyword, because neither language records visibility anywhere the
graph can see. Swift states access level with a keyword and SwiftKG stores it,
so this phase is a SQL query over data already in the graph. That is more
accurate as well as tidier: a grep cannot tell `public` in code from "public"
in a comment, cannot see an access level written on the enclosing extension,
and cannot distinguish `public` from `open`.

**Phase 11, type hierarchy.** Depth is computed over `INHERITS` alone.
Conformance is not a depth relation — a type may conform to any number of
protocols without that saying anything about how deep its class hierarchy runs
— and folding conformances into the depth calculation would report a flat
struct-and-protocol codebase as deeply nested. Conformance breadth is reported
separately, which for protocol-oriented Swift is usually the more interesting
number.

## Reading phase 5 (orphans)

Swift has an unusually large population of declarations with zero internal
callers **by design**, because so much of the language's surface is reached
through protocol witnesses and framework dispatch rather than direct calls.
The phase excludes:

- anything `public` or `open` — its callers are outside the indexed module
- protocol witnesses and lifecycle members: `description`, `encode(to:)`,
  `hash(into:)`, `body`, `viewDidLoad`, `init`, `deinit`, …
- type declarations, which are referenced in type positions that never appear
  in the call graph
- test code, and files under `Views/`, `Scenes/`, `Screens/`
- `App.swift`, `AppDelegate.swift`, `SceneDelegate.swift`, `main.swift`

Without those exclusions the orphan list is mostly framework entry points, and
the genuinely dead code is buried in it.
