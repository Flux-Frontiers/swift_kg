# Release Notes -- v0.5.1

> Released: 2026-11-02

SwiftKG 0.5.1 follows the symbol-resolution fix in kgmodule-utils 0.29.1.
The shared store no longer links a stub to every definition that shares its
bare name, so SwiftKG's own pass for deleting those links had nothing left
to delete and is gone. The release also refreshes the lock past the
advisories open across the fleet.

## What changed

**One less post-build pass.** `prune_ambiguous_resolutions()` deleted the
`name_fallback_ambiguous` edges the store used to write, one per candidate,
when a bare name matched several definitions. Since kgmodule-utils 0.29.1
the store leaves such a name unresolved and writes no edge at all, so the
prune always deleted nothing. The stdlib-member and extension-self prunes
still run.

**kgmodule-utils 0.29.1 is the floor.** Against an older SDK the ambiguous
edges would come back with nothing to remove them, so the floor follows the
fix.

**The lock is refreshed.** certifi, filelock, setuptools and virtualenv move
to patched releases.

## Upgrading

`pip install -U swift-kg`. Rebuild an existing graph to drop any ambiguous
edges an older build wrote. No command or tool changes.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
