"""
test_validation.py — boundary validation for SwiftKG's public entry points.

The MCP server supports the SSE transport beyond a trusted local environment,
so these are real external inputs rather than CLI ergonomics.
"""

from __future__ import annotations

import pytest

from swift_kg.validation import (
    MAX_QUERY_LEN,
    bounded_int,
    known_prefix,
    normalize_node_id,
    require_query,
)


class TestBoundedInt:
    def test_accepts_a_value_in_range(self) -> None:
        assert bounded_int("k", 8, 1, 100) == 8

    def test_accepts_the_bounds_themselves(self) -> None:
        assert bounded_int("hop", 0, 0, 5) == 0
        assert bounded_int("hop", 5, 0, 5) == 5

    @pytest.mark.parametrize("value", [0, -1, 101, 10_000])
    def test_rejects_out_of_range(self, value: int) -> None:
        with pytest.raises(ValueError, match="between 1 and 100"):
            bounded_int("k", value, 1, 100)

    def test_error_names_the_parameter(self) -> None:
        with pytest.raises(ValueError, match="hop"):
            bounded_int("hop", 99, 0, 5)

    def test_rejects_a_non_integer(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            bounded_int("k", "eight", 1, 100)  # type: ignore[arg-type]


class TestRequireQuery:
    def test_strips_surrounding_whitespace(self) -> None:
        assert require_query("  retry policy \n") == "retry policy"

    @pytest.mark.parametrize("value", ["", "   ", "\n\t"])
    def test_rejects_an_empty_query(self, value: str) -> None:
        with pytest.raises(ValueError, match="empty"):
            require_query(value)

    def test_accepts_a_query_at_the_limit(self) -> None:
        assert len(require_query("a" * MAX_QUERY_LEN)) == MAX_QUERY_LEN

    def test_rejects_an_over_long_query(self) -> None:
        with pytest.raises(ValueError, match="at most"):
            require_query("a" * (MAX_QUERY_LEN + 1))

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(ValueError, match="string"):
            require_query(None)  # type: ignore[arg-type]


class TestNormalizeNodeId:
    def test_passes_a_clean_id_through(self) -> None:
        node_id = "cls:Sources/Networking/Client.swift:HTTPClient"
        assert normalize_node_id(node_id) == node_id

    @pytest.mark.parametrize(
        "raw",
        [
            "`cls:Sources/A.swift:T`",
            "'cls:Sources/A.swift:T'",
            '"cls:Sources/A.swift:T"',
            "  cls:Sources/A.swift:T  ",
        ],
    )
    def test_strips_the_wrappers_callers_actually_paste(self, raw: str) -> None:
        """IDs arrive copied out of Markdown reports as often as from tool output."""
        assert normalize_node_id(raw) == "cls:Sources/A.swift:T"

    def test_rejects_an_empty_id(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            normalize_node_id("``")

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(ValueError, match="string"):
            normalize_node_id(42)  # type: ignore[arg-type]


class TestKnownPrefix:
    @pytest.mark.parametrize(
        "prefix",
        [
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
        ],
    )
    def test_recognises_every_prefix_the_extractor_emits(self, prefix: str) -> None:
        assert known_prefix(f"{prefix}:Sources/A.swift:X")

    def test_does_not_recognise_a_foreign_prefix(self) -> None:
        assert not known_prefix("widget:Sources/A.swift:X")
