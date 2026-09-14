# Release Notes — v0.2.0

> Released: 2026-09-14

SwiftKG's graph now resolves the symbols it references instead of leaving
edges pointing at nothing, and a build can be scoped to the source directories
that actually matter. Alongside those two changes, a mkdocs-material
documentation site ships, the CLI and MCP surfaces gain parity fixes with
PyCodeKG, and a run of extraction and analysis bugs found by adversarial
fixtures are fixed.

## What changed

**Symbol resolution is real.** Previously the extractor wrote edges pointing
at `sym:<name>` stub IDs but never emitted a node for them — on Alamofire,
1415 edges pointed at 392 IDs no row defined — and `SwiftKG` never ran a
resolution pass at all, so no `RESOLVES_TO` edge existed despite centrality,
CodeRank and `callers()` all depending on one. SwiftKG now emits a
deduplicated `symbol` node per stub and resolves it through the new
`swift_kg.resolution` module. Resolution is pruned harder than PyCodeKG's:
Swift member names are short and heavily overloaded, so a bare-name match
with more than one candidate (85% of raw resolutions on Alamofire) is dropped
rather than kept at low confidence, alongside stdlib member names and
self-links. Existing snapshots will read as `behind` after the next rebuild,
since `total_nodes` now counts the stub nodes too — that's expected, not a
regression; re-save the snapshot.

**Builds can be scoped to real source.** `--include-dir` / `--exclude-dir`
land on `build`, `update`, `build-sqlite` and `analyze`, matching `pycodekg`.
Without them, indexing `Tests/` and `Example/` alongside a library's actual
source skews every metric the analysis report computes — on Alamofire it
dragged doc-comment coverage from 56.5% down to a blended 31.5% and put two
test-support files in the top three of every structural ranking.

**A documentation site.** `mkdocs.yml`, an mkdocstrings-generated API
reference, and a `Docs` workflow publish to GitHub Pages on every push to
`main` that touches the source. SwiftKG is the first of the code-KG modules
to carry one.

**CLI/MCP parity and hardening.** `swiftkg analyze` gains `-j/--json` and
`-q/--quiet` to match `pycodekg analyze`, plus a `quality` block in its
compiled results. Every bound on the MCP surface — `list_nodes`, `find_node`,
`public_api`, `coderank`'s `radius`, and the Swift-specific tools that had
read the graph directly — now rejects an out-of-range argument with a message
naming the accepted range, instead of silently truncating.

**A run of extraction and analysis fixes.** A nested type with a repo-unique
name no longer absorbs every reference to that name repository-wide,
including references to a same-named standard-library type. An enum's raw
value type (`enum Sections: Int`) is no longer recorded as a protocol
conformance. `swiftkg analyze` now sees the snapshots it was given, a
library's public API is no longer flagged as dead code, and a handful of
smaller report and lookup bugs — double-printed output, unnormalized quoted
node IDs, stale TypeScriptKG wording — are corrected.

## Upgrading

Rebuild the graph (`swiftkg build`) to pick up symbol resolution — existing
indices carry no `symbol` nodes or `RESOLVES_TO` edges. If you track
snapshots, re-save one after the rebuild; the node-count jump from the new
stub nodes will otherwise read as drift. No other migration is needed.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
