# Installation

## From PyPI

```bash
pip install swift-kg
```

That is the whole runtime. SwiftKG needs **no Swift toolchain, no Xcode, and no
buildable project** — `tree-sitter-swift` ships prebuilt wheels for macOS
(arm64 and x86_64), Linux (manylinux and musllinux) and Windows, so indexing
works on a developer's Mac and in Linux CI alike.

Python 3.12 or 3.13.

## First run

```bash
swiftkg init --repo /path/to/swift-repo
```

`init` downloads and caches the embedding model, builds the graph and vector
index, installs the pre-commit snapshot hook, and captures a baseline
snapshot. To do the pieces separately:

```bash
swiftkg download-model                       # cache the model for offline use
swiftkg build --repo /path/to/swift-repo     # graph + index
swiftkg install-hooks --repo /path/to/repo   # pre-commit hook only
```

The model is cached under `./.kgcache/models/`, overridable with the
`KGRAG_MODEL_DIR` environment variable. Once cached, builds and queries need
no network.

## Artefacts

Everything lands under `.swiftkg/` in the indexed repository:

```
.swiftkg/
├── graph.sqlite      structural graph — nodes, edges, provenance
├── vectors.sqlite    sqlite-vec semantic index
└── snapshots/        temporal metric snapshots + manifest.json
```

Add `.swiftkg/` to the target repository's `.gitignore`, or keep
`snapshots/` if you want the temporal record in version control.

## Development

```bash
git clone https://github.com/Flux-Frontiers/swift_kg
cd swift_kg
poetry install --with dev
pycodekg install-hooks --repo .
```

Install the hook with `pycodekg install-hooks`, not `pre-commit install`. Both
write `.git/hooks/pre-commit`, and the PyCodeKG hook already runs
`pre-commit run` -- so it gives you the same checks plus an opt-in index
rebuild, while `pre-commit install` would silently replace it and drop that
path. `pycodekg init --repo .` installs it too.

Extras are user-facing features; dev tooling is a Poetry group, so
`pip install swift-kg[dev]` is deliberately not a thing.

```bash
poetry install                    # core runtime only
poetry install --with dev         # + pytest, ruff, ty, pre-commit
poetry install --with kg          # + the pycodekg / dockg CLIs
```

The `kg` group is separate from `dev` on purpose: `pycode-kg` and `doc-kg`
pull `sentence-transformers` and `torch` transitively, and `dev` is what every
lint, type-check and test job installs. CI declines the `kg` group.

Run the checks the way CI does, with the environment cleaned — an inherited
`VIRTUAL_ENV` from another repo silently redirects the hooks:

```bash
env -u VIRTUAL_ENV -u POETRY_ACTIVE pre-commit run --all-files
.venv/bin/pytest -m "not integration"
.venv/bin/ty check src/ --python .venv
```

Tests marked `integration` load the real embedding model:

```bash
.venv/bin/pytest -m integration
```

## Troubleshooting

**`no such table: vec_nodes`** — the semantic index has not been built. This
happens after `swiftkg build-sqlite`, which builds the graph only. Run
`swiftkg build-index --repo <path>`, or `swiftkg build` for both. `swiftkg
analyze` degrades rather than failing here: it reports every phase that does
not need the index and names the missing step.

**`tree-sitter and tree-sitter-swift are required`** — the grammar failed to
import. Reinstall with `pip install --force-reinstall tree-sitter-swift`.

**No nodes extracted** — check what the walker is skipping. `.build`,
`.swiftpm`, `DerivedData`, `Pods`, `Carthage`, `xcuserdata`, dot-directories
and `*.xcodeproj` / `*.xcworkspace` bundles are always excluded. If the
repository has a `pyproject.toml` with a `[tool.swiftkg] include` list, only
those top-level directories are indexed.

**`swiftkg viz` says it is not available** — the visualizers are not in this
release. See the CHANGELOG's Unreleased section.
