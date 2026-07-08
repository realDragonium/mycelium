"""Shared harness primitives for the three agent-loop packages.

`ask`, `ingest`, and `research` each drive one model context over the substrate
read tools inside a deterministic harness (recon/vocab fetch, the tool-use loop,
an anti-premature-closure floor, op-cap / wall-clock / max-turn ceilings, and
graceful degradation). The *shape* of each loop differs — ask has parallel tool
use and two terminals, ingest/research have one emit terminal and draft
assembly — but a spine of small, boundary-facing helpers is identical across
them. That spine lives here so the three packages compose over it instead of
each carrying a copy.

Everything here is a plain function over plain data (or the injectable
Anthropic client). No package imports ask/ingest/research, so there is no cycle
— the loops import from this module, never the reverse. The `import anthropic`
inside `default_client` stays function-local so the packages import without the
SDK installed.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

#: Cap on a serialized tool_result fed back to the model.
_TOOL_RESULT_MAX_CHARS = 20000


# --------------------------------------------------------------------------- #
# Client + doctrine (framework-seam helpers)
# --------------------------------------------------------------------------- #


def default_client(max_retries: int) -> Any:
    import anthropic  # local import: keeps the package importable without the SDK

    return anthropic.Anthropic(max_retries=max_retries)


def load_doctrine(doctrine_path: str) -> tuple[str, str | None]:
    """Read the reasoning doctrine best-effort. On failure, return ("", note)
    so the loop proceeds on the base prompt and records why."""
    try:
        return Path(doctrine_path).read_text(encoding="utf-8"), None
    except Exception as exc:  # noqa: BLE001 — best-effort; proceed without it
        return "", f"doctrine unreadable ({doctrine_path}): {exc}"


# --------------------------------------------------------------------------- #
# Budget gate
# --------------------------------------------------------------------------- #


def check_budget(trace: Any, config: Any, start: float, max_turns: int) -> str | None:
    """The shared budget gate: op-cap, then wall-clock, then max-turns.

    Returns the forced-finalize reason string (`"op_cap"` / `"wall_clock"` /
    `"turn_limit"`) when a ceiling is hit, else None. Order matters — op_cap is
    checked before the (cheaper-to-exceed) wall clock, matching every call site.
    Duck-typed on the harness contract: `trace.op_count`, `trace.model_turns`,
    `config.op_cap`, `config.wall_clock_s`.
    """
    if trace.op_count >= config.op_cap:
        return "op_cap"
    if (time.monotonic() - start) > config.wall_clock_s:
        return "wall_clock"
    if trace.model_turns >= max_turns:
        return "turn_limit"
    return None


# --------------------------------------------------------------------------- #
# Response + message helpers
# --------------------------------------------------------------------------- #


def first_tool_use(resp: Any) -> Any | None:
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return block
    return None


def _block_type(block: Any) -> Any:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def strip_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop thinking / redacted_thinking blocks from assistant turns.

    Used only for the thinking-disabled forced-finalize request: a request
    without thinking enabled should not carry thinking blocks. If filtering
    would empty a message's content, the original is kept (an empty content
    list is itself invalid).
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            filtered = [
                b
                for b in content
                if _block_type(b) not in ("thinking", "redacted_thinking")
            ]
            out.append({**message, "content": filtered or content})
        else:
            out.append(message)
    return out


def serialize(result: Any) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(result)
    if len(text) > _TOOL_RESULT_MAX_CHARS:
        text = text[:_TOOL_RESULT_MAX_CHARS] + "\n…[truncated]"
    return text


def substrate_has(substrate: Any, name: str) -> bool:
    has = getattr(substrate, "has", None)
    if callable(has):
        return bool(has(name))
    return any(spec.name == name for spec in substrate.tool_specs())


def append_tool_error(
    messages: list[dict[str, Any]], tool_use_id: str, message: str
) -> None:
    """Answer a single (terminal) tool_use with an error, as its own user
    message. Reads are batched by the caller; terminals are handled one at a
    time, so a per-message append is correct here."""
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": message,
                    "is_error": True,
                }
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Tool wiring
# --------------------------------------------------------------------------- #


def read_tool_defs(specs: list[Any]) -> list[dict]:
    """The read primitives, as tool defs for the model — the shared head of each
    package's `build_tools` (terminal tools are appended per package)."""
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in specs
    ]


# --------------------------------------------------------------------------- #
# Trace: the shared record dataclass + the method bodies the two TraceBuilders
# delegate to. Each package keeps its own `TraceBuilder` (own fields + own
# `build()` record shape); these free functions carry the identical mechanics so
# the two builders stay in lockstep without inheritance.
# --------------------------------------------------------------------------- #


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result_size: int
    ok: bool
    counts_as_op: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result_size": self.result_size,
            "ok": self.ok,
            "counts_as_op": self.counts_as_op,
            "error": self.error,
        }


def _result_size(result: Any) -> int:
    """Cheap, robust size signal for a tool result (count of items, else chars)."""
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("statements", "entities", "results"):
            v = result.get(key)
            if isinstance(v, list):
                return len(v)
        return len(result)
    try:
        return len(str(result))
    except Exception:  # noqa: BLE001
        return 0


@contextmanager
def span(spans: Any, name: str) -> Iterator[None]:
    with spans.span(name):
        yield


def record_tool_call(
    trace: Any,
    name: str,
    arguments: dict[str, Any],
    result: Any,
    *,
    ok: bool,
    counts_as_op: bool,
    error: str | None = None,
) -> None:
    if counts_as_op:
        trace.op_count += 1
    trace.tool_calls.append(
        ToolCallRecord(
            name=name,
            arguments=dict(arguments),
            result_size=_result_size(result),
            ok=ok,
            counts_as_op=counts_as_op,
            error=error,
        )
    )


def add_usage(trace: Any, usage: Any) -> None:
    if usage is None:
        return
    trace.tokens["input"] += int(getattr(usage, "input_tokens", 0) or 0)
    trace.tokens["output"] += int(getattr(usage, "output_tokens", 0) or 0)
    trace.tokens["cache_read"] += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    trace.tokens["cache_creation"] += int(
        getattr(usage, "cache_creation_input_tokens", 0) or 0
    )


def cost_usd(
    tokens: dict[str, int], input_per_mtok: float, output_per_mtok: float
) -> float:
    return round(
        tokens["input"] / 1_000_000 * input_per_mtok
        + tokens["output"] / 1_000_000 * output_per_mtok,
        6,
    )


def write_record(path: str | Path, record: dict) -> None:
    """Append one trace record as a single JSONL line. Best-effort: a logging
    failure must never mask the result."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass
