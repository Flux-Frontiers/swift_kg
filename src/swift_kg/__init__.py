"""
swift_kg: Knowledge graph for Swift codebases.

Pure tree-sitter AST extraction → SQLite (authoritative) → sqlite-vec (semantic index).

Primary entry point::

    from swift_kg import SwiftKG

    kg = SwiftKG(repo_root="/path/to/swift-repo")
    stats = kg.build(wipe=True)
    result = kg.query("networking layer")
    pack = kg.pack("error handling")
    pack.save("context.md")

KGExtractor SDK::

    from swift_kg import SwiftCodeExtractor
"""

__version__ = "0.1.0"
__author__ = "Eric G. Suchanek, PhD"

from swift_kg.extractor import SwiftCodeExtractor

__all__ = [
    "SwiftCodeExtractor",
]

try:
    from swift_kg.kg import BuildStats, QueryResult, SnippetPack, SwiftKG
    from swift_kg.swiftkg_thorough_analysis import SwiftKGAnalyzer

    __all__ += [
        "SwiftKG",
        "SwiftKGAnalyzer",
        "BuildStats",
        "QueryResult",
        "SnippetPack",
    ]
except ImportError:
    pass  # kgmodule-utils[semantic] not installed; extractor still works standalone
