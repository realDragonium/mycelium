"""Authoring policy for statement links."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

MIXED_LINK_ERROR = (
    "add_links only creates statement-to-statement links; entity endpoints are "
    "legacy and may only be read or removed. Use add_entity_links for "
    "entity-to-entity links."
)


def reject_entity_statement_additions(links: object) -> None:
    """Reject an add_links batch containing an entity endpoint."""
    if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
        return
    for link in links:
        if not isinstance(link, Mapping):
            continue
        from_id = link.get("from_id")
        to_id = link.get("to_id")
        if (
            isinstance(from_id, str)
            and from_id.startswith("ent_")
            or isinstance(to_id, str)
            and to_id.startswith("ent_")
        ):
            raise ValueError(MIXED_LINK_ERROR)
