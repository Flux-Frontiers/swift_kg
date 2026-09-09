# SwiftKG cheat sheet

## Build

```bash
swiftkg init --repo REPO          # model + graph + index + hook + snapshot
swiftkg build --repo REPO         # full rebuild (wipes) — correct after renames
swiftkg update --repo REPO        # incremental upsert — leaves phantom nodes
                                  #   behind for deleted or renamed symbols
swiftkg build-sqlite --repo REPO  # graph only
swiftkg build-index --repo REPO   # index only (graph must exist)
```

## Search

```bash
swiftkg query "networking layer"
swiftkg query "retry policy" -k 12 --hop 2 --rerank hybrid
swiftkg pack "request error handling" --hop 2 --out context.md
```

`--rerank` is `hybrid` (default), `semantic` or `legacy`.
Bounds: `-k` 1–100, `--hop` 0–5, `--max-nodes` 1–500, query ≤ 500 chars.

## Understand

```bash
swiftkg analyze REPO                       # 14-phase Markdown report
swiftkg analyze REPO -o report.md --write-centrality
swiftkg explain NODE_ID --repo REPO
swiftkg centrality --db .swiftkg/graph.sqlite --top 25
swiftkg centrality --group-by module
swiftkg bridges --top 25                   # file-to-file coupling
swiftkg framework-nodes --top 25           # repo-defining hub files
```

## Snapshots

```bash
swiftkg snapshot save 0.2.0 --repo REPO --subject repo:my-app
swiftkg snapshot list
swiftkg snapshot show latest
swiftkg snapshot diff 0.1.0 0.2.0
swiftkg install-hooks --repo REPO
```

The hook is opt-in per commit: `SWIFTKG_SNAPSHOT=1 git commit …`, and
`SWIFTKG_SKIP_SNAPSHOT=1` forces it off.

## MCP

```bash
swiftkg mcp --repo REPO                    # stdio (default)
swiftkg mcp --repo REPO --transport sse
```

## Node IDs

```
<prefix>:<path>:<qualname>

mod:Sources/Net/Client.swift                    file
cls:Sources/Net/Client.swift:HTTPClient         class
struct:Sources/Model/Point.swift:Point          struct
proto:Sources/Net/Client.swift:HTTPClienting    protocol
actor:Sources/Net/Pool.swift:ConnectionPool     actor
enum:Sources/Net/Client.swift:HTTPError         enum
ext:Sources/Model/Point.swift:Point             extension
fn:Sources/Util/Math.swift:magnitude            free function
meth:Sources/Net/Client.swift:HTTPClient.send   method
prop:Sources/Model/Point.swift:Point.x          property or enum case
type:Sources/Net/Client.swift:Handler           typealias
sym:Foundation                                  unresolved import or call
```

Nested types qualify through: `cls:…:Outer.Inner`, `meth:…:Outer.Inner.run`.
Extension members qualify under the extended type: `meth:…:Point.scaled`.

## Relations

| Relation | Meaning | Inverted with |
|---|---|---|
| `CONTAINS` | file → type, type → member | `callers(id, rel="CONTAINS")` |
| `IMPORTS` | file → `sym:<Module>` | `callers(id, rel="IMPORTS")` |
| `CALLS` | caller → callee or type initializer | `callers(id)` |
| `INHERITS` | class/actor → superclass | subclasses of |
| `CONFORMS` | type/extension → protocol | conformers of |
| `EXTENDS` | extension → extended type | extensions of |

There is no `IMPLEMENTS` — Swift conformance covers it, and asking for it
raises rather than returning nothing.

## Python

```python
from swift_kg import SwiftKG

with SwiftKG(repo_root="REPO") as kg:
    kg.build(wipe=True)
    kg.query("networking layer", k=8)
    kg.pack("error handling").save("context.md")

    kg.conformers(protocol_id)   # who implements this protocol
    kg.subclasses(class_id)      # direct subclasses
    kg.extensions_of(type_id)    # extensions, wherever declared
    kg.callers(node_id, rel="CALLS")
```

## Config

```toml
[tool.swiftkg]
include = ["Sources"]   # top-level dirs to index (unset = all)
exclude = ["Vendor"]    # extra dirs to skip at every depth
```

Always skipped: `.build`, `.swiftpm`, `DerivedData`, `Pods`, `Carthage`,
`Checkouts`, `xcuserdata`, dot-directories, and `*.xcodeproj` /
`*.xcworkspace` / `*.xcassets` / `*.framework` bundles.
