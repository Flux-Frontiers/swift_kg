# Release Notes -- v0.4.0

> Released: 2026-09-29

A validation release. SwiftKG no longer carries its own copies of the input
validators and uses the ones in `kgmodule-utils` instead. Extraction,
resolution, the graph schema and the MCP tool surface are unchanged and no
index needs rebuilding. One behavior changes at the edges: integer arguments
are now checked more strictly, so a bool or a fractional float is rejected
where it used to be silently coerced.

## What changed

**The local validators are gone.** `bounded_int` and `require_query` lived in
`swift_kg.validation` as copies of the SDK's helpers. They are deleted, and the
callers import them from `kg_utils.validation`. The module keeps only what is
specific to Swift: `MAX_QUERY_LEN`, `normalize_node_id` and `known_prefix`.

**The `query()` override is deleted.** It existed only to validate its
arguments. The base class now bounds `q`, `k`, `hop` and `max_nodes` in both
`query()` and `pack()`, and SwiftKG sets its 500-character query cap through
the `max_query_len` class attribute. `pack()` keeps an override for one reason:
it bounds `max_lines`, which the SDK does not check.

**Stricter integer checks.** The SDK's `bounded_int` rejects a bool and a
non-integral float. The old local copy accepted both, so `k=True` was treated
as 1 and `k=3.7` as 3. Both now raise `ValueError`. This is the reason for the
minor version bump.

**`kgmodule-utils` floor raised to `>=0.26.0`,** the latest release. The lock
moves from 0.23.0 to 0.26.0 and changes only fleet packages.

## Upgrading

If you call the Python API or MCP tools with well-formed integers, nothing
changes. If any caller passes a bool or a float with a fractional part for
`k`, `hop`, `max_nodes` or `max_lines`, change it to an int; it will now raise
`ValueError`. No data migration, rebuild or configuration change is needed.
`pip install --upgrade swift-kg` is enough.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
