"""Plan recorder: intercept agent writes, hand back synthetic responses.

The agent has the full MCP write surface but does not write directly.
Each write call is recorded as an `Action` in the per-suspect plan and
returns a synthesized success response. Creates (`upsert_behavior` with
no id, `upsert_entity`, `upsert_annotation`) get a synthetic id like
`pending_beh_3` that the agent can reference in subsequent calls
(linking to a freshly-proposed behavior, annotating a freshly-proposed
entity, etc.).

When the operator approves the plan, `flush()` replays each action
against the real MCP in order, building up a synthetic→real id map as
creates resolve, and walking each subsequent action's args to substitute
pending ids before the call.

Reads pass through to the underlying client. If a read targets a
pending id, we synthesize the response from the recorded create args
(text, mentions, etc. — but no graph neighbors, since none exist yet
on the real side).
"""

from __future__ import annotations

from typing import Any

from mcp_client import MyceliumClient


class PlanRecorder:
    def __init__(self, mcp: MyceliumClient):
        self.mcp = mcp
        self.actions: list[dict[str, Any]] = []
        self._counters: dict[str, int] = {"beh": 0, "ent": 0, "ann": 0}
        self.dedup_skipped: int = 0  # Count of suppressed duplicate writes,
        # surfaced as a warning to the operator if non-zero. Indicates the
        # agent emitted the same write twice — usually a sign the agent is
        # confused about its own state, not a legitimate intent.

    def _next(self, kind: str) -> str:
        self._counters[kind] += 1
        return f"pending_{kind}_{self._counters[kind]}"

    @staticmethod
    def _args_key(args: dict[str, Any]) -> str:
        # Stable serialization for byte-equivalent comparison. dicts are
        # sorted; lists preserve order (since order matters for e.g. links).
        import json as _json
        return _json.dumps(args, sort_keys=True, default=str)

    def _record(
        self, name: str, args: dict[str, Any], synthetic: str | None = None
    ) -> None:
        # Deduplicate exact-duplicate writes. Creates (those with a
        # `synthetic` id) are NEVER deduped because two consecutive
        # `upsert_behavior(text="…")` calls are legitimately distinct
        # creates with distinct pending ids. Idempotent ops (like a second
        # `delete_behavior(id=X)`) collapse to one queued action.
        if synthetic is None:
            key = (name, self._args_key(args))
            for prev in self.actions:
                if (
                    prev["synthetic"] is None
                    and prev["name"] == name
                    and self._args_key(prev["args"]) == key[1]
                ):
                    self.dedup_skipped += 1
                    return
        self.actions.append({"name": name, "args": args, "synthetic": synthetic})

    def _find_create(self, pending_id: str) -> dict[str, Any] | None:
        for a in self.actions:
            if a["synthetic"] == pending_id:
                return a
        return None

    # --- Reads --------------------------------------------------------

    def list_behaviors(self, **kw):
        return self.mcp.list_behaviors(**kw)

    def list_all_behaviors(self):
        return self.mcp.list_all_behaviors()

    def get_behavior(self, id: str):
        if id.startswith("pending_beh_"):
            a = self._find_create(id)
            if a is None:
                return {"error": f"unknown pending id {id}"}
            return {
                "id": id,
                "text": a["args"].get("text", ""),
                "mentions": [
                    {"name_id": "pending", "name": m, "entity_id": "pending"}
                    for m in a["args"].get("mentions", []) or []
                ],
                "links": a["args"].get("links", []) or [],
                "incoming_links": [],
                "annotations": [],
            }
        return self.mcp.get_behavior(id)

    def get_entity(self, id: str):
        if id.startswith("pending_ent_"):
            a = self._find_create(id)
            if a is None:
                return {"error": f"unknown pending id {id}"}
            return {
                "id": id,
                "description": a["args"].get("description", ""),
                "names": [
                    {"id": "pending", "text": a["args"].get("name", "")}
                ],
                "links": [],
                "incoming_links": [],
                "annotations": [],
                "mentioning_annotations": [],
            }
        return self.mcp.get_entity(id)

    def search_behaviors(self, **kw):
        return self.mcp.search_behaviors(**kw)

    def grep_behaviors(self, **kw):
        return self.mcp.grep_behaviors(**kw)

    def list_link_types(self):
        return self.mcp.list_link_types()

    def list_entities(self, **kw):
        return self.mcp.list_entities(**kw)

    def list_annotations(self, **kw):
        return self.mcp.list_annotations(**kw)

    def get_annotation(self, id: str):
        return self.mcp.get_annotation(id)

    def find_duplicates(self, **kw):
        return self.mcp.find_duplicates(**kw)

    # --- Writes (queued) ----------------------------------------------

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
        args = {
            "text": text,
            "mentions": mentions or [],
            "links": links or [],
            "incoming_links": incoming_links or [],
            "allow_phrasing_violations": allow_phrasing_violations,
            "strict_mentions": strict_mentions,
        }
        if id is not None:
            args["id"] = id
            self._record("upsert_behavior", args)
            return {"behavior_id": id, "near_duplicates": []}
        syn = self._next("beh")
        self._record("upsert_behavior", args, synthetic=syn)
        return {"behavior_id": syn, "near_duplicates": []}

    def replace_text(
        self, id: str, text: str, allow_phrasing_violations: bool = False
    ) -> dict[str, Any]:
        self._record(
            "replace_text",
            {
                "id": id,
                "text": text,
                "allow_phrasing_violations": allow_phrasing_violations,
            },
        )
        return {"behavior_id": id}

    def add_mentions(
        self, id: str, mentions: list[str], strict_mentions: bool = False
    ) -> dict[str, Any]:
        self._record(
            "add_mentions",
            {"id": id, "mentions": mentions, "strict_mentions": strict_mentions},
        )
        return {"behavior_id": id, "added": len(mentions)}

    def remove_mentions(self, id: str, mentions: list[str]) -> dict[str, Any]:
        self._record("remove_mentions", {"id": id, "mentions": mentions})
        return {"behavior_id": id, "removed": len(mentions)}

    def add_links(self, links: list[dict]) -> dict[str, Any]:
        self._record("add_links", {"links": links})
        return {"inserted": len(links)}

    def remove_links(self, links: list[dict]) -> dict[str, Any]:
        self._record("remove_links", {"links": links})
        return {"removed": len(links)}

    def delete_behavior(self, id: str) -> dict[str, Any]:
        self._record("delete_behavior", {"id": id})
        return {"deleted": True}

    def merge_behaviors(
        self, from_behavior_id: str, into_behavior_id: str
    ) -> dict[str, Any]:
        self._record(
            "merge_behaviors",
            {
                "from_behavior_id": from_behavior_id,
                "into_behavior_id": into_behavior_id,
            },
        )
        return {"into_behavior_id": into_behavior_id}

    def upsert_entity(self, name: str, description: str) -> dict[str, Any]:
        syn = self._next("ent")
        self._record(
            "upsert_entity",
            {"name": name, "description": description},
            synthetic=syn,
        )
        return {"entity_id": syn}

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
        args = {
            "kind": kind,
            "text": text,
            "behavior_ids": behavior_ids or [],
            "entity_ids": entity_ids or [],
            "mentions": mentions or [],
            "strict_mentions": strict_mentions,
        }
        if id is not None:
            args["id"] = id
            self._record("upsert_annotation", args)
            return {"annotation_id": id, "near_duplicates": []}
        syn = self._next("ann")
        self._record("upsert_annotation", args, synthetic=syn)
        return {"annotation_id": syn, "near_duplicates": []}

    def attach_annotation(
        self,
        annotation_id: str,
        behavior_id: str | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        self._record(
            "attach_annotation",
            {
                "annotation_id": annotation_id,
                "behavior_id": behavior_id,
                "entity_id": entity_id,
            },
        )
        return {"annotation_id": annotation_id, "attached": 1}

    # --- Validation ---------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of human-readable warnings about plan coherence.

        Surfaces issues an operator should see BEFORE approving:
        - Pending ids referenced but never created in this plan.
        - The same target id is both deleted and modified in the same plan.
        - Duplicate writes were suppressed (informational, not a defect).

        These are warnings, not errors — the operator decides whether the
        plan is acceptable. The substrate's own validation runs at flush
        time and catches missing real ids, phrasing violations, etc.
        """
        warnings: list[str] = []

        created: set[str] = {
            a["synthetic"] for a in self.actions if a["synthetic"] is not None
        }

        def _walk_ids(obj: Any):
            if isinstance(obj, str) and obj.startswith("pending_"):
                yield obj
            elif isinstance(obj, list):
                for x in obj:
                    yield from _walk_ids(x)
            elif isinstance(obj, dict):
                for v in obj.values():
                    yield from _walk_ids(v)

        # Pending-id references that have no matching create.
        for i, action in enumerate(self.actions, 1):
            for ref in _walk_ids(action["args"]):
                if ref not in created:
                    warnings.append(
                        f"action {i} ({action['name']}) references {ref} "
                        f"but no create in this plan produced that id"
                    )

        # Same id is both deleted and otherwise modified in the same plan.
        deleted_ids: set[str] = set()
        modified_ids: set[str] = set()
        for action in self.actions:
            if action["name"] == "delete_behavior":
                deleted_ids.add(action["args"].get("id", ""))
            elif action["name"] in (
                "replace_text",
                "add_mentions",
                "remove_mentions",
            ):
                modified_ids.add(action["args"].get("id", ""))
            elif action["name"] == "upsert_behavior" and action["args"].get("id"):
                modified_ids.add(action["args"]["id"])
        conflict = deleted_ids & modified_ids
        for cid in conflict:
            warnings.append(
                f"behavior {cid} is both deleted AND modified in this plan"
            )

        if self.dedup_skipped:
            warnings.append(
                f"{self.dedup_skipped} duplicate write(s) auto-suppressed "
                "(agent emitted the same call twice)"
            )

        return warnings

    # --- Flush --------------------------------------------------------

    def flush(self) -> list[dict[str, Any]]:
        """Replay queued actions against the real MCP, substituting
        pending ids with real ids as creates resolve. Returns a list of
        per-action result dicts (`{action, result}` or `{action, error}`)."""
        id_map: dict[str, str] = {}
        results: list[dict[str, Any]] = []
        for action in self.actions:
            args = self._substitute(action["args"], id_map)
            method = getattr(self.mcp, action["name"])
            try:
                # Drop None values so methods with defaulted-None params don't
                # see explicit Nones (e.g. attach_annotation's behavior/entity
                # exclusivity check).
                clean = {k: v for k, v in args.items() if v is not None}
                result = method(**clean)
            except Exception as e:
                results.append(
                    {"action": action["name"], "error": f"{type(e).__name__}: {e}"}
                )
                continue
            results.append({"action": action["name"], "result": result})
            syn = action.get("synthetic")
            if syn is not None and isinstance(result, dict):
                real = (
                    result.get("behavior_id")
                    or result.get("entity_id")
                    or result.get("annotation_id")
                )
                if real:
                    id_map[syn] = real
        return results

    def _substitute(self, obj: Any, id_map: dict[str, str]) -> Any:
        if isinstance(obj, str):
            return id_map.get(obj, obj) if obj.startswith("pending_") else obj
        if isinstance(obj, list):
            return [self._substitute(x, id_map) for x in obj]
        if isinstance(obj, dict):
            return {k: self._substitute(v, id_map) for k, v in obj.items()}
        return obj
