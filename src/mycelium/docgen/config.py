"""Tunables for the documentation-generation loop.

Config follows the repo convention (ingest/config.py, research/config.py): a
frozen dataclass of defaults, `from_env` reading `MYCELIUM_DOCGEN_*` with
inline fallbacks. No central settings module.

Claude remains the default and falls back to ingest's model. GPT uses an
explicitly configured model ID. A generation
run is shaped like `research` rather than like `ask` — it surveys the
substrate before it writes a word — so the op cap and wall clock are sized
closer to a research run than to a single question.

A run reads TWO kinds of steering text, and only one of them is a file here.
The GUIDELINE SET says how to write a document and lives entirely in the
prompt store as rows an operator can edit or add without a redeploy
(docs/GUIDELINE_SETS.md) — `guideline_set` below is only the instance's
preferred set, never a path. The DOCTRINE says how to run the loop that
writes one, and follows its siblings exactly: a packaged file seeds the
`(doctrine, docgen)` row at startup, and the loop reads the row per run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from .. import tracing
from ..guidelines import SET_NAME
from ..ingest.config import DEFAULT_MODEL

#: The generation doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the docgen doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit through `save_prompt_text` lands on the next documentation run.
DOCTRINE_NAME = "docgen"


Provider = Literal["claude", "openai"]


def resolve_provider(value: str | None = None) -> Provider:
    selected = value or os.environ.get("MYCELIUM_DOCGEN_PROVIDER", "claude")
    if selected not in ("claude", "openai"):
        raise ValueError("documentation provider must be claude or openai")
    return selected


class ModelChoice(TypedDict):
    provider: Provider
    label: str
    model: str | None
    available: bool
    reason: str | None


def _claude_configuration_error() -> str | None:
    from anthropic import Anthropic, AnthropicError

    # SDK discovery includes tokens, profiles and federation. Constructing a
    # client resolves configuration locally; credentials are fetched on request.
    try:
        with Anthropic() as client:
            if client.api_key or client.auth_token or client.credentials:
                return None
    except (AnthropicError, ValueError, OSError):
        return "Check the server's Anthropic credential configuration."
    return "Configure Anthropic credentials on the server."


def model_choices() -> list[ModelChoice]:
    choices: list[ModelChoice] = []
    for provider in ("claude", "openai"):
        config = DocgenConfig.from_env(provider=resolve_provider(provider))
        key = "ANTHROPIC_API_KEY" if provider == "claude" else "OPENAI_API_KEY"
        reason = None
        if not config.model:
            reason = (
                "Set MYCELIUM_DOCGEN_OPENAI_MODEL on the server."
                if provider == "openai"
                else "Set MYCELIUM_DOCGEN_MODEL on the server."
            )
        elif provider == "claude":
            reason = _claude_configuration_error()
        elif not os.environ.get(key, "").strip():
            reason = f"Set {key} on the server."
        choices.append(
            {
                "provider": config.provider,
                "label": "Claude" if provider == "claude" else "GPT",
                "model": config.model or None,
                "available": reason is None,
                "reason": reason,
            }
        )
    return choices


@dataclass(frozen=True)
class DocgenConfig:
    model: str = DEFAULT_MODEL
    provider: Provider = "claude"
    #: The set this instance prefers when the request named none. It is a
    #: preference the resolution step is told about, not an override: the
    #: request wins, and a prompt that plainly asks for another configured
    #: set wins too. Defaults to the one set that ships, so an instance that
    #: has only ever been booted (never configured) still has a preference.
    guideline_set: str = SET_NAME
    #: Hard ceiling on tool operations per run. Every substrate read the run
    #: makes while gathering material counts toward it.
    op_cap: int = 150
    #: Whole-run wall-clock budget, seconds. A run holds a shared model-loop
    #: slot for its whole life, so this is also how long one request can keep
    #: that slot from `ask` and `ingest`.
    wall_clock_s: float = 900.0
    #: max_tokens per model turn. A document body is the largest single thing
    #: any loop in this tree emits, hence the headroom over ask's.
    max_tokens: int = 12000
    #: Anthropic SDK auto-retries 429/5xx/connection with exponential backoff.
    max_retries: int = 4
    #: Per-Anthropic-call timeout, seconds. Kept well under the wall clock so
    #: a single hung call can't blow the whole budget.
    request_timeout_s: float = 120.0
    #: Adaptive thinking in the loop.
    thinking: bool = True
    #: Cap on the requested prompt. Enforced at the door by
    #: `request_documentation`, which refuses rather than truncates: a
    #: documentation request is something a person typed, and silently
    #: dropping its tail would generate the wrong document instead of an
    #: error the caller can act on.
    max_prompt_chars: int = 2000
    #: Width of the opening `survey_statements` map of the request. Wider
    #: than ask's recon: a document covers a topic, not a question.
    recon_k: int = 30
    #: Path to the docgen doctrine seeded into the store and injected into
    #: the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: Pricing, $ / 1M tokens — used only to stamp an estimated cost on the
    #: trace. Override when running a non-default model.
    input_per_mtok: float | None = 3.0
    output_per_mtok: float | None = 15.0
    #: JSONL sink for the trace. None disables it.
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/ingest/research); empty string disables writing.
    trace_dir: str | None = None

    @classmethod
    def from_env(cls, *, provider: Provider | None = None) -> "DocgenConfig":
        selected_provider = resolve_provider(provider)

        def _f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        def _i(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        return cls(
            provider=selected_provider,
            model=(
                (os.environ.get("MYCELIUM_DOCGEN_OPENAI_MODEL") or "").strip()
                if selected_provider == "openai"
                else (
                    os.environ.get("MYCELIUM_DOCGEN_MODEL")
                    or os.environ.get("MYCELIUM_INGEST_MODEL")
                    or DEFAULT_MODEL
                ).strip()
            ),
            guideline_set=os.environ.get("MYCELIUM_DOCGEN_GUIDELINE_SET") or SET_NAME,
            op_cap=_i("MYCELIUM_DOCGEN_OP_CAP", 150),
            wall_clock_s=_f("MYCELIUM_DOCGEN_WALL_CLOCK_S", 900.0),
            max_tokens=_i("MYCELIUM_DOCGEN_MAX_TOKENS", 12000),
            max_retries=_i("MYCELIUM_DOCGEN_MAX_RETRIES", 4),
            request_timeout_s=_f("MYCELIUM_DOCGEN_REQUEST_TIMEOUT_S", 120.0),
            thinking=(
                os.environ.get("MYCELIUM_DOCGEN_THINKING", "on").lower() != "off"
            ),
            max_prompt_chars=_i("MYCELIUM_DOCGEN_MAX_PROMPT_CHARS", 2000),
            recon_k=_i("MYCELIUM_DOCGEN_RECON_K", 30),
            doctrine_path=(
                os.environ.get("MYCELIUM_DOCGEN_DOCTRINE_PATH")
                or _DEFAULT_DOCTRINE_PATH
            ),
            input_per_mtok=(
                None
                if selected_provider == "openai"
                else _f("MYCELIUM_DOCGEN_INPUT_PER_MTOK", 3.0)
            ),
            output_per_mtok=(
                None
                if selected_provider == "openai"
                else _f("MYCELIUM_DOCGEN_OUTPUT_PER_MTOK", 15.0)
            ),
            trace_log_path=os.environ.get("MYCELIUM_DOCGEN_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_DOCGEN_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
