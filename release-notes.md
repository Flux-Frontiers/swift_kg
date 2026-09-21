# Release Notes -- v0.3.0

> Released: 2026-09-21

A dependency and packaging release. Nothing in extraction, resolution, query or
the MCP surface changes, and no index needs rebuilding. What moves is what
SwiftKG requires of its environment: it now floors `kgmodule-utils` at 0.23.0
and `mcp` at 1.3.0, and a typing workaround that 0.23.0 made unnecessary has
been deleted.

## What changed

**The `__enter__` override is gone.** It existed for one reason: `KGModule`
typed `__enter__` as returning the base class, so `with SwiftKG(...) as kg:`
lost the subclass surface under `ty` and every repo that hit this wrote the
same three-line override to narrow it back. kgmodule-utils 0.23.0 returns
`Self` instead, which makes all of those redundant at once. SwiftKG's copy is
deleted here and `ty` is clean without it. This is the fleet's standing rule
applied to itself: when several repos independently write the same override,
the override is the thing to delete, and the base class is where the fix
belongs.

**The `mcp` floor was wrong, and it matters more here than elsewhere.** It read
`>=1.0.0` and now reads `>=1.3.0,<2`. `mcp.server.fastmcp` does not exist at
all below 1.2.0, and its `FastMCP` accepts `instructions=` and `lifespan=` only
from 1.3.0. SwiftKG is one of the few fleet servers that passes both, so a
resolver landing below 1.3.0 would have broken `swiftkg-mcp` at construction
rather than merely ignoring an argument. Every lock already resolved far above
it, so this corrects a declaration that was untrue rather than an environment
that was broken. The `<2` cap stays: mcp 2.0 removed the bundled
`mcp.server.fastmcp` module entirely.

**The maintainer-only `kg` Poetry group is gone.** It held `doc-kg` and
`pycode-kg`, which this package runs but never imports. Under the fleet's
"tools are global" rule a tool is installed once with `uv tool` and is never a
dependency of the repo, and the test is the import. This does not affect anyone
installing `swift-kg` from PyPI, since the group was never part of the
published metadata.

## Upgrading

Nothing to do. No data migration, no rebuild, no configuration change. If you
install from PyPI, `pip install --upgrade swift-kg` picks up the new floors and
resolves the same versions your environment almost certainly already had.

Contributors working in a clone need one command, once, because the pre-commit
hook that `pycodekg install-hooks` wrote used to point into `.venv/bin` and the
tools no longer live there:

```bash
pycodekg install-hooks --force
```

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
