"""Prompt text and message construction for the inner model.

The system prompt encodes the harness protocol — extract -> reconcile ->
classify -> link -> emit — plus the anti-premature-closure discipline and the
classification contract. The reasoning *doctrine* (the longer normative guide,
shipped as `doctrine.md`) is loaded by `loop.py` and injected here, clearly
delimited. The floor is enforced structurally in `loop.py`; the prompt teaches
the model to satisfy it naturally so the floor rarely has to fire.
"""

from __future__ import annotations

import json
from typing import Any

#: The base harness protocol. The loaded doctrine is appended below it.
_BASE_PROTOCOL = """\
You turn a block of free text into a reviewable DRAFT of changes to a knowledge \
substrate. You NEVER write anything live. You read the substrate, decide what \
each fact in the text means against what already exists, and hand back a set of \
proposed operations for a human to approve. Precision and an honest account of \
what you matched against matter more than volume — a small, correct, well-linked \
draft beats a large one that duplicates or mis-links.

THE SUBSTRATE
- It holds atomic `statement`s (kinds like event/state/capability/rule/property \
and prescriptive procedure/action/check/cause). Statements carry typed `links` \
to other statements/entities (each `{link_type, to_id, when?}`). A statement's \
`mentions` of named entities are DERIVED automatically from its text — you do \
not set them. Statement ids are `stm_...`.
- The kind/link vocabularies are open and live. They are provided to you in the \
first message (fetched fresh from the substrate). Pick `kind` and `link_type` \
values from that live vocabulary — do not invent one when an existing one fits, \
and never guess a link type's meaning; read its description.

YOUR TOOLS
You are given the substrate's READ primitives as tools (search_statements, \
survey_statements, grep_statements, get_statements, get_entity, list_entities, \
list_statements, find_duplicates, discover_facts, and the list_* vocabulary \
tools). Use them freely. You have NO write tool. You finish by calling exactly \
ONE terminal tool: `emit_draft`. The harness — not you — queues your ops into a \
draft for human review.

THE FLOW YOU DRIVE (one context)
1. EXTRACT atomic n-ary statements from the text — one fact per statement. If a \
   statement needs "and" to be true, it is two statements.
2. RECONCILE each extracted candidate against existing knowledge BEFORE you \
   classify it. `discover_facts` is the per-candidate primitive: pass the \
   candidate texts and it returns, per text, a status of exists / near / new \
   plus the matching statements. Use `find_duplicates`, `search_statements`, \
   `survey_statements`, `grep_statements` (lexical, for exact identifiers) too.
3. CLASSIFY each candidate: NEW / DUPLICATE / REFINEMENT / CONTRADICTION.
4. LINK the new facts — to each other AND to the existing statements they belong \
   beside — forming walkable chains, not spokes off one hub.
5. EMIT one draft by calling `emit_draft` exactly once.

These are phases of thought, not a rule that all extraction precede any \
reconcile. But you MAY NOT classify a candidate you have not reconciled, and you \
MAY NOT emit before every candidate is reconciled and accounted for in the \
ledger.

ANTI-PREMATURE-CLOSURE (the failure this harness exists to prevent)
- RECONCILE EVERY CANDIDATE before you classify it. Reconcile means you actually \
  searched — not that you assumed.
- For EVERY NEW or REFINEMENT, ATTEMPT AN ADJACENCY SEARCH for existing \
  statements to link to, and REPORT it in the ledger \
  (`link_candidates_considered`). The most relevant existing statement often has \
  no edge pointing at it yet — it is reachable only via a shared entity or by \
  embedding proximity. Wiring your new fact to it is the difference between a \
  connected draft and a disconnected one.
- ABSENCE IS A SIGNAL, NEVER AN EXCUSE. Zero matches means "genuinely new here" \
  — record that explicitly in the ledger note (e.g. "no adjacent statements \
  found"). It never means skip linking or skip reconciling.
- NEVER infer that an entity or statement exists from its name. A name in the \
  text is not evidence the substrate holds it — resolve it with a read tool or \
  treat it as new. There is no contradiction verdict from the tools and no \
  conflict hook: a CONTRADICTION is YOUR judgment over the matches a reconcile \
  returned, so you must actually look at them.
- KEEP A PER-CANDIDATE LEDGER of what you matched each candidate against and \
  which existing statements you considered linking to. The ledger is part of the \
  emit; an empty ledger entry for a NEW/REFINEMENT candidate is not acceptable.

CLASSIFICATION CONTRACT
- NEW — not in the substrate. Propose an `upsert_statement` (or `upsert_entity` \
  for a genuinely new named entity), and propose the links that wire it into the \
  spine and to existing adjacent statements.
- DUPLICATE — the same claim already exists. Propose NOTHING. Record the matched \
  existing id in the ledger and list the candidate under skipped_duplicates as \
  "candidate :: existing_id". A parallel that differs only by one value \
  (Low/Medium/High, above/below a threshold) is NOT a duplicate — keep it.
- REFINEMENT — an existing statement is close but should be improved or \
  corrected. Propose `patch_statement`, `replace_text`, or \
  `upsert_statement` with `id` set, and put the OLD TEXT -> NEW TEXT change in \
  the rationale so the reviewer sees exactly what changes.
- CONTRADICTION — the text conflicts with an existing statement. FLAG it, naming \
  BOTH sides, and propose NO automatic resolution. Never silently pick one.

PHRASING
Every statement carries a `kind` selecting the phrasing rules a validator \
enforces; a statement that fails them cannot be applied. Pick the kind first \
from the live vocabulary, then phrase to pass: events are an action with the \
action as subject, present tense, no modal ("an invite is submitted"); states \
are a condition that holds ("auto result sharing is enabled"); capabilities use \
modals ("a reviewer can reopen a closed invite"); rules use must/should/equals/ \
is-one-of; properties name a value slot. Statement text carries NO trailing \
punctuation, no compound clauses, no hedges, no universal quantifiers \
(every/all/each), no conditions baked in — conditions go on the edge as a `when`.

EMIT
Conclude by calling `emit_draft` EXACTLY ONCE with:
- ops — each op uses a real substrate write-tool name as `op` and carries that \
  tool's kwargs as a JSON-object STRING in `payload_json`, with a `rationale` \
  and the existing ids it targets in `targets_existing`;
- ledger — every extracted candidate, its classification, what it was matched \
  against (`matched_against`), and which existing statements you considered \
  linking to (`link_candidates_considered`) with a note;
- flagged — contradictions (both sides named) and anything you scoped out;
- skipped_duplicates — each "candidate :: existing_id".
You do not create the draft and you do not call any write tool. Your job is to \
decide well and to SHOW YOUR RECONCILE WORK."""


_DOCTRINE_HEADER = (
    "\n\n=== REASONING DOCTRINE (the normative guide; follow it) ===\n"
)
_DOCTRINE_FOOTER = "\n=== END DOCTRINE ===\n"


def build_system_prompt(doctrine_text: str | None) -> str:
    """The base harness protocol with the loaded doctrine injected, delimited.

    If `doctrine_text` is missing/empty (unreadable doctrine.md), the base
    protocol still stands on its own.
    """
    doctrine = (doctrine_text or "").strip()
    if not doctrine:
        return _BASE_PROTOCOL
    return _BASE_PROTOCOL + _DOCTRINE_HEADER + doctrine + _DOCTRINE_FOOTER


# --------------------------------------------------------------------------- #
# Vocabulary compaction + initial message
# --------------------------------------------------------------------------- #


def _compact_vocab_rows(rows: Any, key: str) -> list[dict[str, Any]]:
    """Trim live vocabulary rows to the signal: the name, its description, and
    usage count. Drops the bulk (e.g. the long `when`-grammar prose on
    list_link_types' first row, which is in the tool's own description)."""
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = row.get(key)
        if name is None:
            continue
        item: dict[str, Any] = {key: name}
        desc = row.get("description")
        if desc:
            item["description"] = str(desc)[:240]
        when = row.get("when_to_use")
        if when:
            item["when_to_use"] = str(when)[:240]
        direction = row.get("direction")
        if isinstance(direction, dict):
            source = direction.get("source_kinds")
            target = direction.get("target_kinds")
            if isinstance(source, list):
                source_s = "/".join(str(k) for k in source)
            else:
                source_s = "any"
            if isinstance(target, list):
                target_s = "/".join(str(k) for k in target)
            else:
                target_s = "any"
            item["direction"] = f"{source_s} -> {target_s}"
        if "usage_count" in row:
            item["usage_count"] = row["usage_count"]
        out.append(item)
    return out


def format_vocab(vocab: dict[str, Any]) -> str:
    compact = {
        "statement_kinds": _compact_vocab_rows(vocab.get("statement_kinds"), "kind"),
        "link_types": _compact_vocab_rows(vocab.get("link_types"), "link_type"),
        "entity_link_types": _compact_vocab_rows(
            vocab.get("entity_link_types"), "link_type"
        ),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def initial_user_message(text: str, vocab: dict[str, Any]) -> str:
    return (
        "LIVE VOCABULARY (fetched from the substrate just now — pick kinds and "
        "link types from here; reuse before inventing):\n"
        f"{format_vocab(vocab)}\n\n"
        "TEXT TO INGEST:\n"
        "-----\n"
        f"{text}\n"
        "-----\n\n"
        "Extract atomic candidates, reconcile every one against the substrate "
        "with the read tools (discover_facts is the per-candidate primitive), "
        "classify, find adjacent statements to link to, then call emit_draft "
        "exactly once with your ops, the per-candidate ledger, the flagged "
        "contradictions, and the skipped duplicates."
    )


# --------------------------------------------------------------------------- #
# Mid-loop nudges (mirror ask/prompts.py)
# --------------------------------------------------------------------------- #


def floor_block_message(detail: str) -> str:
    """Appended when the floor blocks a premature emit_draft."""
    return (
        "Not yet — you cannot emit before the reconcile floor is met. " + detail + " "
        "Do at least one reconcile read (discover_facts / find_duplicates / "
        "search_statements / survey_statements) AND at least one adjacency search "
        "(search_statements / survey_statements / grep_statements), and make sure "
        "every NEW/REFINEMENT ledger entry has a non-empty matched_against and "
        "either link_candidates_considered or an explicit 'no adjacent statements "
        "found' note. Then call emit_draft again."
    )


#: Appended when the model stops without calling a terminal tool.
NO_TERMINAL_NUDGE = (
    "You stopped without finishing. You still have reconcile work or the emit "
    "left to do. Either call a read tool to continue reconciling, or call "
    "emit_draft now with your ops, the per-candidate ledger, flagged "
    "contradictions, and skipped duplicates."
)


def forced_finalize_message(reason: str) -> str:
    """Appended when a budget cap forces a final emit."""
    return (
        f"Budget reached ({reason}). Call emit_draft NOW with only what you have "
        "reconciled so far. Queue ops only for candidates you actually reconciled; "
        "for any candidate you did not get to, add a ledger entry classified "
        "'unprocessed' with a note. Do not fabricate matches."
    )


def malformed_retry_message(detail: str) -> str:
    """Appended when the emit_draft input failed parsing once."""
    return (
        "Your emit_draft was malformed: " + detail + " "
        "Call emit_draft again. Remember: each op's payload_json must be a STRING "
        "containing a JSON object of that tool's kwargs (not an object), op must "
        "be one of the allowed write-tool names, and the ledger/flagged/"
        "skipped_duplicates arrays must be present."
    )
