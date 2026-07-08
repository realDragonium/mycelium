"""Thin HTTP client for the Mycelium MCP surface.

Used in two ways:
1. Directly from the cleanup orchestrator (list behaviors to scan, write
   rewrites via replace_text, run the post-rewrite dedup search).
2. As the backend for tools the Ollama agent calls during its
   investigation phase — see `agent.py` for how each method is wrapped
   into an Ollama tool descriptor.

No auth, no retries — local-only and the failure mode (server down /
500) is the same: surface to the operator and let them decide.
"""

from __future__ import annotations

from typing import Any

import httpx


class MyceliumClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        resp = self.client.post(f"{self.base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Reads ----------------------------------------------------------

    def list_behaviors(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._post("/list-behaviors", {"limit": limit, "offset": offset})

    def list_all_behaviors(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        offset = 0
        page = 100
        while True:
            data = self.list_behaviors(limit=page, offset=offset)
            rows = data.get("behaviors", [])
            if not rows:
                return out
            out.extend(rows)
            if len(rows) < page:
                return out
            offset += page

    def get_behavior(self, id: str) -> dict[str, Any]:
        return self._post("/get-behavior", {"id": id})

    def get_entity(self, id: str) -> dict[str, Any]:
        return self._post("/get-entity", {"id": id})

    def search_behaviors(
        self, query: str, limit: int = 5, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        return self._post(
            "/search-behaviors",
            {"query": query, "limit": limit, "min_score": min_score},
        )

    def grep_behaviors(self, query: str, limit: int = 10) -> dict[str, Any]:
        return self._post("/grep-behaviors", {"query": query, "limit": limit})

    def list_link_types(self) -> list[str]:
        # No-arg tools are exposed as GET by the HTTP transport.
        resp = self.client.get(f"{self.base_url}/list-link-types")
        resp.raise_for_status()
        return resp.json()

    def list_entities(
        self, prefix: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        return self._post(
            "/list-entities",
            {"prefix": prefix, "limit": limit, "offset": offset},
        )

    def list_annotations(
        self,
        behavior_id: str | None = None,
        entity_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if behavior_id is not None:
            body["behavior_id"] = behavior_id
        if entity_id is not None:
            body["entity_id"] = entity_id
        if kind is not None:
            body["kind"] = kind
        return self._post("/list-annotations", body)

    def get_annotation(self, id: str) -> dict[str, Any]:
        return self._post("/get-annotation", {"id": id})

    def find_duplicates(
        self, threshold: float = 0.92, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self._post("/find-duplicates", {"threshold": threshold, "limit": limit})

    # --- Writes ---------------------------------------------------------

    def replace_text(
        self, id: str, text: str, allow_phrasing_violations: bool = False
    ) -> dict[str, Any]:
        return self._post(
            "/replace-text",
            {
                "id": id,
                "text": text,
                "allow_phrasing_violations": allow_phrasing_violations,
            },
        )

    def merge_behaviors(
        self, from_behavior_id: str, into_behavior_id: str
    ) -> dict[str, Any]:
        return self._post(
            "/merge-behaviors",
            {
                "from_behavior_id": from_behavior_id,
                "into_behavior_id": into_behavior_id,
            },
        )

    def upsert_behavior(
        self,
        text: str,
        mentions: list[str] | None = None,
        links: list[dict] | None = None,
        id: str | None = None,
        incoming_links: list[dict] | None = None,
        allow_phrasing_violations: bool = False,
        strict_mentions: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "mentions": mentions or [],
            "links": links or [],
            "incoming_links": incoming_links or [],
            "allow_phrasing_violations": allow_phrasing_violations,
            "strict_mentions": strict_mentions,
        }
        if id is not None:
            body["id"] = id
        return self._post("/upsert-behavior", body)

    def add_mentions(
        self, id: str, mentions: list[str], strict_mentions: bool = False
    ) -> dict[str, Any]:
        return self._post(
            "/add-mentions",
            {
                "id": id,
                "mentions": mentions,
                "strict_mentions": strict_mentions,
            },
        )

    def remove_mentions(self, id: str, mentions: list[str]) -> dict[str, Any]:
        return self._post("/remove-mentions", {"id": id, "mentions": mentions})

    def add_links(self, links: list[dict]) -> dict[str, Any]:
        return self._post("/add-links", {"links": links})

    def remove_links(self, links: list[dict]) -> dict[str, Any]:
        return self._post("/remove-links", {"links": links})

    def delete_behavior(self, id: str) -> dict[str, Any]:
        return self._post("/delete-behavior", {"id": id})

    def upsert_entity(self, name: str, description: str) -> dict[str, Any]:
        return self._post("/upsert-entity", {"name": name, "description": description})

    def upsert_annotation(
        self,
        kind: str,
        text: str,
        behavior_ids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        mentions: list[str] | None = None,
        id: str | None = None,
        strict_mentions: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "kind": kind,
            "text": text,
            "behavior_ids": behavior_ids or [],
            "entity_ids": entity_ids or [],
            "mentions": mentions or [],
            "strict_mentions": strict_mentions,
        }
        if id is not None:
            body["id"] = id
        return self._post("/upsert-annotation", body)

    def attach_annotation(
        self,
        annotation_id: str,
        behavior_id: str | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"annotation_id": annotation_id}
        if behavior_id is not None:
            body["behavior_id"] = behavior_id
        if entity_id is not None:
            body["entity_id"] = entity_id
        return self._post("/attach-annotation", body)
