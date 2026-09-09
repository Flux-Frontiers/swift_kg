# Changelog

All notable changes to SwiftKG are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Flux-Frontiers/swift_kg/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Flux-Frontiers/swift_kg/releases/tag/v0.1.0
