## Summary

<!-- What changes, and why. One or two sentences. -->

## Changes

<!-- The files or areas touched, and what each one does now that it did not. -->

## Graph impact

<!-- Does this change what the extractor emits — node kinds, edge relations,
     node IDs, metadata? A node-ID change invalidates every existing index and
     needs a rebuild, so say so. Write "none" if the graph is unaffected. -->

## Verification

<!-- What you ran, and what it said.

  env -u VIRTUAL_ENV -u POETRY_ACTIVE pre-commit run --all-files
  .venv/bin/pytest -m "not integration"
  .venv/bin/ty check src/ --python .venv
-->

- [ ] `pre-commit run --all-files` passes
- [ ] Tests pass, and new behaviour has a test
- [ ] MCP tool changes update the module docstring **and** the `FastMCP`
      instructions block in this same commit
- [ ] CHANGELOG updated under Unreleased
