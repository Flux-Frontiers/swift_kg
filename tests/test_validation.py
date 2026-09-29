"""
test_validation.py — boundary validation for SwiftKG's public entry points.

The MCP server supports the SSE transport beyond a trusted local environment,
so these are real external inputs rather than CLI ergonomics.
"""

from __future__ import annotations

import pytest

from swift_kg.validation import known_prefix, normalize_node_id


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
