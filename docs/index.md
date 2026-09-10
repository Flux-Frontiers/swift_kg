# SwiftKG

**A knowledge graph for Swift codebases -- deterministic AST extraction,
hybrid semantic + structural search, served over MCP.**

*Eric G. Suchanek, PhD -- Flux-Frontiers*

SwiftKG indexes Swift source with `tree-sitter`, stores the structural graph
in SQLite and the semantic index in sqlite-vec, and exposes both to an agent
over the Model Context Protocol. It needs no Swift toolchain, no Xcode and no
buildable project: point it at any checkout, on macOS or on Linux CI.

```bash
swiftkg init  --repo /path/to/swift-repo
swiftkg build --repo /path/to/swift-repo
swiftkg query "networking layer"
```

## Where to start

| | |
|---|---|
| [Installation](INSTALLATION.md) | Install, index a repository, wire up the MCP server |
| [Cheatsheet](CHEATSHEET.md) | Every `swiftkg` command, quick reference |
| [MCP server](MCP.md) | The tool surface an agent sees, and how to configure it |

## Understanding a repository

| | |
|---|---|
| [Repository analysis](Analyze.md) | What `swiftkg analyze` reports and how to read it |
| [Ranking](CODERANK.md) | SIR and CodeRank, the two structural ranking systems |
| [Snapshots](SNAPSHOTS.md) | Recording graph metrics over time and diffing them |

## Swift specifics

Swift's grammar drives several deliberate divergences from the Python and
TypeScript modules in this fleet: `CONFORMS` separate from `INHERITS`,
repository-wide two-pass extraction, `extension` as its own node kind, and
visibility stored on every node.

| | |
|---|---|
| [What the extractor sees](SWIFT_GRAMMAR.md) | The `tree-sitter-swift` properties the extractor is built on |

The [API reference](api/kg.md) is generated from the package's own docstrings.

## Source

SwiftKG is Elastic-2.0 and lives at
[github.com/Flux-Frontiers/swift_kg](https://github.com/Flux-Frontiers/swift_kg).
