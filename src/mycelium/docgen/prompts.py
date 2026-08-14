"""Prompt text and message construction for the docgen inner model.

Three layers stack into one system prompt, in widening specificity:

1. the base harness protocol below — what this loop is, what its tools do,
   and what it will refuse;
2. the DOCTRINE — how to run a generation loop, loaded by `loop.py` from the
   `(doctrine, docgen)` row;
3. the GUIDELINE SET — how to write this particular document: the set-wide
   `guidance` and `exposure` rows, then the template row for the resolved
   document type.

They are delimited so the model can tell them apart, because they can
disagree. A guideline set is written for whoever holds it, which has
historically been an agent with a filesystem and a person to ask; the
doctrine and this protocol say what a *loop* does with the same instructions.
The base protocol resolves the conflicts it can predict (there is no file to
save, no caller to ask) so the doctrine does not have to restate the set.

The resolution turn has its own, much smaller, prompt: it precedes the
guideline texts because it is what chooses them.
"""

from __future__ import annotations

import json
from typing import Any

from ..ask.prompts import format_recon

__all__ = [
    "build_system_prompt",
    "initial_user_message",
    "resolution_message",
    "resolution_retry_message",
    "emit_block_message",
    "malformed_retry_message",
    "forced_finalize_message",
    "format_recon",
    "NO_TERMINAL_NUDGE",
]

_BASE_PROTOCOL = """\
You write ONE document about a topic, from a knowledge substrate, and you are \
HONEST ABOUT WHAT THE SUBSTRATE DOES NOT HOLD. What you write is stored as it \
stands and served to readers. A reviewer that has not seen your reasoning will \
check the finished document against this set's exposure rules and template and \
may return it once, but cannot check facts without your run's reads. Nothing \
downstream will notice a sentence you could not source; substrate discipline \
is yours alone.

THE SUBSTRATE
- It holds atomic `statement`s (kinds like event/state/capability/rule/property \
and prescriptive procedure/action/check/cause). Statements carry typed `links` \
to other statements/entities (each `{link_type, to_id, when?}`) and `mentions` \
of named entities. Statement ids are `stm_...`; entity ids are `ent_...`.
- You FOLLOW A LINK by calling `get_statements` on the linked id. There is no \
expander — links are followed mechanically, but you decide which to follow.
- The link/kind vocabularies are open and grow. If a link_type or kind is \
unfamiliar, look it up with `list_link_types` / `list_entity_link_types` / \
`list_statement_kinds` rather than guessing what it means.
- The substrate is the ONLY source of product fact available to you. Your own \
prior knowledge of how systems like this usually work is not evidence and \
never reaches the page.

YOUR TOOLS
The substrate's read primitives (search_statements, survey_statements, \
get_statements, get_entity, grep_statements, discover_facts, the list_* and \
glossary tools, and more) — use them freely. Plus `report_knowledge_gap`, for \
filing what the substrate could not supply. You have NO write tool: nothing \
you do can change the substrate, and the document does not become substrate \
truth. You finish by calling exactly ONE terminal tool: `emit_document`.

THE FLOW YOU DRIVE (one context)
1. MAP the topic. A wide `survey_statements` of the request has already run \
   and is in the first message — treat it as a starting map, not as material.
2. GATHER. Follow the links out of what the map found, hydrate the ids, and \
   RE-SEARCH on the concepts you have gathered rather than on the request's \
   original wording — the statement a section needs often has no edge \
   pointing at it and is reachable only by embedding proximity or a shared \
   entity. Keep gathering until each section of the template has statements \
   behind it, or until you have established that it does not.
3. WRITE the document against the template, section by section, from what you \
   gathered.
4. EMIT once, with the statement ids the body rests on.

WHAT THE HARNESS WILL REFUSE
- An `emit_document` with no `statement_ids`. A document that rests on nothing \
  is not recorded.
- An `emit_document` citing an id this run never retrieved. Cite what you \
  actually read; if you want to cite something the map only mentioned, \
  `get_statements` it first.
- A blank title or a blank body.
These are checked before anything is stored, and you will be asked again.

WHEN THE SUBSTRATE FALLS SHORT
The template will ask for things the substrate does not hold. That is the \
normal case, not a failure, and it has exactly one correct response: call \
`report_knowledge_gap` with what was missing and what you searched, then \
either leave the section out or mark it in the body as unverified. Absence is \
a finding. Do NOT fill the hole from your own knowledge, do NOT infer a fact \
from a name or a naming convention, and do NOT round a "probably" into a \
statement of behaviour. A short document of sourced facts plus filed gaps is \
a success; a complete-looking document with three invented sentences is the \
one failure this loop exists to prevent.

WHAT THE GUIDELINE SET CANNOT ASK OF YOU
The guideline set below may be phrased for an author with a checkout and a \
person to talk to. You are neither. Where it says to save a file to a path, \
ignore that — you emit the body and the harness stores it. Where it says to \
ask the caller, you cannot: decide, and record the uncertainty in the body \
and in your gaps. Where it says to run a command or validate links against a \
repository, you have no such tool — hand the point back as a gap rather than \
claiming it holds. Everything else in it — structure, tone, frontmatter, what \
each section is for, the quality bar — is binding.

Work efficiently: there is a hard cap on total operations. Spend them on \
following the chain and on concept-seeded re-search, not on repeating \
near-identical queries."""


_DOCTRINE_HEADER = "\n\n=== GENERATION DOCTRINE (how to run this loop; follow it) ===\n"
_DOCTRINE_FOOTER = "\n=== END DOCTRINE ===\n"


def _guideline_block(
    guideline_set: str,
    document_type: str,
    guidance: str | None,
    exposure: str | None,
    template: str | None,
) -> str:
    parts = [
        f"\n\n=== GUIDELINE SET `{guideline_set}` (how to write this document) ===\n"
    ]
    if guidance:
        parts.append(f"--- {guideline_set}/guidance ---\n{guidance.strip()}\n")
    else:
        parts.append(
            f"--- {guideline_set}/guidance ---\n(this set has no set-wide "
            "guidance row; follow the template and this protocol)\n"
        )
    if exposure:
        parts.append(f"\n--- {guideline_set}/exposure ---\n{exposure.strip()}\n")
    else:
        parts.append(
            f"\n--- {guideline_set}/exposure ---\n(this set states no exposure rules)\n"
        )
    parts.append(
        f"\n--- {guideline_set}/{document_type} (the template you are "
        f"filling) ---\n{(template or '').strip()}\n"
    )
    parts.append("=== END GUIDELINE SET ===\n")
    return "".join(parts)


def build_system_prompt(
    doctrine_text: str | None,
    *,
    guideline_set: str,
    document_type: str,
    guidance: str | None,
    exposure: str | None,
    template: str | None,
) -> str:
    """The base protocol, the loaded doctrine, then the guideline set — each
    delimited so the model can tell which is which when they disagree.

    A missing doctrine drops its block; the protocol stands on its own.
    """
    doctrine = (doctrine_text or "").strip()
    out = _BASE_PROTOCOL
    if doctrine:
        out += _DOCTRINE_HEADER + doctrine + _DOCTRINE_FOOTER
    return out + _guideline_block(
        guideline_set, document_type, guidance, exposure, template
    )


# --------------------------------------------------------------------------- #
# Resolution turn
# --------------------------------------------------------------------------- #


def resolution_message(
    prompt: str,
    catalogue: dict[str, list[str]],
    *,
    requested_set: str | None,
    requested_type: str | None,
) -> str:
    """The one-shot message that decides which set and type to write against.

    The catalogue is passed as data rather than described in prose, because it
    is whatever the store currently holds — the message is regenerated per run
    and a set added as config appears in it without anyone editing this file.
    """
    fixed = []
    if requested_set:
        fixed.append(f"The request already names the guideline set: {requested_set}.")
    if requested_type:
        fixed.append(f"The request already names the document type: {requested_type}.")
    return (
        "Choose what this documentation request should be written against.\n\n"
        "REQUEST:\n-----\n"
        f"{prompt}\n"
        "-----\n\n"
        "CONFIGURED GUIDELINE SETS (set -> the document types it has a "
        "template for):\n"
        f"{json.dumps(catalogue, ensure_ascii=False, indent=2)}\n\n"
        + (" ".join(fixed) + " Keep it.\n\n" if fixed else "")
        + "Pick the document type by what the reader of the finished document "
        "will want: to walk through a first success, to accomplish a task, to "
        "look a value up, to understand why something works, or to fix a "
        "problem they are hitting. Then call choose_guideline_set once. The "
        "document type must be one the set you chose actually lists above."
    )


def resolution_retry_message(chosen_set: str, chosen_type: str, available: list) -> str:
    return (
        f"'{chosen_type}' is not a document type '{chosen_set}' has a template "
        f"for. That set can write: {sorted(available)}. Call "
        "choose_guideline_set again with a pair that appears together in the "
        "listing."
    )


# --------------------------------------------------------------------------- #
# The writing loop
# --------------------------------------------------------------------------- #


def initial_user_message(
    prompt: str,
    recon: Any,
    *,
    guideline_set: str,
    document_type: str,
) -> str:
    return (
        f"DOCUMENTATION REQUEST:\n-----\n{prompt}\n-----\n\n"
        f"You are writing a `{document_type}` against the `{guideline_set}` "
        "guideline set, whose guidance, exposure rules, and template are in "
        "your system prompt.\n\n"
        "RECON (survey_statements of the request — a wide starting map, not "
        "material to write from):\n"
        f"{format_recon(recon)}\n\n"
        "Gather from here: follow the links out of what looks relevant, "
        "hydrate the ids you intend to cite, and re-search on the concepts "
        "you gather rather than on the request's wording. File a "
        "report_knowledge_gap for anything the template needs and the "
        "substrate does not hold. Then call emit_document once."
    )


def emit_block_message(detail: str) -> str:
    """Appended when the harness refuses an emit and wants another."""
    return (
        "Not recorded — " + detail + " Fix it and call emit_document again. "
        "If the substrate genuinely does not support this document, report "
        "the gap and emit only what you can source."
    )


#: Appended when the model stops without calling a terminal tool.
NO_TERMINAL_NUDGE = (
    "You stopped without finishing. You still have gathering or the emit left "
    "to do. Either call a read tool to continue, or call emit_document now "
    "with the title, the body, and the statement ids it rests on."
)


def forced_finalize_message(reason: str) -> str:
    """Appended when a budget cap forces a final emit."""
    return (
        f"Budget reached ({reason}). Call emit_document NOW with what you can "
        "source from what you have already read. Write only the sections your "
        "gathered statements support, list every one of those statement ids, "
        "and put what you did not get to in gaps. Do not pad the document to "
        "look complete."
    )


def malformed_retry_message(detail: str) -> str:
    """Appended when the emit_document input failed parsing once."""
    return (
        "Your emit_document was malformed: " + detail + " Call it again with "
        "title and body as strings and statement_ids as an array of strings."
    )
