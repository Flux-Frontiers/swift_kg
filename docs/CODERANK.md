# Ranking: SIR and CodeRank

Two ranking systems, both deterministic, both over the resolved structural
graph.

## SIR — Structural Importance Ranking

```bash
swiftkg centrality --db .swiftkg/graph.sqlite --top 25
swiftkg centrality --group-by module
```

A weighted PageRank where each relation contributes a distinct edge weight and
cross-file edges get an additional boost. `sym:` stubs are resolved through
`RESOLVES_TO` before ranking, so a cross-module reference counts for the node
it actually names.

| Relation | Weight |
|---|---|
| `CALLS` | 1.00 |
| `INHERITS` | 0.80 |
| `CONFORMS` | 0.80 |
| `EXTENDS` | 0.80 |
| `IMPORTS` | 0.45 |
| `CONTAINS` | 0.15 |

**`CONFORMS` carries the same weight as `INHERITS`** — in Swift the protocol,
not the superclass, is usually the load-bearing abstraction, and weighting
conformance below inheritance would systematically under-rank exactly the
declarations a protocol-oriented codebase is organised around.

**The private-symbol penalty reads the declared access level.** The Python and
TypeScript modules infer "private" from a leading underscore, because that is
all their languages give them. Swift says `private` and `fileprivate` out
loud, SwiftKG stores it, and the penalty applies to what the author actually
marked — not to a name that happens to start with `_`.

Module aggregation weights protocols at 1.3, other types at 1.2, members at
1.0, properties at 0.8: a file declaring the abstractions others conform to is
the one worth reading first.

## CodeRank

```bash
swiftkg analyze REPO      # phase 2
```

Global weighted PageRank via NetworkX, plus query-conditioned ranking. Exposed
through the `rank_nodes`, `query_ranked` and `explain_rank` MCP tools.

`query_ranked` combines semantic seeds with centrality and graph proximity
(`hybrid`), or runs personalized PageRank from the seeds (`ppr`). Results
carry `why` strings explaining each score.

Test paths are excluded by default, recognising SwiftPM's layout: `Tests/`
directories and the `…Tests.swift` filename convention, rather than
TypeScript's `.test.ts` infix.

## Bridge centrality

```bash
swiftkg bridges --top 25
```

How many unique files each file reaches and is reached by.

This carries a substantive Swift adaptation. In the Python and TypeScript
modules `IMPORTS` is the backbone of the metric, because an import there names
a *file* and so resolves to a node with a path. A Swift `import` names a whole
module and resolves to a `sym:` stub with no path, so it is dropped by the
join and contributes nothing. Leaving the relation set unchanged would have
produced a metric that runs and reports numbers while carrying about half the
signal it does elsewhere — with nothing to indicate the difference.

The relations that actually cross file boundaries in Swift are `CALLS`,
`INHERITS`, `CONFORMS` and `EXTENDS`. The last two especially: declaring a
conformance in an extension in another file is idiomatic rather than unusual,
and is exactly the coupling this metric exists to surface.

## Framework nodes

```bash
swiftkg framework-nodes --top 25
```

`0.6 × normalized SIR + 0.4 × normalized connectivity` — files that are both
architecturally central and highly connected.

Swift needs its boilerplate filter more than most languages: protocol
witnesses (`description`, `hashValue`, `encode`) and SwiftUI's `body` appear
on nearly every type, and an unfiltered ranking returns those instead of the
repository's actual hubs.
