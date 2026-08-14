"""Tunables for the documentation-generation loop.

Config follows the repo convention (ingest/config.py, research/config.py): a
frozen dataclass of defaults, `from_env` reading `MYCELIUM_DOCGEN_*` with
inline fallbacks. No central settings module.

The model default falls back to ingest's, as research's does. A generation
run is shaped like `research` rather than like `ask` — it surveys the
substrate before it writes a word — so the op cap and wall clock are sized
closer to a research run than to a single question.

What is deliberately absent is a doctrine path, and that is the one place
this config departs from its siblings. Every other loop injects a doctrine
file that ships in the package; a documentation run follows a GUIDELINE SET,
which lives in the prompt store as rows an operator can edit or add without a
redeploy (docs/GUIDELINE_SETS.md). `guideline_set` here is only the fallback
for a request that names none — the text itself is never a file path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..guidelines import SET_NAME
from ..ingest.config import DEFAULT_MODEL


@dataclass(frozen=True)
class DocgenConfig:
    model: str = DEFAULT_MODEL
    #: The guideline set a run writes against when the request named none.
    #: Defaults to the one set that ships, so an instance that has only ever
    #: been booted (never configured) can still generate.
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

    @classmethod
    def from_env(cls) -> "DocgenConfig":
        def _f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        def _i(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        return cls(
            model=(
                os.environ.get("MYCELIUM_DOCGEN_MODEL")
                or os.environ.get("MYCELIUM_INGEST_MODEL")
                or DEFAULT_MODEL
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
        )
