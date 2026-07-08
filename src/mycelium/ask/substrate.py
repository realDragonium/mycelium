"""The in-process substrate seam.

The reasoning loop depends only on this thin interface — it never imports
`server`/`store` directly. The one concrete implementation calls the registered
read primitives *as code* in the same process (no MCP loopback, no network).

Tools are **discovered**, not hardcoded: every reader-role function on
`server.TOOLS` that is a side-effect-free substrate read is exposed, its Claude
tool schema generated from the primitive's real signature. Adding a future read
primitive requires no change here.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import create_model

#: Reader-role tools that are NOT side-effect-free substrate reads, so they must
#: not be offered to the inner model. This is a *denylist* (not an allowlist):
#: any new read primitive is auto-discovered and exposed without editing this
#: set — which is what keeps the "discover, don't hardcode" guarantee.
_NON_READ_READER_TOOLS = frozenset(
    {
        "report_knowledge_gap",  # role=reader but WRITES a knowledge-gap record
        "ask",  # this tool itself — avoid recursion
        "list_my_drafts",  # draft-session state, not the substrate
        "get_draft",  # draft-session state, not the substrate
    }
)

#: Injected by the @tool wrapper onto draftable list tools; not a real read
#: parameter, so it's hidden from the inner model.
_HIDDEN_PARAMS = frozenset({"draft_id"})


@dataclass(frozen=True)
class ToolSpec:
    """A discovered read primitive, bridged to a Claude tool definition."""

    name: str
    description: str
    input_schema: dict


class SubstrateReader(Protocol):
    """The seam the loop depends on."""

    def tool_specs(self) -> list[ToolSpec]: ...

    def call(self, name: str, arguments: dict[str, Any]) -> Any: ...


class SubstrateError(RuntimeError):
    """A substrate read failed twice (after one retry). The loop renders this
    as an error tool_result rather than throwing to the caller."""


def _json_schema_for(func: Callable[..., Any]) -> dict:
    """Build a JSON Schema for a primitive's parameters from its signature.

    Mirrors how `http.py` derives a pydantic body model from the same
    signature, then emits JSON Schema for the Anthropic tool definition.
    """
    sig = inspect.signature(func)
    try:
        hints = inspect.get_annotations(func, eval_str=True)
    except Exception:  # noqa: BLE001 — best-effort; fall back to str typing
        hints = {}

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        if name in _HIDDEN_PARAMS:
            continue
        annotation = hints.get(name, str)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    model = create_model(func.__name__ + "Args", **fields)
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema["type"] = "object"
    return schema


def _description_for(func: Callable[..., Any]) -> str:
    doc = inspect.getdoc(func) or f"Read primitive `{func.__name__}`."
    # Keep tool descriptions compact — the inner model has the whole set.
    return doc.strip()[:1500]


class InProcessSubstrate:
    """Calls `server`'s registered read primitives directly, in-process.

    `server_module` is injectable so tests can supply a stub registry; in
    production it is `mycelium.server` (its globals must be `init()`-ialised).
    """

    def __init__(self, server_module: Any | None = None) -> None:
        if server_module is None:
            from .. import server as server_module  # lazy: avoid import cycle
        self._server = server_module
        self._funcs: dict[str, Callable[..., Any]] = {}
        self._specs: list[ToolSpec] = []
        self._discover()

    def _discover(self) -> None:
        for wrapper in getattr(self._server, "TOOLS", []):
            name = getattr(wrapper, "__name__", "")
            role = getattr(wrapper, "_mycelium_required_role", None)
            if role != "reader" or name in _NON_READ_READER_TOOLS:
                continue
            self._funcs[name] = wrapper
            self._specs.append(
                ToolSpec(
                    name=name,
                    description=_description_for(wrapper),
                    input_schema=_json_schema_for(wrapper),
                )
            )

    def tool_specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def has(self, name: str) -> bool:
        return name in self._funcs

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a read primitive, retrying once on a transient failure.

        The substrate (vector index / Ollama embed) is known to be slow and to
        occasionally time out; the repo convention is try-once-retry-once. On a
        second failure we raise `SubstrateError` for the loop to surface as a
        gap, never returning a fabricated empty result silently.
        """
        func = self._funcs.get(name)
        if func is None:
            raise SubstrateError(f"unknown read primitive: {name!r}")
        try:
            return func(**arguments)
        except Exception:  # noqa: BLE001 — transient substrate/index/Ollama; retry once
            try:
                return func(**arguments)
            except Exception as exc:  # noqa: BLE001
                raise SubstrateError(f"{name} failed after retry: {exc}") from exc
