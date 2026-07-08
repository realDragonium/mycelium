"""Heuristic pre-filter for code-leaky behavior text.

Recall-first — flags anything that looks like it might leak implementation
detail. The agent then decides per-suspect whether the leak is real and
whether the behavior can be salvaged into product-level wording. False
positives here are cheap (the agent will return `skip`); false negatives
are expensive (the suspect never reaches the agent).

Patterns flagged:
- *Service / *Manager / *Repository / *Provider / *Factory / *Handler / *Helper suffixes
- *Exception / *Error class names
- "raises/throws/returns/instantiates …" verbs
- SQL keywords inside the text
- Two-or-more CamelCase tokens combined with code-vocabulary words
"""

from __future__ import annotations

import re
from typing import Any

from mcp_client import MyceliumClient

_SUFFIX_RE = re.compile(
    r"\b[A-Z][a-zA-Z]*(?:Service|Manager|Repository|Provider|Factory|Handler|Processor|Helper|Validator|Serializer|Deserializer|Controller|Resolver)\b"
)
_EXCEPTION_RE = re.compile(r"\b[A-Z][a-zA-Z]*(?:Exception|Error)\b")
_VERB_RE = re.compile(
    r"\b(?:throws?|raises?|returns?|instantiates?|deserializes?|serializes?)\s+(?:[A-Z][a-zA-Z]*|[`'\"][^`'\"]+[`'\"])"
)
_SQL_RE = re.compile(
    r"\b(?:INSERT INTO|SELECT \*|UPDATE \w+ SET|DELETE FROM|JOIN|WHERE|FROM \w+)\b"
)
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
_CODE_VOCAB = (
    "method",
    "function",
    "class",
    "module",
    "import",
    "callback",
    "exception",
    "interface",
)


def is_leaky(text: str) -> bool:
    if _SUFFIX_RE.search(text):
        return True
    if _EXCEPTION_RE.search(text):
        return True
    if _VERB_RE.search(text):
        return True
    if _SQL_RE.search(text):
        return True
    if len(_CAMEL_RE.findall(text)) >= 2 and any(
        w in text.lower() for w in _CODE_VOCAB
    ):
        return True
    return False


def find_candidates(
    mcp: MyceliumClient, sample: int | None = None
) -> list[dict[str, str]]:
    """Walk every behavior in the substrate and return suspected leaks.

    `sample`: when set, randomly samples that many behaviors AFTER filtering
    (so the sample is over leaks, not over the whole substrate). When None,
    returns every leak found.
    """
    import random

    rows = mcp.list_all_behaviors()
    leaks = [{"id": r["id"], "text": r["text"]} for r in rows if is_leaky(r["text"])]
    if sample and sample > 0 and len(leaks) > sample:
        leaks = random.sample(leaks, sample)
    return leaks
