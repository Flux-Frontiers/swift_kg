"""
validation.py — Boundary validation for SwiftKG's public entry points.

Per FLEET_STANDARDS (settled 2026-08-24), a KGModule subclass validates once
in its own ``query()`` / ``pack()`` / lookup overrides rather than separately
in the CLI and the MCP server. Both funnel through those methods, so one set
of checks covers both surfaces and there is nothing to drift.

This matters more than CLI ergonomics: the MCP server supports the SSE
transport beyond a trusted local environment, so these are real external
inputs. An unbounded ``hop`` drives an unbounded graph walk.

Bounds follow the reference implementation (genealogy_kg PR #3): they are a
starting point sized to cover real result sizes while capping the worst case,
not a specification.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

__all__ = [
    "MAX_QUERY_LEN",
    "bounded_int",
    "normalize_node_id",
    "require_query",
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


def bounded_int(name: str, value: int, minimum: int, maximum: int) -> int:
    """Return ``value`` if it lies within ``[minimum, maximum]``, else raise.

    :param name: Parameter name, used in the error message.
    :param value: Value to check.
    :param minimum: Smallest accepted value, inclusive.
    :param maximum: Largest accepted value, inclusive.
    :return: The validated value.
    :raises ValueError: If the value is out of range or not an integer.
    """
    try:
        ivalue = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc
    if ivalue < minimum or ivalue > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {ivalue}")
    return ivalue


def require_query(q: str) -> str:
    """Return a stripped, length-capped query string, or raise.

    :param q: Raw query text.
    :return: The stripped query.
    :raises ValueError: If the query is empty or longer than :data:`MAX_QUERY_LEN`.
    """
    if not isinstance(q, str):
        raise ValueError(f"query must be a string, got {type(q).__name__}")
    stripped = q.strip()
    if not stripped:
        raise ValueError("query must not be empty")
    if len(stripped) > MAX_QUERY_LEN:
        raise ValueError(f"query must be at most {MAX_QUERY_LEN} characters, got {len(stripped)}")
    return stripped


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
