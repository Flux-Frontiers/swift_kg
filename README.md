# SwiftKG

[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: Elastic-2.0](https://img.shields.io/badge/License-Elastic%202.0-blue.svg)](https://www.elastic.co/licensing/elastic-license)
[![PyPI](https://img.shields.io/pypi/v/swift-kg.svg)](https://pypi.org/project/swift-kg/)
[![Version](https://img.shields.io/badge/version-0.2.1-blue.svg)](https://github.com/Flux-Frontiers/swift_kg/releases)
[![CI](https://github.com/Flux-Frontiers/swift_kg/actions/workflows/ci.yml/badge.svg)](https://github.com/Flux-Frontiers/swift_kg/actions/workflows/ci.yml)
[![Docs](https://github.com/Flux-Frontiers/swift_kg/actions/workflows/docs.yml/badge.svg)](https://github.com/Flux-Frontiers/swift_kg/actions/workflows/docs.yml)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.22759432-blue.svg)](https://doi.org/10.5281/zenodo.22759432)

Knowledge graph for Swift codebases -- deterministic AST extraction, hybrid semantic + structural search.

## Overview

SwiftKG builds a queryable knowledge graph from Swift source using:

- **tree-sitter** for deterministic, parser-level AST extraction (no LLM inference during indexing)
- **SQLite** for the structural graph (nodes, edges, provenance)
- **sqlite-vec** for the semantic vector index (embeddings via `BAAI/bge-small-en-v1.5`)
- **Hybrid retrieval**: semantic seed → graph hop expansion → lexical re-ranking

It needs no Swift toolchain, no Xcode, and no buildable project. Point it at
any checkout, on macOS or on Linux CI, and it indexes.

## What Swift makes different

Three things about Swift are not cosmetic differences from the Python and
TypeScript modules in this fleet, and they shape the whole graph.

**Inheritance and conformance are written identically.** `: Base, Proto` gives
no syntactic signal about which is which:

```swift
final class DiskStorage: Storage<Data> {}   // superclass
struct Point: Equatable, Hashable {}        // two protocols
class Storage<T>: NSObject, Repository {}   // superclass, then protocol
```

SwiftKG runs two passes. The first builds a repository-wide table of every
declared type and its kind; the second resolves each specifier against it, so
a protocol target becomes `CONFORMS` and a class or actor target becomes
`INHERITS`. When the target is external — `NSObject`, `Codable`, anything from
a dependency — it falls back to the language's own rule: only a class or actor
may have a superclass, and it must be written first.

**There are no per-file imports within a module.** Every file in a target sees
every other file's declarations without an import statement. That makes the
repository the correct resolution scope rather than an approximation of one,
so calls and type references resolve across files. A name declared twice
resolves to nothing rather than to an arbitrary one of the two — an honest
`sym:` stub beats a confidently wrong edge.

**Extensions are a unit of authorship.** A type's conformances and much of its
behaviour routinely live in an extension in a different file. Each extension
gets its own node and an `EXTENDS` edge to the type, with members qualified
under the type (`Point.scaled`), so `swiftkg` can answer "where is the rest of
this type" without losing where the code actually is. Since it is idiomatic to
write one extension per conformance, an extension's own ID carries its
conformance list (`ext:…:Point+Codable`) rather than colliding on the type name.

Swift also states access level with a keyword, so `public` / `open` /
`internal` / `private` is recorded as a fact rather than guessed from a naming
convention. The public-API report, the centrality penalty for private symbols,
and `explain`'s reasoning about zero-caller declarations all read it directly.

## Node types

| Kind | Description |
|------|-------------|
| `module` | Every indexed `.swift` file |
| `class` | Class declaration |
| `struct` | Struct declaration |
| `enum` | Enum declaration |
| `protocol` | Protocol declaration |
| `actor` | Actor declaration |
| `extension` | Extension declaration |
| `function` | Free function at file scope |
| `method` | Function, initializer, deinitializer or subscript inside a type |
| `property` | Stored or computed property, enum case, or file-scope `let`/`var` |
| `typealias` | Type alias, and `associatedtype` inside a protocol |
| `symbol` | Unresolved import or call stub |

## Edge types

| Relation | Description |
|----------|-------------|
| `CONTAINS` | module → type/function, type → member |
| `IMPORTS` | module → `sym:<Module>` (a Swift import names a module, not a file) |
| `CALLS` | function/method → function, method, or type initializer |
| `INHERITS` | class or actor → superclass |
| `CONFORMS` | type or extension → protocol |
| `EXTENDS` | extension → the type it extends |

## Quick start

```bash
pip install swift-kg

# First-time setup (downloads model, builds graph, installs hooks, snapshots)
swiftkg init --repo /path/to/swift-repo

# Build the KG for a Swift repo
swiftkg build --repo /path/to/swift-repo

# Query
swiftkg query "networking layer"
swiftkg pack "request error handling" --hop 2

# Understand the repository
swiftkg analyze /path/to/swift-repo
swiftkg centrality --top 20
swiftkg explain "proto:Sources/Networking/Client.swift:HTTPClienting"
```

`build` wipes and rebuilds; `update` upserts without wiping. The split is
deliberate — a rebuild is correct after renames or deletions, where an upsert
leaves phantom nodes behind, so the safe operation is the bare verb and the
surprising one has to be asked for by name.

## MCP tools

`swiftkg mcp --repo /path/to/swift-repo` exposes 21 tools. Two exist only in
this module:

| Tool | Purpose |
|------|---------|
| `type_hierarchy(node_id)` | Conformers, subclasses, extensions and declared supertypes of one type, together — for a Swift type these are one question |
| `public_api(module_path, limit)` | The declared `public` / `open` surface, read from access levels |

The rest match the fleet: `graph_stats`, `query_codebase`, `pack_snippets`,
`callers`, `get_node`, `list_nodes`, `find_node`, `centrality`,
`bridge_centrality`, `framework_nodes`, `find_definition_at`, `analyze_repo`,
`explain`, `rank_nodes`, `query_ranked`, `explain_rank`, `snapshot_list`,
`snapshot_show`, `snapshot_diff`.

See [`docs/MCP.md`](docs/MCP.md) for client configuration.

## Snapshots & git hook

`swiftkg snapshot save` records graph metrics under `.swiftkg/snapshots/`, and
`swiftkg install-hooks` installs a pre-commit hook that keeps them current.
Alongside the shared metrics, SwiftKG records what actually characterises a
Swift codebase: counts by type kind, conformance and inheritance counts, and
extensions-per-type — how much behaviour is declared away from the type it
belongs to.

Snapshots, not per-node timestamps, are how a code KG answers temporal
questions. Git already owns when the code changed.

## Python API

```python
from swift_kg import SwiftKG

with SwiftKG(repo_root="/path/to/swift-repo") as kg:
    kg.build(wipe=True)

    result = kg.query("networking layer", k=8)
    pack = kg.pack("request error handling")
    pack.save("context.md")

    protocol_id = "proto:Sources/Networking/Client.swift:HTTPClienting"
    kg.conformers(protocol_id)      # every conforming type and extension
    kg.subclasses(class_id)         # direct subclasses
    kg.extensions_of(type_id)       # extensions, wherever they are declared
```

## Configuration

When the target repository has a `pyproject.toml`, SwiftKG reads
`[tool.swiftkg]`:

```toml
[tool.swiftkg]
include = ["Sources"]     # top-level dirs to index (unset = all)
exclude = ["Vendor"]      # extra dirs to skip at every depth
```

Most Swift repositories have no `pyproject.toml`, which is fine: with no
config, everything is indexed. `.build`, `.swiftpm`, `DerivedData`, `Pods`,
`Carthage`, `xcuserdata` and `*.xcodeproj` / `*.xcworkspace` bundles are always
skipped.

## Architecture

```
Swift source ─► tree-sitter ─► pass 1: symbol table
                            └► pass 2: NodeSpec / EdgeSpec
                                      │
                                      ├─► SQLite   (authoritative graph)
                                      └─► sqlite-vec (semantic index)
                                                │
                              hybrid query ◄────┘
                                    │
                        CLI · MCP server · Python API
```

Everything below the extractor — persistence, indexing, hybrid retrieval,
snippet packing, snapshots — comes from
[`kgmodule-utils`](https://pypi.org/project/kgmodule-utils/). This package
implements the Swift-specific layer and nothing else.

## Status

The visualizers (`swiftkg viz`, `viz3d`, `viz-timeline`) are registered and
report that they are not yet available; see the CHANGELOG's Unreleased
section. Everything else is complete.

## Author

Eric G. Suchanek, PhD — [Flux-Frontiers](https://github.com/Flux-Frontiers)

## Citation

If you use SwiftKG in your research or project, please cite it:

[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.22759432-blue.svg)](https://doi.org/10.5281/zenodo.22759432)

> Suchanek, E. G. (2026). *SwiftKG: Semantic Knowledge Graph for Swift Codebases* (Version 0.2.1) [Software]. Flux-Frontiers. https://doi.org/10.5281/zenodo.22759432

```bibtex
@software{suchanek_swift_kg,
  author    = {Suchanek, Eric G.},
  title     = {{SwiftKG}: Semantic Knowledge Graph for Swift Codebases},
  version   = {0.2.1},
  year      = {2026},
  publisher = {Flux-Frontiers},
  doi       = {10.5281/zenodo.22759432},
  url       = {https://github.com/Flux-Frontiers/swift_kg},
}
```

Full citation metadata in [`CITATION.cff`](CITATION.cff).

## License

[Elastic License 2.0](https://www.elastic.co/licensing/elastic-license). See
[`LICENSE`](LICENSE).
