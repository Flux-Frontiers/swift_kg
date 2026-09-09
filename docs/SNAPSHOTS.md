# Snapshots

A snapshot records the graph's metrics at a point in time under
`.swiftkg/snapshots/`, with a `manifest.json` tracking them all.

```bash
swiftkg snapshot save 0.2.0 --repo REPO --subject repo:my-app
swiftkg snapshot list
swiftkg snapshot show latest
swiftkg snapshot diff 0.1.0 0.2.0
```

## Why snapshots and not per-node timestamps

Three kinds of time exist across the KGRAG fleet, and only one of them is what
the shared temporal contract describes:

| Kind | Example | Mechanism |
|---|---|---|
| Content-time — the content has an intrinsic date | a diary entry, a photograph | the temporal contract |
| **Artifact-time — the content has no date; the artifact has versions** | **SwiftKG, PyCodeKG, TypeScriptKG** | **snapshots** |
| Simulation-time — an integration axis, not a calendar | an ODE's `t=0..100` | neither |

Swift declarations carry no calendar time. The temporal question about a
codebase — how did this change — is answered at the graph level by
`snapshot save` / `show` / `diff`, not per node.

More decisively: **git is already the authoritative temporal store for code.**
Copying commit dates into node metadata would be a second authoring that goes
stale on the next commit, and deriving them on read would mean a `git blame`
per node to answer a question `git log` answers better.

## What SwiftKG records

Alongside the shared metrics (`total_nodes`, `total_edges`, node and edge
counts by kind, doc coverage), SwiftKG adds the numbers that say *what* moved
in a Swift codebase rather than only that something did:

| Metric | What it tells you |
|---|---|
| `swift_types` | Total classes, structs, enums, protocols and actors |
| `swift_classes` / `swift_structs` / `swift_enums` | Kind mix — is the codebase drifting toward value types |
| `swift_protocols` | Whether abstractions are being introduced |
| `swift_actors` | Whether concurrency is spreading |
| `swift_extensions` | Extension count |
| `swift_conformances` / `swift_inheritances` | Protocol-oriented vs. class-hierarchy design |
| `swift_extension_ratio` | Extensions per type — how much behaviour is declared away from the type it belongs to |

That last one is the interesting one over time. A ratio climbing without a
matching rise in type count usually means conformances and helpers are
accumulating in extensions scattered across files.

## Implementation

`swift_kg.snapshots.SnapshotManager` subclasses the shared
`kg_utils.snapshots.SnapshotManager` and carries exactly two things the base
cannot know: `package_name = "swift-kg"`, and a `_domain_metrics()` hook
returning the table above.

It does **not** override `capture()`, and does not subclass `Snapshot`. That is
the fleet standard, and the reason is specific: a `capture()` override has to
restate the base signature, and restating it is how an unnamed `key=` falls
into `**extra_metrics`, gets recorded as a dead metric, and never reaches the
base — so the snapshot keys on a git tree hash while the code looks correct.
That shipped in four packages. `tests/test_snapshots.py` asserts the overrides
stay absent.

## The git hook

```bash
swiftkg install-hooks --repo REPO
```

The hook runs the repository's quality checks on every commit. Snapshots are
opt-in per commit, because a snapshot on every commit is noise:

```bash
SWIFTKG_SNAPSHOT=1 git commit -m "…"       # rebuild and snapshot
SWIFTKG_SKIP_SNAPSHOT=1 git commit -m "…"  # force off (wins)
```

Snapshots key on a release tag, or a UTC timestamp when none is given — never
on a git tree hash, which is read before `git add` stages the snapshot and so
names a tree that is never committed.
