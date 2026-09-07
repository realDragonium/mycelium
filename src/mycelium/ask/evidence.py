"""Run-local references for complete statement records actually supplied to the model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import JsonValue, TypeAdapter

JSON = TypeAdapter(JsonValue)
MAX_CONTEXT_CHARS = 20_000


def _dump(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def bound_payload(value: JsonValue, limit: int = MAX_CONTEXT_CHARS) -> JsonValue:
    """Omit whole list entries, never cut statement text or a condition tree."""
    if len(_dump(value)) <= limit:
        return value
    if isinstance(value, list):
        kept: list[JsonValue] = []
        for item in value:
            if (
                len(_dump({"items": [*kept, item], "omitted_items": len(value)}))
                > limit
            ):
                break
            kept.append(item)
        return {"items": kept, "omitted_items": len(value) - len(kept)}
    if isinstance(value, dict):
        # Only top-level collections contain independently meaningful records.
        result = dict(value)
        lists = [key for key, item in result.items() if isinstance(item, list)]
        omitted: dict[str, JsonValue] = {}
        while lists and len(_dump(result)) > limit - 100:
            key = max(lists, key=lambda key: len(_dump(result[key])))
            items = result[key]
            if isinstance(items, list) and items:
                result[key] = items[:-1]
                count = omitted.get(key, 0)
                omitted[key] = count + 1 if isinstance(count, int) else 1
            else:
                lists.remove(key)
        if len(_dump(result)) <= limit - 100:
            return {**result, "omitted_items": omitted}
    return {
        "omitted_items": 1,
        "reason": "record exceeds context budget; narrow retrieval",
    }


def _has_omissions(value: JsonValue) -> bool:
    if isinstance(value, dict):
        return any(_has_omissions(item) for item in value.values())
    return bool(value)


@dataclass
class Evidence:
    by_ref: dict[str, str] = field(default_factory=dict)
    last_ids: set[str] = field(default_factory=set)
    supplied_chars: int = 0
    omitted: bool = False

    @property
    def ids(self) -> set[str]:
        return set(self.by_ref.values())

    def supply(self, value: object) -> str:
        value = JSON.validate_python(value)
        pending = dict(self.by_ref)
        reverse = {sid: ref for ref, sid in pending.items()}

        def annotate(item: JsonValue) -> JsonValue:
            if isinstance(item, list):
                return [annotate(child) for child in item]
            if not isinstance(item, dict):
                return item
            out = {key: annotate(child) for key, child in item.items()}
            sid = item.get("id")
            if (
                isinstance(sid, str)
                and sid.startswith("stm_")
                and isinstance(item.get("text"), str)
            ):
                next_ref = max((int(ref[1:]) for ref in pending), default=0) + 1
                ref = reverse.setdefault(sid, f"s{next_ref}")
                pending[ref] = sid
                out["ref"] = ref
            return out

        bounded = bound_payload(annotate(value))
        self.last_ids = set()

        def register(item: JsonValue) -> None:
            if isinstance(item, dict):
                for key, value in item.items():
                    if (
                        key.endswith("_truncated")
                        or key in {"truncated", "omitted_items"}
                    ) and _has_omissions(value):
                        self.omitted = True
                ref = item.get("ref")
                if (
                    isinstance(ref, str)
                    and pending.get(ref) == item.get("id")
                    and isinstance(item.get("text"), str)
                ):
                    self.by_ref[ref] = pending[ref]
                    self.last_ids.add(pending[ref])
                for child in item.values():
                    register(child)
            elif isinstance(item, list):
                for child in item:
                    register(child)

        register(bounded)
        sent = _dump(bounded)
        self.supplied_chars += len(sent)
        return sent

    def expand(self, references: list[str]) -> list[str]:
        result: list[str] = []
        for ref in references:
            # Full statement IDs remain accepted for older injected model clients.
            sid = self.by_ref.get(ref, ref if ref in self.ids else None)
            if sid is None:
                raise ValueError(f"Unknown statement evidence reference: {ref}")
            if sid not in result:
                result.append(sid)
        return result
