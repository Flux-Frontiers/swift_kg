# Changelog

All notable changes to SwiftKG are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The Zenodo concept DOI, `10.5281/zenodo.22759432`,** in `CITATION.cff`,
  as a README badge, and in a README citation section with APA and BibTeX,
  matching `tscode_kg`. No archive existed to cite until v0.2.0 minted the
  first one on 2026-09-14. The concept DOI resolves to the newest archive, so
  it does not change at release time; `CITATION.cff` says so in a comment.

## [0.2.0] - 2026-09-14

### Added

- **`symbol` stub nodes, and the resolution pass that needs them.** The
  extractor emitted edges pointing at `sym:<name>` IDs but never emitted a node
  for them, so on Alamofire 1415 edges pointed at 392 IDs no row defined:
  `get_node` returned nothing for them, `explain` had nothing to explain, and
  every consumer had to special-case the hole. `SwiftCodeExtractor.extract` now
  emits one deduplicated `symbol` node per distinct stub, repo-wide rather than
  per file, recording in `metadata.referenced_by` which relations reached it.
  The scaffolding for these was already in place and unused: `node_kinds()`
  already declared `symbol` and `meaningful_node_kinds()` already excluded it
  from vector indexing and doc-comment coverage, so neither metric moves.
- **`swift_kg.resolution`, and a `_post_build_hook` on `SwiftKG` that runs it.**
  `SwiftKG` subclassed `kg_utils.pipeline.KGModule` directly and never
  overrode the hook, so no resolution ran and the graph carried no
  `RESOLVES_TO` edges at all -- while `centrality._load_effective_edges`
  rewrites `sym:` targets through exactly those edges, `coderank` weights
  `RESOLVES_TO` at 0.30, and `callers()` documents itself as resolving through
  stubs. All three were silently working on an edge type that was never
  written. PyCodeKG puts the same hook on an intermediate `module/base.py`
  class because it has several KG classes; SwiftKG has one, so the override
  lives directly on it.
- **A mkdocs-material documentation site**, matching `gutenberg_kg` and
  `quiltwright`: `mkdocs.yml`, `docs/index.md`, twelve `docs/api/*.md`
  mkdocstrings stubs, a `docs` Poetry group (`mkdocs-material`,
  `mkdocstrings[python]`), a `Makefile` with `docs` / `docs-serve`, and a
  `Docs` workflow that publishes to GitHub Pages on every push to `main` that
  touches `docs/`, `src/swift_kg/` or `mkdocs.yml`. The API reference is
  generated from the package's own docstrings, so it cannot drift from the
  code. mkdocstrings reads the source statically through `paths: [src]` rather
  than importing `swift_kg`, so the docs job installs no extras. The theme
  names no logo or favicon: this repo ships no brand assets, and naming files
  that do not exist would give the site two silent 404s. SwiftKG is the first
  of the three code-KG modules to carry a site; PyCodeKG and TypeScriptKG have
  none yet.
- **`--include-dir` / `--exclude-dir` on `build`, `update`, `build-sqlite` and
  `analyze`**, matching `pycodekg`. The `[tool.swiftkg]` config they union with
  was already read, but `_scaffold_swiftkg_config` only writes it into an
  existing `pyproject.toml` and a Swift repository rarely has one -- so on most
  real repositories scoping a build was unreachable. Indexing `Tests/` and
  `Example/` alongside `Source/` skews every metric the report computes: on
  Alamofire they were 1665 of 3528 nodes at 3.5% doc-comment coverage against
  `Source/`'s 56.5%, which blended to the 31.5% that drove an F grade, and put
  two test-support files in the top three of every structural ranking.
  `swiftkg build --include-dir Source` now reports 57.0% and a D.
- `swift_kg.cli.options`, holding the two shared option decorators, mirroring
  `pycode_kg.cli.options`.
- **A `main()` entry point and `__main__` guard** in the thorough-analysis
  module, matching `pycodekg_thorough_analysis.main` parameter for parameter.
  It is the single path behind `swiftkg analyze`, a standalone
  `python src/swift_kg/swiftkg_thorough_analysis.py`, and any programmatic
  caller, so all three behave identically. Unlike the PyCodeKG original it
  returns the compiled results rather than `None`; an empty dict means the
  graph was missing, which is how the CLI knows to exit non-zero. The module
  previously carried a `#!/usr/bin/env python3` shebang with no entry point to
  justify it.
- **`-j/--json` and `-q/--quiet` on `swiftkg analyze`**, completing the flag
  parity with `pycodekg analyze`. `_compile_results()` already produced a
  serialisable dict and was already tested as such; nothing consumed it.
- **A `quality` block in the compiled results** (`score`, `grade`, `label`),
  so a JSON consumer need not recompute the report's headline number. PyCodeKG
  also carries a per-component breakdown, which SwiftKG does not track.
- **Argument bounds across the MCP surface**, and an "Argument bounds" section
  in the `FastMCP` instructions so an agent learns the ranges without trial and
  error. `list_nodes` and `find_node` gained a bounded `limit` (defaults 500
  and 100): an unfiltered `list_nodes()` previously serialised every node in
  the repository, and `find_node("")` became `LIKE '%%'` over the whole graph.

### Changed

- **Ambiguous symbol resolutions are dropped rather than kept at low
  confidence**, diverging from PyCodeKG. `GraphStore.resolve_symbols` writes a
  `RESOLVES_TO` edge to *every* candidate when a bare name matches more than
  one definition, which Python tolerates and Swift does not: Swift member names
  are short and overloaded across unrelated types, so on Alamofire `sym:init`
  matches 96 definitions, `sym:request` 30 and `sym:encode` 19. Of the 867
  edges raw resolution produces there, 737 -- 85% -- are ambiguous, and every
  consumer of `RESOLVES_TO` fans out through all of them. Swift is statically
  typed, so a name matching several declarations with no receiver type is not a
  weak signal worth keeping; it is an unresolvable reference. Two narrower
  prunes run alongside it: `sym:append` and the rest of
  `SWIFT_STDLIB_MEMBER_NAMES` are library members rather than the repository's
  own (the analogue of PyCodeKG's builtin-method prune), and `extension Array`
  is the only node named `Array`, so resolving `sym:Array` would link that
  extension to itself. 103 resolutions survive on Alamofire, 20 on
  ml-stable-diffusion.
- **Existing snapshots will read as `behind` after the next rebuild.**
  `total_nodes` now counts stub nodes -- 584 more on Alamofire, 160 on
  ml-stable-diffusion -- which is well past the 50-node freshness tolerance in
  `_freshness`. The graph genuinely has more nodes; re-save the snapshot.
- **`analysis.py` is now `swiftkg_thorough_analysis.py`**, matching
  `pycode_kg`'s module name. This is a deliberate divergence from `tscode_kg`,
  which calls its equivalent `analysis.py` as SwiftKG did: the fleet-parity
  rule names both PyCodeKG and TypeScriptKG as references, and they disagree
  here. Chosen by the maintainer so the thorough-analysis module is findable
  under one name across the fleet. No public behaviour changes; `SwiftKGAnalyzer`
  is still re-exported from `swift_kg`, and no documentation referenced the old
  path.

- **`[tool.dockg]` now declares `exclude`, not `include`.** DocKG reads only
  `[tool.dockg].exclude`; it has no `include` key and no `--include-dir` flag,
  so an `include` list is silently ignored. The corpus is therefore defined by
  what is left out: `docs/`, `skills/` and the root Markdown files are indexed,
  while `src/` and `tests/` (PyCodeKG's) and the `.pycodekg/`, `.swiftkg/` and
  `.kgcache/` artifact directories are not. `.kgcache/` matters in particular --
  it holds the downloaded embedding model, whose HuggingFace model card is a
  Markdown file that would otherwise be indexed as project documentation. The
  dotdirs sibling repos also list are already in DocKG's own `SKIP_DIRS` and are
  not duplicated.

### Fixed

- **A call to a closure parameter emitted a stub for it.** `handlers.forEach {
  $0() }` recorded a CALLS edge to `sym:$0`, which names no declaration in the
  repository or out of it. Seven such edges on Alamofire.
- **A nested type no longer captures same-named references repository-wide.**
  The symbol table keyed every declared type by its bare name, so a nested
  type with a repo-unique bare name absorbed every reference to that name --
  including references to a standard-library type of the same name, which the
  table cannot contain. In Alamofire, the private `PathMonitor.Result` enum
  collected 141 `CALLS` edges and both `extension Result` blocks, which extend
  the *standard library's* `Result`, and the inflated node ranked 4th in global
  centrality while pushing one of its own enum cases to 6th. Types are now
  keyed by qualified name, and lookups resolve outward through the enclosing
  scopes as Swift does: a nested name still resolves from inside the type that
  declares it, and from outside becomes an honest `sym:` stub.
- **An enum's raw-value type is no longer recorded as a protocol
  conformance.** `enum Sections: Int` writes its raw type in exactly the
  position a superclass or first conformance occupies, so the resolver filed
  `Sections CONFORMS Int` -- naming `Int` as a protocol. A literal-backed
  standard-library type in first position on an enum is now read as a raw
  value and emits no edge; a conformance after it is unaffected, so
  `enum CodingKeys: String, CodingKey` keeps its `CodingKey` conformance.
  This removed 12 false `CONFORMS` edges from the Alamofire graph.
- **`swiftkg analyze` now sees the snapshots it was given.** The command never
  constructed a `SnapshotManager`, so phase 13 reported `skipped (no snapshot
  manager)` and the report rendered "No snapshots" even directly after
  `swiftkg init` captured one. The MCP `analyze_repo` tool was already wired
  correctly; only the CLI path was not.
- **The Public API Surface section no longer claims to read an `export`
  keyword.** Swift has none, and SwiftKG does not grep for one -- it reads the
  access level already stored on every node. The TypeScript vocabulary had
  followed the report template across; the phase's own docstring already
  described the Swift behaviour correctly.
- **`swiftkg analyze -o` announces the written report once**, not twice: both
  the analyzer and the CLI were printing it.
- **A library's public API is no longer reported as possible dead code.**
  `_is_swift_entry_point` has always excluded `public` and `open` declarations,
  whose callers are outside the repository by definition, but the orphan phase
  built its node dict without `metadata` and never selected the column -- so
  the visibility test read its `"internal"` default and the filter could not
  fire. On Alamofire this reported 332 orphans led by `responseData`,
  `responseDecodable` and `responseJSON`, the library's primary entry points;
  it now reports 83. Visibility inherited from a `public extension` is honoured
  too, since the extractor has already resolved it onto each member.
- **The "semantic index is missing" guidance reappears in a degraded report.**
  `_render_incomplete_analysis` decided whether to print it by matching
  `"vec_nodes"` or `"no such table"` against the phase's error text -- what a
  raw sqlite driver error happened to say. `kgmodule-utils` now raises a typed
  `VectorStoreNotFoundError` whose message is *"Vector store not found: ...
  Nothing has written it -- build the knowledge graph first"*, which contains
  neither substring, so the guidance had gone silent: `swiftkg analyze` after
  `swiftkg build-sqlite` reported that phase 4 failed without saying that
  `swiftkg build-index` is the fix. The check is now `_is_missing_index`,
  evaluated by exception type when the phase fails rather than by string at
  render time. The substring test is kept as a fallback for a store whose file
  exists but whose table does not -- a case the typed error, a
  `FileNotFoundError` subclass, does not cover. The `kgmodule-utils` floor rises
  to 0.21.0 with it, the release that introduced the typed error: against 0.20.x
  the guidance would go missing exactly as before, which is not something a
  caller could diagnose from the report.
- **`type_hierarchy` and `explain_rank` no longer silently return nothing for a
  quoted node ID.** Both reached `SwiftKG.node()`, which normalizes, but then
  passed the *raw* argument to `store.edges_from()` — so an ID copied out of a
  Markdown report with surrounding backticks resolved for the lookup and then
  matched no edges. They normalize once, up front.
- **`public_api` reports an out-of-range `limit` instead of silently
  truncating.** It clamped with `max(1, min(int(limit), 1000))`, so a caller
  asking for 5000 declarations received 1000 with nothing to indicate the
  result was cut. Every bound on the MCP surface now rejects with a message
  naming the accepted range, per FLEET_STANDARDS (settled 2026-08-24): a
  truncated result that looks complete is worse than an error. Validation runs
  before the graph is touched, and is reported as a tool result rather than
  raised as a protocol error.
- **Boundary validation reaches the tools that bypassed it.** `SwiftKG`'s
  `query`/`pack`/`node`/`callers` overrides were already validated, but the
  Swift-specific tools read the graph directly and so had no validated path —
  the same gap the standard was written for. `render_explain` and
  `compute_bridge_centrality` now validate internally, covering their CLI
  callers at the same time, and `coderank`'s query entries bound `radius`,
  which drives the induced-subgraph walk.
- **Remaining TypeScriptKG leftovers in user-facing text**: six
  `/path/to/ts-repo` examples in the `swiftkg` CLI module docstring and two in
  the analysis module, plus "Exported public API surface" in its feature list.
  Commit `069c01a` swept the CLI surface; a case-sensitive search missed
  `Exported`.

### Planned

- **Visualization surface.** `swiftkg viz` (Streamlit graph explorer),
  `swiftkg viz3d` (PyVista/PyQt5) and `swiftkg viz-timeline` (Plotly snapshot
  timeline) are registered and report that they are not yet available. The
  ports land together with the `viz` and `viz3d` extras — publishing extras
  that install Streamlit and PyVista for commands that only print a notice
  would put the gap somewhere nobody looks, in wheel metadata.
- **`swiftkg architecture`**, matching `pycodekg architecture`.
- Zenodo archive and concept DOI for `CITATION.cff`.

## [0.1.0] - 2026-09-09

First release. SwiftKG is the fleet's fourth language module, built on
`kgmodule-utils` and modelled on `tscode_kg`.

### Added

- **Swift AST extraction** (`SwiftCodeExtractor`) via tree-sitter, indexing
  files, classes, structs, enums, protocols, actors, extensions, functions,
  methods, properties and type aliases, with `CONTAINS`, `IMPORTS`, `CALLS`,
  `INHERITS`, `CONFORMS` and `EXTENDS` edges.
- **Two-pass repo-wide resolver.** Swift writes superclass inheritance and
  protocol conformance identically (`: Base, Proto`), so nothing local to a
  declaration distinguishes them. Pass 1 builds a symbol table of every
  declared type and its kind; pass 2 resolves each inheritance specifier
  against it, falling back to the language rule — only a class or actor has a
  superclass, and it is written first — when the target is external.
- **Cross-file reference resolution.** Swift has no per-file imports within a
  module, so a name declared anywhere in a target is visible everywhere in it.
  Calls and type references therefore resolve repository-wide, and
  `super.method()` resolves through the enclosing type's superclass.
  Ambiguous names resolve to nothing rather than to an arbitrary candidate:
  an honest `sym:` stub beats a confidently wrong edge.
- **Extensions as first-class nodes**, with an `EXTENDS` edge to the type and
  members qualified under it (`Point.scaled`). Swift routinely declares a
  type's behaviour in an extension in another file, and folding those members
  into the type would lose where the code actually lives.
- **Access levels recorded on every node.** Swift states visibility with a
  keyword, so `public` / `open` / `internal` / `private` is read rather than
  inferred from a naming convention. The two places Swift's default is not
  `internal` are honoured: `public extension` confers public access on members
  declaring none, and a protocol requirement takes its protocol's level. This
  feeds the centrality penalty, the public-API analysis phase, the
  `public_api` MCP tool, and `explain`'s zero-caller reasoning.
- **Well-known external protocols classified correctly.** `class ViewModel:
  ObservableObject` has no superclass, but `ObservableObject` is declared in
  Combine and invisible to the symbol table, so the positional fallback would
  invent one. A curated set of standard-library and Apple-framework protocol
  names resolves these to `CONFORMS`; anything absent still falls through to
  the heuristic, which is correct for real superclasses like `NSObject`.
- **Extension IDs carry their conformance list** (`ext:…:Point+Codable`).
  Idiomatic Swift writes one extension per conformance in the same file, and
  keying on the extended type alone collides — silently, since the store
  upserts by node ID and the second would overwrite the first.
- **`swiftkg` CLI**: `init`, `build`, `update`, `build-sqlite`, `build-index`,
  `query`, `pack`, `analyze`, `explain`, `centrality`, `bridges`,
  `framework-nodes`, `snapshot`, `install-hooks`, `download-model`, `mcp`.
- **MCP server** with 21 tools, including two that exist only here:
  `type_hierarchy` (conformers, subclasses, extensions and declared supertypes
  of one type, together, because for a Swift type they are one question) and
  `public_api` (the declared surface, read from access levels).
- **Analysis, ranking and snapshots**: 14-phase `analyze`, SIR centrality,
  CodeRank, bridge centrality, framework-node detection, and temporal
  snapshots recording Swift-shaped metrics (type counts by kind, conformance
  counts, and extensions-per-type).
- **Boundary validation** in the `SwiftKG` method overrides, so the CLI and
  the MCP server are both covered by one set of checks.
- 259 tests, ruff, ty, pre-commit, and CI including the wheel job that
  installs the built artifact into a clean venv and loads every console script.

### Notes

- **No temporal contract.** SwiftKG is artifact-time, not content-time: git
  already owns when the code changed, and snapshots answer the graph-level
  question. This is the documented correct choice for a code KG.
- **tree-sitter, not SourceKit-LSP.** SourceKit would give real type
  resolution and would require a Swift toolchain and a buildable project.
  Deterministic AST extraction that works on any checkout — and on Linux CI —
  is worth more than resolution that works only where the target compiles.

[Unreleased]: https://github.com/Flux-Frontiers/swift_kg/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Flux-Frontiers/swift_kg/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Flux-Frontiers/swift_kg/releases/tag/v0.1.0
