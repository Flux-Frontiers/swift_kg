# SwiftKG make targets.
#
#   make docs        build the mkdocs site into ./site
#   make docs-serve  serve it locally with live reload on :8000
#
# Both need the docs group: poetry install --with docs
#
# There is deliberately nothing else here. Linting, type-checking and tests run
# through pre-commit and pytest, and duplicating them as make targets would give
# two entry points that drift.

.PHONY: help docs docs-serve

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

docs:  ## build the mkdocs site into ./site
	poetry run mkdocs build

docs-serve:  ## serve the mkdocs site locally with live reload
	poetry run mkdocs serve
