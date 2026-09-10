"""
cli/options.py — Shared Click option decorators for SwiftKG CLI commands.

Each symbol is a reusable decorator that can be stacked onto any Click command
to keep option names, defaults and help text identical across the CLI::

    @click.command()
    @include_option
    @exclude_option
    def my_command(include_dir, exclude_dir):
        ...

Mirrors ``pycode_kg.cli.options`` so the two CLIs take the same flags.

Author: Eric G. Suchanek, PhD

License: Elastic 2.0
"""

from __future__ import annotations

import click

include_option = click.option(
    "--include-dir",
    multiple=True,
    help="Top-level directory names to include in indexing. Can be used multiple times. "
    "When none are specified, all directories are indexed. "
    "Also reads [tool.swiftkg].include from pyproject.toml.",
)

exclude_option = click.option(
    "--exclude-dir",
    multiple=True,
    help="Directory names to exclude at every depth during indexing. Can be used multiple times. "
    "E.g. --exclude-dir Tests --exclude-dir Example. "
    "Also reads [tool.swiftkg].exclude from pyproject.toml.",
)
