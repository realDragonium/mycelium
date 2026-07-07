"""Direction checks for statement links."""

from __future__ import annotations

KindSet = frozenset[str] | None

LINK_DIRECTION: dict[str, tuple[KindSet, KindSet]] = {
    "teaches": (frozenset({"procedure"}), frozenset({"capability"})),
    "performs": (frozenset({"action"}), frozenset({"event"})),
    "verifies": (frozenset({"check"}), frozenset({"state"})),
    "violates": (frozenset({"cause"}), frozenset({"state"})),
    "confirms": (frozenset({"check"}), frozenset({"cause"})),
    "refutes": (frozenset({"check"}), frozenset({"cause"})),
    "resolves": (frozenset({"action"}), frozenset({"cause"})),
    "obtained-by": (frozenset({"property"}), frozenset({"action", "procedure"})),
    "accepts": (None, frozenset({"property"})),
    "establishes": (None, frozenset({"state"})),
    "valued-by": (None, frozenset({"rule"})),
    "governed-by": (None, frozenset({"rule"})),
}


def _satisfies(kinds: tuple[KindSet, KindSet], from_kind: str, to_kind: str) -> bool:
    source_kinds, target_kinds = kinds
    return (
        (source_kinds is None or from_kind in source_kinds)
        and (target_kinds is None or to_kind in target_kinds)
    )


def _describe(kinds: KindSet) -> str:
    if kinds is None:
        return "any"
    return "/".join(sorted(kinds))


def flip_error(link_type: str, from_kind: str, to_kind: str) -> str | None:
    """Return an error only when a statement link is provably backwards."""
    kinds = LINK_DIRECTION.get(link_type)
    if kinds is None:
        return None
    if _satisfies(kinds, from_kind, to_kind):
        return None
    if not _satisfies(kinds, to_kind, from_kind):
        return None
    source_kinds, target_kinds = kinds
    expected = f"{_describe(source_kinds)} -> {_describe(target_kinds)}"
    actual = f"{from_kind} -> {to_kind}"
    return (
        f"link direction looks flipped: `{link_type}` goes {expected}, "
        f"but this edge goes {actual}; swap from_id and to_id"
    )
