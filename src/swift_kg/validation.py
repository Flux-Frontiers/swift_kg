"""
validation.py — Boundary validation for SwiftKG's public entry points.

Per FLEET_STANDARDS (settled 2026-08-24), a KGModule validates once, in
``query()`` / ``pack()`` and the lookup methods, rather than separately in
the CLI and the MCP server. Both funnel through those methods, so one set
of checks covers both surfaces and there is nothing to drift.

This matters more than CLI ergonomics: the MCP server supports the SSE
transport beyond a trusted local environment, so these are real external
inputs. An unbounded ``hop`` drives an unbounded graph walk.

The generic checks, ``bounded_int`` and ``require_query``, come from
``kg_utils.validation``, and the base class applies them in ``query()`` and
``pack()``. This module keeps only what is SwiftKG's own: the query-length
cap it sets on the class, and node-ID handling.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

__all__ = [
    "MAX_QUERY_LEN",
    "normalize_node_id",
]

#: Longest accepted query string.
MAX_QUERY_LEN = 500

#: Node-ID prefixes SwiftKG emits, used to recognise an already-qualified ID.
_KNOWN_PREFIXES = frozenset(
    {
        "mod",
        "cls",
        "struct",
        "enum",
        "proto",
        "actor",
        "ext",
        "fn",
        "meth",
        "prop",
        "type",
        "sym",
    }
)


def normalize_node_id(raw: str) -> str:
    """Return a usable node ID from the several forms callers actually pass.

    A node ID reaches this code three ways: copied verbatim from a previous
    tool result, typed by hand with surrounding backticks or quotes from a
    Markdown report, or pasted with stray whitespace. All three are the same
    request and all three should work.

    :param raw: Node ID as supplied.
    :return: The normalized node ID.
    :raises ValueError: If nothing usable remains after normalization.
    """
    if not isinstance(raw, str):
        raise ValueError(f"node_id must be a string, got {type(raw).__name__}")
    node_id = raw.strip().strip("`").strip("'\"").strip()
    if not node_id:
        raise ValueError(
            "node_id must not be empty; expected a form like "
            "'cls:Sources/SampleKit/Storage.swift:Storage'"
        )
    if len(node_id) > MAX_QUERY_LEN:
        raise ValueError(f"node_id must be at most {MAX_QUERY_LEN} characters")
    return node_id


def known_prefix(node_id: str) -> bool:
    """Report whether ``node_id`` starts with a prefix SwiftKG emits.

    Advisory only — used to phrase a better "not found" message, never to
    reject an ID, since a graph built by an older version may carry others.

    :param node_id: A normalized node ID.
    :return: ``True`` if the prefix is one of SwiftKG's own.
    """
    return node_id.split(":", 1)[0] in _KNOWN_PREFIXES
