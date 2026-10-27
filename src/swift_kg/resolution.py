"""
resolution.py — post-resolution hygiene for the Swift symbol graph.

``GraphStore.resolve_symbols`` matches ``sym:`` stubs to first-party
definitions by name.  Swift member names are short and routinely overloaded
across unrelated types: in Alamofire ``sym:init`` matches 96 definitions,
``sym:request`` 30 and ``sym:encode`` 19.  Since kgmodule-utils 0.29.1 the
store leaves a name that matches several definitions unresolved, which is
what Swift needs: a statically typed reference with no receiver type and
several candidates is unresolvable, not a weak signal.  Everything derived
from resolved edges -- ``callers()`` fan-in, CodeRank, the SIR ranker, which
all fan out through RESOLVES_TO -- would otherwise rank on guesses.

A unique name match can still be wrong, so two prunes run after resolution,
both from :func:`resolve_symbols_pruned`:

:func:`prune_stdlib_member_resolutions` covers the first: a stub
like ``sym:append`` is almost always ``Array.append``, not the repository's own
``MultipartFormData.append``, and no amount of name matching can tell them
apart.  The direct analogue of PyCodeKG's builtin-method prune.

:func:`prune_extension_self_resolutions` covers the second: ``extension Array``
emits an EXTENDS edge to ``sym:Array``, and the only node in the graph named
``Array`` is that same extension.  Resolving it links the extension to itself.

Author: Eric G. Suchanek, PhD

License: Elastic 2.0
"""

from __future__ import annotations

import sqlite3

#: Swift standard-library and Foundation member names that collide with
#: first-party declarations often enough that a bare-name match is a coin flip.
#: A repository's own ``append`` is real, but so is every ``Array.append`` call
#: in it, and the stub carries no receiver type to separate them.
SWIFT_STDLIB_MEMBER_NAMES = frozenset(
    {
        "advanced",
        "allSatisfy",
        "append",
        "callAsFunction",
        "compactMap",
        "contains",
        "count",
        "decode",
        "description",
        "distance",
        "drop",
        "dropFirst",
        "dropLast",
        "elementsEqual",
        "encode",
        "enumerated",
        "filter",
        "first",
        "firstIndex",
        "flatMap",
        "forEach",
        "hash",
        "index",
        "init",
        "insert",
        "joined",
        "last",
        "lastIndex",
        "map",
        "max",
        "min",
        "next",
        "prefix",
        "randomElement",
        "reduce",
        "remove",
        "removeAll",
        "removeFirst",
        "removeLast",
        "replaceSubrange",
        "reserveCapacity",
        "reversed",
        "shuffled",
        "sorted",
        "split",
        "starts",
        "suffix",
        "swapAt",
        "trimmingCharacters",
        "withUnsafeBytes",
    }
)


def prune_stdlib_member_resolutions(con: sqlite3.Connection) -> int:
    """Delete RESOLVES_TO edges for stubs named after a stdlib member.

    :param con: Open SQLite connection with an ``edges`` table.
    :return: Number of RESOLVES_TO edges deleted.
    """
    names = sorted(SWIFT_STDLIB_MEMBER_NAMES)
    placeholders = ", ".join("?" for _ in names)
    cur = con.execute(
        f"""
        DELETE FROM edges
        WHERE rel = 'RESOLVES_TO'
          AND src IN (SELECT id FROM nodes WHERE kind = 'symbol' AND name IN ({placeholders}))
        """,
        tuple(names),
    )
    con.commit()
    return cur.rowcount


def prune_extension_self_resolutions(con: sqlite3.Connection) -> int:
    """Delete RESOLVES_TO edges that link an extension back to its own stub.

    ``extension Array`` emits ``EXTENDS -> sym:Array`` and is itself the only
    node named ``Array``, so resolving the stub points the extension at itself.

    :param con: Open SQLite connection with an ``edges`` table.
    :return: Number of RESOLVES_TO edges deleted.
    """
    cur = con.execute(
        """
        DELETE FROM edges
        WHERE rel = 'RESOLVES_TO'
          AND EXISTS (
              SELECT 1 FROM edges AS ext
              WHERE ext.rel = 'EXTENDS'
                AND ext.src = edges.dst
                AND ext.dst = edges.src
          )
        """
    )
    con.commit()
    return cur.rowcount


def resolve_symbols_pruned(store) -> int:
    """Resolve symbol stubs, then drop the resolutions Swift cannot support.

    Called from :meth:`swift_kg.kg.SwiftKG._post_build_hook`, so resolution and
    hygiene cannot drift apart.

    :param store: :class:`~kg_utils.store.GraphStore` whose graph was just
        written.
    :return: Net number of RESOLVES_TO edges kept.
    """
    resolved = store.resolve_symbols()
    pruned = prune_stdlib_member_resolutions(store.con)
    pruned += prune_extension_self_resolutions(store.con)
    return max(0, resolved - pruned)
