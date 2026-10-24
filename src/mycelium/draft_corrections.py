"""Applying a reviewer's precise corrections to a draft's queued operations.

A correction changes exactly what it names: one statement's text or kind,
one link, one statement of a batch, or one whole operation. Indices and `@`
references in corrections name the draft as submitted, so corrections never
depend on each other's order. Dropping a batch statement renumbers that
batch, and every reference to a later statement is rewritten so it keeps its
target. `apply` then checks the result independently: every statement and
operation no correction names must be unchanged, references included.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field

from pydantic import JsonValue, TypeAdapter, ValidationError

from .draft_review_store import Correction, LinkRef

Payload = dict[str, JsonValue]
_payload: TypeAdapter[Payload] = TypeAdapter(Payload)

_SIBLING = re.compile(r"@(\d+)")
_OTHER = re.compile(r"@(\d+):(\d+)")
_EDITABLE = {
    "upsert_statements": {"text", "kind"},
    "upsert_statement": {"text", "kind"},
    "patch_statement": {"text", "kind"},
    "replace_text": {"text"},
    "upsert_entity": {"description"},
}
_EDGE_LISTS = ("add_links", "remove_links")


@dataclass(frozen=True)
class Operation:
    ref: str
    seq: int
    kind: str
    payload: Payload


@dataclass
class Corrected:
    """The draft after its corrections: each surviving operation's payload by
    ref, the refs struck, and the tool calls appended."""

    payloads: dict[str, Payload]
    struck: list[str]
    appended: list[tuple[str, Payload]] = field(default_factory=list)


def parse_payload(correction: Correction) -> Payload:
    if not correction.payload_json:
        raise ValueError(
            "an append correction needs payload_json: the tool's complete "
            "arguments as one JSON object"
        )
    try:
        return _payload.validate_json(correction.payload_json)
    except ValidationError:
        raise ValueError(
            "an append correction's payload_json is not one JSON object"
        ) from None


def apply(operations: list[Operation], corrections: list[Correction]) -> Corrected:
    """The draft's operations after every correction, or ValueError naming
    the first correction that does not fit the draft as submitted."""
    by_ref = {op.ref: op for op in operations}
    payloads = {op.ref: copy.deepcopy(op.payload) for op in operations}
    corrected = Corrected(payloads=payloads, struck=[])
    drops: list[tuple[Operation, int]] = []
    for correction in corrections:
        _check_fields(correction)
        if correction.action == "append":
            assert correction.tool_name is not None  # _check_fields
            corrected.appended.append((correction.tool_name, parse_payload(correction)))
            continue
        ref = correction.operation_ref
        if ref is None or ref not in by_ref:
            raise ValueError(f"operation_ref {ref} names no operation of the draft")
        op = by_ref[ref]
        if correction.action == "strike":
            if sum(c.operation_ref == ref for c in corrections) > 1:
                raise ValueError(
                    f"operation {ref} is struck, so no other correction can change it"
                )
            corrected.struck.append(ref)
            del payloads[ref]
        elif correction.action == "edit":
            _edit(op, payloads[ref], correction)
        elif correction.action in ("add_link", "drop_link"):
            assert correction.link is not None  # _check_fields
            _relink(op, payloads[ref], correction.action, correction.link)
        else:
            drops.append((op, _statement_index(op, correction)))
    dropped: dict[int, set[int]] = {}
    for op, index in drops:
        if index in dropped.setdefault(op.seq, set()):
            raise ValueError(f"statement {index} of {op.ref} is dropped twice")
        dropped[op.seq].add(index)
    for seq, indices in dropped.items():
        op = next(item for item in operations if item.seq == seq)
        _drop(op, sorted(indices), corrected)
    _check_intact(operations, corrections, corrected, dropped)
    if not corrected.payloads and not corrected.appended:
        raise ValueError(
            "the corrections strike every operation, so nothing would land; "
            "a draft that should not land is a reject"
        )
    return corrected


_ALLOWED = {
    "edit": {"operation_ref", "statement", "text", "kind", "description"},
    "add_link": {"operation_ref", "link"},
    "drop_link": {"operation_ref", "link"},
    "drop_statement": {"operation_ref", "statement"},
    "strike": {"operation_ref"},
    "append": {"tool_name", "payload_json"},
}
_OPTIONAL = {"statement", "text", "kind", "description"}


def _check_fields(correction: Correction) -> None:
    allowed = _ALLOWED[correction.action]
    values = correction.model_dump(exclude={"action", "reason"})
    extra = sorted(k for k, v in values.items() if v is not None and k not in allowed)
    if extra:
        raise ValueError(f"{correction.action} takes no " + ", ".join(extra))
    missing = sorted(k for k in allowed - _OPTIONAL if values[k] is None)
    if missing:
        raise ValueError(f"{correction.action} needs " + ", ".join(missing))
    if correction.action == "edit" and not (
        correction.text or correction.kind or correction.description
    ):
        raise ValueError("an edit correction needs text, kind or description")


def _statements(op: Operation, payload: Payload) -> list[JsonValue]:
    statements = payload.get("statements")
    if op.kind != "upsert_statements" or not isinstance(statements, list):
        raise ValueError(f"{op.ref} is a {op.kind}, not an upsert_statements batch")
    return statements


def _statement_index(op: Operation, correction: Correction) -> int:
    statements = _statements(op, op.payload)
    index = correction.statement
    if index is None or not 0 <= index < len(statements):
        raise ValueError(
            f"{op.ref} has statements 0 to {len(statements) - 1}; "
            f"statement {index} names none of them"
        )
    return index


def _edit(op: Operation, payload: Payload, correction: Correction) -> None:
    editable = _EDITABLE.get(op.kind)
    if editable is None:
        raise ValueError(f"an edit correction cannot change a {op.kind} operation")
    changes = {
        key: value
        for key in ("text", "kind", "description")
        if (value := getattr(correction, key)) is not None
    }
    if not changes.keys() <= editable:
        raise ValueError(
            f"an edit of a {op.kind} changes only " + ", ".join(sorted(editable))
        )
    if op.kind == "upsert_statements":
        target = _statements(op, payload)[_statement_index(op, correction)]
        if not isinstance(target, dict):
            raise ValueError(f"statement {correction.statement} of {op.ref} is invalid")
    elif correction.statement is not None:
        raise ValueError(f"{op.ref} holds one record; statement must be null")
    else:
        target = payload
    target.update(changes)


def _when(link: LinkRef) -> JsonValue:
    if link.when_json is None:
        return None
    try:
        when = json.loads(link.when_json)
    except json.JSONDecodeError:
        raise ValueError("a link's when_json is not JSON") from None
    if not isinstance(when, dict):
        raise ValueError("a link's when_json must be a JSON object")
    when_value: JsonValue = when
    return when_value


def _local(op: Operation, reference: str, size: int) -> int | None:
    """The batch index `reference` names in `op`'s own batch, if any."""
    if (sibling := _SIBLING.fullmatch(reference)) is not None:
        index = int(sibling[1])
    elif (other := _OTHER.fullmatch(reference)) is not None and int(other[1]) == op.seq:
        index = int(other[2])
    else:
        return None
    if index >= size:
        raise ValueError(f"{reference} is past the end of {op.ref}'s batch")
    return index


def _matches(item: JsonValue, end: str, other: str, link: LinkRef) -> bool:
    if not isinstance(item, dict) or item.get("link_type") != link.link_type:
        return False
    if item.get(end) != other:
        return False
    return link.when_json is None or item.get("when") == _when(link)


def _relink(op: Operation, payload: Payload, action: str, link: LinkRef) -> None:
    when = _when(link)
    if op.kind in _EDGE_LISTS:
        edges = payload.setdefault("links", [])
        assert isinstance(edges, list)
        found = [
            index
            for index, item in enumerate(edges)
            if isinstance(item, dict)
            and item.get("from_id") == link.from_id
            and item.get("to_id") == link.to_id
            and _matches(item, "to_id", link.to_id, link)
        ]
        if action == "drop_link":
            del edges[_one(found, op, link)]
        elif any(_when_of(edges[i]) == when for i in found):
            raise ValueError(f"{op.ref} already has that link")
        else:
            edge: dict[str, JsonValue] = {
                "from_id": link.from_id,
                "to_id": link.to_id,
                "link_type": link.link_type,
            }
            if when is not None:
                edge["when"] = when
            edges.append(edge)
        return
    statements = _statements(op, payload)
    source = _local(op, link.from_id, len(statements))
    target = _local(op, link.to_id, len(statements))
    if source is None and target is None:
        raise ValueError(
            f'a link correction on {op.ref} needs one end in its batch, written "@N"'
        )
    to_id = f"@{target}" if target is not None else link.to_id
    from_id = f"@{source}" if source is not None else link.from_id
    places: list[tuple[list[JsonValue], int]] = []
    for holder, key, end, other in (
        (source, "links", "to_id", to_id),
        (target, "incoming_links", "from_id", from_id),
    ):
        if holder is None:
            continue
        statement = statements[holder]
        items = statement.get(key, []) if isinstance(statement, dict) else []
        if isinstance(items, list):
            places.extend(
                (items, index)
                for index, item in enumerate(items)
                if _matches(item, end, other, link)
            )
    if action == "drop_link":
        items, index = places[_one(list(range(len(places))), op, link)]
        del items[index]
        return
    if any(_when_of(items[index]) == when for items, index in places):
        raise ValueError(f"{op.ref} already has that link")
    if source is not None:
        holder_statement, key, spec = statements[source], "links", {"to_id": to_id}
    else:
        assert target is not None
        holder_statement, key = statements[target], "incoming_links"
        spec = {"from_id": from_id}
    if not isinstance(holder_statement, dict):
        raise ValueError(f"{op.ref} has an invalid statement")
    new: dict[str, JsonValue] = {**spec, "link_type": link.link_type}
    if when is not None:
        new["when"] = when
    existing = holder_statement.setdefault(key, [])
    assert isinstance(existing, list)
    existing.append(new)


def _when_of(item: JsonValue) -> JsonValue:
    return item.get("when") if isinstance(item, dict) else None


def _one(found: list[int], op: Operation, link: LinkRef) -> int:
    name = f"{link.from_id} {link.link_type} {link.to_id}"
    if not found:
        raise ValueError(f"{op.ref} has no link {name}")
    if len(found) > 1:
        raise ValueError(
            f"{op.ref} has {len(found)} links {name}; give when_json to name one"
        )
    return found[0]


def _rewrite(value: JsonValue, rename: dict[str, str]) -> JsonValue:
    if isinstance(value, str):
        return rename.get(value, value)
    if isinstance(value, list):
        return [_rewrite(item, rename) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite(item, rename) for key, item in value.items()}
    return value


def _strings(value: JsonValue) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def _drop(op: Operation, indices: list[int], corrected: Corrected) -> None:
    payload = corrected.payloads.get(op.ref)
    if payload is None:
        raise ValueError(f"{op.ref} is struck, so none of its statements can drop")
    statements = _statements(op, payload)
    if len(indices) >= len(statements):
        raise ValueError(
            f"dropping every statement of {op.ref} empties it; strike it instead"
        )
    kept = [index for index in range(len(statements)) if index not in indices]
    inside = {f"@{old}": f"@{new}" for new, old in enumerate(kept)}
    outside = {f"@{op.seq}:{old}": f"@{op.seq}:{new}" for new, old in enumerate(kept)}
    gone_inside = {f"@{index}" for index in indices}
    gone_outside = {f"@{op.seq}:{index}" for index in indices}
    remaining = [statements[index] for index in kept]
    holders = [(op.ref, remaining, gone_inside | gone_outside)] + [
        (ref, other, gone_outside)
        for ref, other in corrected.payloads.items()
        if ref != op.ref
    ]
    holders += [
        (f"appended {tool}", other, gone_outside) for tool, other in corrected.appended
    ]
    for name, value, gone in holders:
        if named := sorted(gone & set(_strings(value))):
            raise ValueError(
                f"{op.ref}'s dropped statement is still named by {name} as "
                + ", ".join(named)
                + "; drop or re-point those links too"
            )
    payload["statements"] = [_rewrite(item, inside | outside) for item in remaining]
    for ref, other in list(corrected.payloads.items()):
        if ref != op.ref:
            rewritten = _rewrite(other, outside)
            assert isinstance(rewritten, dict)
            corrected.payloads[ref] = rewritten
    corrected.appended = [
        (tool, rewritten)
        for tool, other in corrected.appended
        if isinstance(rewritten := _rewrite(other, outside), dict)
    ]


def _identity_view(
    payload: Payload, seq: int | None, positions: dict[int, list[int]]
) -> JsonValue:
    """`payload` with every draft reference replaced by the statement it
    resolves to, as `#seq:original-index`, so references compare by target."""

    def resolve(text: str) -> str:
        if seq is not None and (sibling := _SIBLING.fullmatch(text)):
            index = int(sibling[1])
            original = positions.get(seq)
            return f"#{seq}:{original[index] if original and index < len(original) else index}"
        if other := _OTHER.fullmatch(text):
            batch, index = int(other[1]), int(other[2])
            original = positions.get(batch)
            return f"#{batch}:{original[index] if original and index < len(original) else index}"
        return text

    def visit(value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return resolve(value)
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value

    return visit(payload)


def _named(
    operations: list[Operation], corrections: list[Correction]
) -> tuple[set[str], dict[str, set[int]]]:
    """The operations corrections name as a whole, and the batch statements
    they name, by operation ref."""
    whole = {
        c.operation_ref
        for c in corrections
        if c.operation_ref is not None and c.statement is None
    }
    statements: dict[str, set[int]] = {}
    by_ref = {op.ref: op for op in operations}
    for c in corrections:
        if c.operation_ref is None:
            continue
        indices = statements.setdefault(c.operation_ref, set())
        if c.statement is not None:
            indices.add(c.statement)
        op = by_ref.get(c.operation_ref)
        if c.link is not None and op is not None and op.kind == "upsert_statements":
            size = len(_statements(op, op.payload))
            for end in (c.link.from_id, c.link.to_id):
                if (index := _local(op, end, size)) is not None:
                    indices.add(index)
    return whole, statements


def _check_intact(
    operations: list[Operation],
    corrections: list[Correction],
    corrected: Corrected,
    dropped: dict[int, set[int]],
) -> None:
    """Refuse a result that changed or lost anything no correction names."""
    named_ops, named_statements = _named(operations, corrections)
    before_positions = {
        op.seq: list(range(len(statements)))
        for op in operations
        if op.kind == "upsert_statements"
        and isinstance(statements := op.payload.get("statements"), list)
    }
    after_positions = {
        seq: [index for index in indices if index not in dropped.get(seq, set())]
        for seq, indices in before_positions.items()
    }
    for op in operations:
        if op.ref in corrected.struck:
            continue
        after = corrected.payloads[op.ref]
        own = op.seq if op.kind == "upsert_statements" else None
        old = _identity_view(op.payload, own, before_positions)
        new = _identity_view(after, own, after_positions)
        if op.kind != "upsert_statements" or not isinstance(old, dict):
            if op.ref not in named_ops and old != new:
                raise ValueError(f"the corrections changed {op.ref}, which none names")
            continue
        assert isinstance(new, dict)
        old_items, new_items = old.get("statements"), new.get("statements")
        assert isinstance(old_items, list) and isinstance(new_items, list)
        survivors = after_positions[op.seq]
        if len(new_items) != len(survivors):
            raise ValueError(f"the corrections lost a statement of {op.ref}")
        named = named_statements.get(op.ref, set())
        for position, original in enumerate(survivors):
            if original not in named and new_items[position] != old_items[original]:
                raise ValueError(
                    f"the corrections changed statement {original} of {op.ref}, "
                    "which none names"
                )
        if {k: v for k, v in old.items() if k != "statements"} != {
            k: v for k, v in new.items() if k != "statements"
        }:
            raise ValueError(f"the corrections changed {op.ref}, which none names")
