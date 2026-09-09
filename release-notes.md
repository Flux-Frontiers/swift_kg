# SwiftKG 0.1.0

First release of SwiftKG — a hybrid semantic + structural knowledge graph for
Swift codebases, and the fourth language module in the KGRAG fleet.

## Highlights

**Swift's ambiguities, resolved rather than flattened.** Swift writes
superclass inheritance and protocol conformance with identical syntax
(`: Base, Proto`), so nothing local to a declaration says which is which.
SwiftKG runs two passes over the repository: the first builds a table of every
declared type and its kind, the second resolves each inheritance specifier
against it. A protocol target becomes `CONFORMS`; a class or actor target
becomes `INHERITS`. External targets fall back to the language's own rule —
only a class or actor has a superclass, written first.

**Repository-wide reference resolution.** Swift has no per-file imports within
a module: every file in a target sees every other file's declarations. That
makes the repository the correct resolution scope, so calls and type
references resolve across files, and `super.method()` resolves through the
enclosing type's superclass. Ambiguous names resolve to a `sym:` stub rather
than to an arbitrary candidate.

**Extensions as first-class nodes.** A Swift type's conformances and much of
its behaviour routinely live in an extension in another file. Each extension
gets a node and an `EXTENDS` edge, with members qualified under the type, so
"where is the rest of this type" has a graph answer.

**Access levels as data.** Swift states visibility with a keyword, so the
public API surface is read from the graph rather than grepped for an `export`
keyword. This feeds the analysis report, the `public_api` MCP tool, the
centrality penalty for private symbols, and `explain`'s reasoning about
declarations with no callers.

**No Swift toolchain required.** tree-sitter parses any checkout, on macOS or
Linux CI, with no Xcode and no buildable project.

## Surface

- `swiftkg` CLI: `init`, `build`, `update`, `build-sqlite`, `build-index`,
  `query`, `pack`, `analyze`, `explain`, `centrality`, `bridges`,
  `framework-nodes`, `snapshot`, `install-hooks`, `download-model`, `mcp`.
- MCP server with 21 tools, including `type_hierarchy` and `public_api`.
- Python API: `SwiftKG`, plus `conformers()`, `subclasses()` and
  `extensions_of()`.

## Not in this release

The visualizers (`viz`, `viz3d`, `viz-timeline`) are registered and report
that they are not yet available. They land together with the `viz` and `viz3d`
extras.

## Install

```bash
pip install swift-kg
swiftkg init --repo /path/to/swift-repo
```
