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
guideline texts because it is what chooses them. The reviewer also has its
own prompt, containing only its protocol, the exposure rules when present,
and the resolved template; writer instructions and history do not cross that
boundary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import timestamps
from ..ask.prompts import format_recon
from . import flows as flow_drawing
from .schema import FlowDefinition, RefusedDraft, ReviewFinding, StoredFlow

if TYPE_CHECKING:
    from ..audiences import Audience
    from ..media import Offer
    from .reads import ConceptContext, ExistingPage
    from .trace import ReviewNote

__all__ = [
    "build_system_prompt",
    "build_review_system_prompt",
    "initial_user_message",
    "review_message",
    "review_retry_message",
    "resolution_message",
    "resolution_retry_message",
    "emit_block_message",
    "malformed_retry_message",
    "forced_finalize_message",
    "format_recon",
    "format_anchor",
    "Anchor",
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
The substrate's read primitives (search_statements, \
get_statements, get_entity, list_statements, grep_statements, discover_facts, \
and the vocabulary lookups above) — use them freely. `preview_flow` shows the \
steps that follow from one statement, read from its links; the statements it \
returns count as read. Plus `report_knowledge_gap`, for \
filing what the substrate could not supply. You have NO write tool: nothing \
you do can change the substrate, and the document does not become substrate \
truth. You finish by calling exactly ONE terminal tool: `emit_document`.

THE FLOW YOU DRIVE (one context)
1. MAP the topic. A wide decomposed `search_statements` of the request has already run \
   and is in the first message — treat it as a starting map, not as material. \
   When the request names the concept the document is about, the first \
   message also carries that concept and every statement that mentions it: \
   that is where coverage starts.
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
- A title or body using this harness's vocabulary: the word "substrate", a \
statement or entity id, or a tool name. The reader never sees any of them; \
say what is not known in the reader's terms ("this is not documented yet"), \
and let the cited ids travel beside the document.
- Media placed other than as `![alt text](media:med_...)`, an image with \
  empty alt text, or a media id no read offered you.
- A flow whose start or stop does not exist or this audience may not see, a \
  flow that draws fewer than three statements, a placement naming no flow in \
  `flows`, a flow in `flows` the body never places, and a flow name that is \
  malformed or used twice. An image placeholder whose description has fewer \
  than three words. All of them come back in one refusal.
These are checked before anything is stored, and you will be asked again.

CONCEPT LINKS AND FLOWS
Both are optional. Link a concept the reader may want to open as `[[Name]]`, \
or `[[Name|text shown]]` where the sentence needs other words, using a name \
the knowledge base gives that concept. A link that matches no concept is not \
refused: it reads as its text. To show something that happens in steps, \
`preview_flow` it, then hand it over in `flows` as `{name, title, start, \
stop}` and place it in the body with a fenced block whose info string is \
`flow` and whose only content is the name. The server draws it from the \
stored links, so the body carries no statement ids. Choose `start` and `stop` \
so the drawing stays readable: start where the process the text describes \
begins, and stop it where the text stops.

MEDIA
A read result may end with AVAILABLE MEDIA: screenshots and recordings \
attached to the statements or concept it returned, already cleared for this \
document's audience, each with an id, alt text and caption. You cannot see \
them; the alt text says what they show. Place one where it shows a screen or \
step the text describes, as `![alt text](media:med_...)` on its own line; the \
server turns the reference into the image. Alt text says what the image shows \
for a reader who cannot see it. A template may mark an image slot as \
`{Image: what it should show}`: fill it with an offered item that shows that, \
or leave the slot out. Never describe a screenshot you were not offered, and \
leave out media that does not fit the text.

IMAGE PLACEHOLDERS
Where seeing a screen would help the reader and no offered media shows it, \
mark the place with `![what the picture should show](image-wanted)` on its \
own line. Describe the screen and the state it is in, in at least three \
words; a person adds the picture later. It is not media and needs no id.

WHEN THE SUBSTRATE FALLS SHORT
The template will ask for things the substrate does not hold. That is the \
normal case, not a failure, and it has exactly one correct response: call \
`report_knowledge_gap` with what was missing and what you searched, then \
either leave the section, table column or field out (or blank) or mark it in \
the body as unverified. Absence is \
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


DEFAULT_REVIEW_INSTRUCTIONS = """Every finding names WHERE — a section heading or a quoted phrase — and WHAT \
failed. A finding the writer cannot locate cannot be fixed. Fail only on \
something you can point at; unease is not a finding.

THE FINDINGS LIST IS NOT A NOTEPAD. Anything you put in it rejects this \
document, whatever status you set alongside it: findings are the evidence and \
the label is not, so a check carrying findings fails. Write a finding ONLY for \
something that must change. Never record what you examined and accepted, why a \
borderline case is acceptable, or that a check turned up nothing — a line \
saying "this passes" or "no finding on this point" throws the document away as \
surely as a real defect does.

A check with nothing to fix reports zero findings. Passing a document you have \
doubts about is a decision; padding the findings list to look diligent sends a \
correct document back for no reason and spends the run's one retry."""


_REVIEW_PROTOCOL = """\
You are reviewing ONE finished document that another context wrote. You did \
not write it, and you are deliberately not being shown how it was produced: \
an agent that produced something believes it works, and that belief is not \
evidence.

{checks}

You are NOT fact-checking, and you cannot: you do not have the run's reads. \
The statements the document cites are shown to you so you can see what \
material the document was standing on when it revealed something, and \
whether a required section is populated or padded — not so you can verify \
the product's behaviour. Do not fail a claim for being unfamiliar. EXPOSURE \
judges the document's title and body only; the cited statements are evidence, \
not part of the document.

The writer may state only what the cited statements support, and was told to \
leave out, leave blank or mark as unverified any section, table column or \
field the knowledge base cannot fill, and to file a knowledge gap for it. Such \
an omission conforms to the template. Fail CONFORMANCE for the shape of the \
document type, for a placeholder left in, or for structure the cited \
statements could have filled; never for material the statements do not hold.

The reader never sees the knowledge base behind the document. Fail EXPOSURE, \
or CONFORMANCE when there is no exposure check, for text that talks about it: \
"substrate", statements, statement or entity ids, tool names, or what the \
knowledge base holds, where the reader needs only the product.
Images appear in the body as `![alt text](media:med_...)`, and PLACED MEDIA \
says what each shows; you cannot see the pixels. Fail CONFORMANCE for an image \
whose alt text does not say what it shows, or one that, by its alt text and \
caption, does not show what the surrounding text describes. Fail EXPOSURE for \
an image whose alt text or caption reveals what this audience must not get. \
Leaving an image slot empty conforms.
`[[Name]]` and `[[Name|text]]` link a concept, and a fenced block with the \
info string `flow` holding one name places a flow the server draws. Both are \
permitted body syntax, not placeholders left in. PLACED FLOWS says what each \
placed flow shows: the reader sees its caption, steps, conditions, outcomes \
and what it says continues, so the exposure check covers them as it covers \
the body. Fail CONFORMANCE for a flow that does not show what the \
surrounding text describes.
`![what the picture should show](image-wanted)` marks where a picture would \
help. It is permitted body syntax: not media, and not a placeholder left in. \
Fail CONFORMANCE for one only when its description does not say what to show.

{instructions}

Call `record_review` exactly once."""


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


def _audience_block(audience: Audience) -> str:
    return (
        f"\n\n=== AUDIENCE `{audience.name}` ({audience.scope}) ===\n"
        f"{audience.description.strip()}\n"
        "Only knowledge this audience may see is available: the read tools "
        "return nothing else, and a document citing anything else is refused. "
        "Write at the depth, and in the tone, this description asks for.\n"
        "=== END AUDIENCE ===\n"
    )


def build_system_prompt(
    doctrine_text: str | None,
    *,
    guideline_set: str,
    document_type: str,
    guidance: str | None,
    exposure: str | None,
    template: str | None,
    audience: Audience | None = None,
) -> str:
    """The base protocol, the loaded doctrine, then the guideline set — each
    delimited so the model can tell which is which when they disagree.

    A missing doctrine drops its block; the protocol stands on its own.
    """
    doctrine = (doctrine_text or "").strip()
    out = _BASE_PROTOCOL
    if doctrine:
        out += _DOCTRINE_HEADER + doctrine + _DOCTRINE_FOOTER
    out += _guideline_block(guideline_set, document_type, guidance, exposure, template)
    return out + _audience_block(audience) if audience is not None else out


def build_review_system_prompt(
    *,
    instructions: str = DEFAULT_REVIEW_INSTRUCTIONS,
    guideline_set: str,
    document_type: str,
    exposure: str | None,
    template: str | None,
    audience: Audience | None = None,
) -> str:
    """The independent review protocol and only the rules it judges.

    The writer's protocol, generation doctrine and set-wide guidance are
    deliberately absent: they describe producing a document, while this
    context only judges the finished one.
    """
    exposure_text = (exposure or "").strip()
    if exposure_text or audience is not None:
        checks = (
            "Run TWO checks and report them separately, because they fail "
            "differently. EXPOSURE: does the text respect what this guideline "
            "set may reveal? The rules are below. CONFORMANCE: does it match "
            "the template below and the content expectations of "
            f"{_article(document_type)} `{document_type}`?"
        )
    else:
        checks = (
            "Run the CONFORMANCE check: does the document match the template "
            "below and the content expectations of "
            f"{_article(document_type)} `{document_type}`? Report that check "
            "separately."
        )
    parts = [_REVIEW_PROTOCOL.format(checks=checks, instructions=instructions)]
    if audience is not None:
        parts.append(
            f"\n\n=== AUDIENCE `{audience.name}` ({audience.scope}) ===\n"
            f"{audience.description.strip()}\n"
            "EXPOSURE also fails when the document gives this audience "
            "something the description says it must not get.\n"
            "=== END AUDIENCE ===\n"
        )
    if exposure_text:
        parts.append(
            f"\n\n=== `{guideline_set}` EXPOSURE RULES ===\n"
            f"{exposure_text}\n"
            "=== END EXPOSURE RULES ===\n"
        )
    parts.append(
        f"\n\n=== `{guideline_set}/{document_type}` TEMPLATE ===\n"
        f"{(template or '').strip()}\n"
        "=== END TEMPLATE ===\n"
    )
    return "".join(parts)


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


@dataclass(frozen=True)
class Anchor:
    """The concept a document is about, as the harness read it."""

    entity_id: str
    names: list[str]
    description: str
    statements: list[dict[str, Any]]
    #: How many statements mention it, of which `statements` is the first page.
    total: int
    #: None when the run's reader cannot supply it.
    context: ConceptContext | None = None
    #: Documents of this profile about the concepts in `context`.
    pages: Sequence[ExistingPage] = ()


def _article(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def _concept_lines(context: ConceptContext) -> list[str]:
    def quoted(name: str, entity_id: str) -> str:
        return f"{json.dumps(name, ensure_ascii=False)} ({entity_id})"

    lines: list[str] = []
    if context.related:
        lines.append("\nRELATED CONCEPTS (its direct concept links):")
        lines.extend(
            f"- this concept {link.link_type} {quoted(link.name, link.entity_id)}"
            if link.direction == "outgoing"
            else f"- {quoted(link.name, link.entity_id)} {link.link_type} this concept"
            for link in context.related
        )
    if context.more_specific:
        lines.append(
            "\nMORE SPECIFIC CONCEPTS (it contains them, or they are a kind of "
            "it; with how many statements mention each):"
        )
        lines.extend(
            f"- {quoted(concept.name, concept.entity_id)}: {concept.statements}"
            for concept in context.more_specific
        )
    if context.named_together:
        lines.append(
            "\nOFTEN NAMED TOGETHER (concepts most often named in the same "
            "statements, with how many statements name both):"
        )
        lines.extend(
            f"- {quoted(concept.name, concept.entity_id)}: {concept.statements}"
            for concept in context.named_together
        )
    return lines


def format_anchor(anchor: Anchor) -> str:
    name = anchor.names[0] if anchor.names else anchor.entity_id
    lines = [
        f"THE DOCUMENT IS ABOUT ONE CONCEPT: {json.dumps(name, ensure_ascii=False)} "
        f"({anchor.entity_id}). Write about this concept; the request says what to "
        "say about it."
    ]
    if len(anchor.names) > 1:
        lines.append("Also called: " + ", ".join(anchor.names[1:]))
    lines.append(
        f"{json.dumps(name, ensure_ascii=False)} is its preferred name. Call "
        "every concept by its preferred name throughout, which is the name "
        "this message gives it. Do not list this concept's other names: the "
        "page shows them."
    )
    if anchor.description.strip():
        lines.append("Description: " + anchor.description.strip())
    if anchor.context is not None:
        lines.extend(_concept_lines(anchor.context))
    if anchor.pages:
        lines.append(
            "\nPAGES THAT EXIST (documents this profile already holds about "
            "the concepts above, each with its title and how it opens). Link "
            "to a page with its concept's name instead of repeating what it "
            "covers:"
        )
        lines.extend(
            f"- {json.dumps(page.name, ensure_ascii=False)}: "
            f"{json.dumps(page.title, ensure_ascii=False)}"
            + (f" — {page.lead}" if page.lead else "")
            for page in anchor.pages
        )
    lines.append(
        f"\nSTATEMENTS THAT MENTION IT ({len(anchor.statements)} of {anchor.total}; "
        "already retrieved, so you may cite them directly):"
    )
    lines.extend(
        f"- {row.get('id')} [{row.get('kind')}] {row.get('text')}"
        for row in anchor.statements
    )
    if anchor.total > len(anchor.statements):
        lines.append(
            f"(The other {anchor.total - len(anchor.statements)} are reachable "
            f"with list_statements(entity_id={anchor.entity_id!r}, "
            f"offset={len(anchor.statements)}).)"
        )
    if anchor.context is not None and anchor.context.flow_starts:
        lines.append(
            "\nWHERE FLOWS START (statements about it that begin a chain of "
            "steps, largest first, with how many statements the drawing from "
            "there holds; preview_flow(start=<id>) shows it):"
        )
        lines.extend(
            f"- {start.statement_id} [{start.kind}] {start.text} "
            f"({start.size} statements)"
            for start in anchor.context.flow_starts
        )
    lines.append(
        "\nCOVERAGE STARTS HERE. Each statement above is about the concept, so "
        "each belongs in the document unless it is off-topic for what the "
        "request asks or the template asks for a summary; leave one out "
        "deliberately, never by not getting to it. "
        "Then follow their links and search for what is about the concept "
        "without naming it."
    )
    return "\n".join(lines)


def initial_user_message(
    prompt: str,
    recon: Any,
    *,
    guideline_set: str,
    document_type: str,
    anchor: Anchor | None = None,
    current_document: str | None = None,
    current_flows: Sequence[StoredFlow] = (),
    current_statement_ids: Sequence[str] = (),
    review_notes: Sequence[ReviewNote] = (),
    refused_draft: RefusedDraft | None = None,
) -> str:
    revision = (
        "\n\nCURRENT DOCUMENT TO REVISE (verbatim):"
        "\n=== CURRENT DOCUMENT ===\n"
        f"{current_document}\n=== END CURRENT DOCUMENT ==="
        + submitted_flows(current_flows)
        + cited_statements(current_statement_ids)
        if current_document is not None
        else ""
    )
    notes = (
        "NOTES FROM THE REVIEW THAT REFUSED AN EARLIER ATTEMPT (for you only; "
        "the next review does not see them). Address each where it holds; the "
        "guidance, template and statements win where a note contradicts them:\n"
        + "\n".join(
            f"- {note['check']}: {note['where']} — {note['problem']}"
            for note in review_notes
        )
        + "\n\n"
        if review_notes
        else ""
    )
    if refused_draft is not None:
        notes += (
            "THE DOCUMENT THAT ATTEMPT SUBMITTED. Revise this text instead of "
            "starting over: keep what the notes do not touch and fix what they "
            "name. Read a statement before citing it, and submit every flow "
            "the body still places.\n"
            + document_payload(title=refused_draft.title, body=refused_draft.body)
            + _flows_text("ITS FLOWS", refused_draft.flows, refused_draft.flows)
            + "\n\n"
        )
    return (
        f"DOCUMENTATION REQUEST:\n-----\n{prompt}\n-----\n\n"
        + notes
        + f"Today is {timestamps.now()[:10]}.\n"
        f"You are writing {_article(document_type)} `{document_type}` "
        f"against the `{guideline_set}` guideline set, whose guidance, exposure "
        "rules, and template are in your system prompt.\n\n"
        + (format_anchor(anchor) + "\n\n" if anchor is not None else "")
        + "RECON (decomposed search_statements of the request — a wide starting map, not "
        "material to write from):\n"
        f"{format_recon(recon)}\n\n"
        "Gather from here: follow the links out of what looks relevant, "
        "hydrate the ids you intend to cite, and re-search on the concepts "
        "you gather rather than on the request's wording."
        + revision
        + "\n\nFile a report_knowledge_gap for anything the template needs and the "
        "substrate does not hold. Then call emit_document once."
    )


def _flow_block(flow: StoredFlow, *, with_ids: bool) -> str:
    lines = flow_drawing.flow_lines(flow.drawing, with_ids=with_ids)
    return "\n".join(f"  {line}" for line in lines)


def cited_statements(statement_ids: Sequence[str]) -> str:
    """The statements a document cited, for a writer about to submit it
    again, who would otherwise have to find them a second time."""
    if not statement_ids:
        return ""
    return (
        "\n\nSTATEMENTS IT CITED (ids). Read the ones you still rest on with "
        "get_statements before citing them again, and cite others where the "
        "text changes:\n" + ", ".join(statement_ids)
    )


def submitted_flows(flows: Sequence[StoredFlow]) -> str:
    """The flows a document places, for a writer about to submit it again:
    each one's definition and its drawing, with statement ids."""
    if not flows:
        return ""
    return (
        "\n\nCURRENT FLOWS (the flows this document places, each with its "
        "definition and the drawing stored for it). The `flows` you submit "
        "replace this set: submit again every flow the body still places, and "
        "leave out one whose placement you removed.\n"
        + "\n".join(
            "- "
            + json.dumps(
                flow.model_dump(include={"name", "title", "start", "stop"}),
                ensure_ascii=False,
            )
            + "\n"
            + _flow_block(flow, with_ids=True)
            for flow in flows
        )
    )


def _flows_text(
    heading: str,
    definitions: Sequence[FlowDefinition],
    drawn: Sequence[StoredFlow],
) -> str:
    """Submitted flows as text: each definition, and its drawing with
    statement ids where one was made."""
    if not definitions:
        return ""
    drawings = {flow.name: flow for flow in drawn}
    return (
        f"\n\n{heading} (each with its definition and, where it was drawn, "
        "its drawing):\n"
        + "\n".join(
            "- "
            + json.dumps(
                definition.model_dump(include={"name", "title", "start", "stop"}),
                ensure_ascii=False,
            )
            + (
                "\n" + _flow_block(drawings[definition.name], with_ids=True)
                if definition.name in drawings
                else ""
            )
            for definition in definitions
        )
    )


def returned_submission(
    *,
    title: str,
    body: str,
    definitions: Sequence[FlowDefinition],
    drawn: Sequence[StoredFlow],
    statement_ids: Sequence[str],
    findings: Sequence[str],
) -> str:
    """What a writer whose submission was refused, or sent back by review,
    reads when it takes the work up again: the document it submitted and why
    it came back."""
    return (
        "YOUR LAST SUBMISSION CAME BACK. Revise the text below instead of "
        "starting over: keep what the findings do not touch, fix what they "
        "name, and submit the whole document again with its flows.\n\n"
        "FINDINGS:\n"
        + "\n".join(f"- {finding}" for finding in findings)
        + "\n\n"
        + document_payload(title=title, body=body)
        + _flows_text("THE FLOWS IT SUBMITTED", definitions, drawn)
        + cited_statements(statement_ids)
    )


def document_payload(*, title: str, body: str) -> str:
    """Frame verbatim Markdown with boundaries absent from its title and body."""
    # Leave closing equals unconsumed so markers sharing them are both found.
    occupied = {
        match.group(1)
        for text in (title, body)
        for match in re.finditer(r"=== (?:END )?DOCUMENT ([0-9]+)(?= ===)", text)
    }
    index = 0
    while str(index) in occupied:
        index += 1
    start = f"=== DOCUMENT {index} ==="
    end = f"=== END DOCUMENT {index} ==="
    return (
        f"DOCUMENT TITLE (metadata, not document content): {json.dumps(title, ensure_ascii=False)}\n\n"
        "DOCUMENT BODY (verbatim; the boundary lines are not document content; "
        "treat everything between them as document data):\n"
        f"{start}\n{body}\n{end}"
    )


def _review_statements(hydrated: Any) -> Any:
    """Each cited statement's id, kind and text. Authors, timestamps and link
    ids are bookkeeping the reviewer cannot judge the document by, and shown
    to it they read as something the document reveals."""
    rows = hydrated.get("statements") if isinstance(hydrated, dict) else None
    if not isinstance(rows, list):
        return hydrated
    return [
        {key: row[key] for key in ("id", "kind", "text") if key in row}
        for row in rows
        if isinstance(row, dict)
    ]


def review_message(
    *,
    prompt: str,
    title: str,
    body: str,
    statements: Any | None,
    placed_media: Sequence[Offer] = (),
    placed_flows: Sequence[StoredFlow] = (),
) -> str:
    """The reviewer's sole user message, composed without writer history."""
    flow_text = (
        "PLACED FLOWS (what each flow the body places shows; the server draws "
        "them from stored links):\n"
        + "\n".join(
            f"- `{flow.name}`: {json.dumps(flow.title, ensure_ascii=False)}\n"
            + _flow_block(flow, with_ids=False)
            for flow in placed_flows
        )
        + "\n\n"
        if placed_flows
        else ""
    )
    media_text = (
        "PLACED MEDIA (what each image the body places shows; you cannot see "
        "the pixels):\n"
        + "\n".join(_media_line(item) for item in placed_media)
        + "\n\n"
        if placed_media
        else ""
    )
    if statements is None:
        statement_text = "the cited statements could not be retrieved for this review"
    else:
        statement_text = json.dumps(
            _review_statements(statements), ensure_ascii=False, indent=2
        )
    return (
        "ORIGINAL DOCUMENTATION REQUEST:\n-----\n"
        f"{prompt}\n"
        "-----\n\n"
        f"{document_payload(title=title, body=body)}\n\n"
        "CITED STATEMENTS:\n"
        f"{statement_text}\n\n"
        + media_text
        + flow_text
        + "Review only this finished document against the checks in your system "
        "prompt, then call record_review once."
    )


def _media_line(item: Offer) -> str:
    caption = (
        f" Caption: {json.dumps(item.caption, ensure_ascii=False)}"
        if item.caption
        else ""
    )
    return (
        f"- `{item.id}` ({item.content_type}). Alt text: "
        f"{json.dumps(item.alt_text, ensure_ascii=False)}.{caption}"
    )


def media_offer_note(offers: Sequence[Offer]) -> str:
    """Appended to a read: media attached to what it returned that this
    document's audience may see."""
    lines = "\n".join(
        _media_line(item) + f" Attached to {', '.join(item.attached_to)}."
        for item in offers
    )
    return (
        "\n\nAVAILABLE MEDIA (screenshots and recordings attached to what you "
        "just read, cleared for this audience). Place one where it shows a step "
        "or screen the text describes, as ![what it shows](media:<id>), using "
        "or adapting its alt text:\n" + lines
    )


def review_retry_message(
    *,
    prompt: str,
    title: str,
    body: str,
    exposure_findings: list[ReviewFinding],
    conformance_findings: list[ReviewFinding],
    flows: Sequence[StoredFlow] = (),
    statement_ids: Sequence[str] = (),
) -> str:
    """The rejected document and findings for the fresh writer context."""
    groups = []
    if exposure_findings:
        groups.append(
            "EXPOSURE FINDINGS:\n"
            + "\n".join(
                f"- {finding.where} — {finding.problem}"
                for finding in exposure_findings
            )
        )
    if conformance_findings:
        groups.append(
            "CONFORMANCE FINDINGS:\n"
            + "\n".join(
                f"- {finding.where} — {finding.problem}"
                for finding in conformance_findings
            )
        )
    findings = "\n\n".join(groups)
    return (
        "A reviewer checked this document and sent it back. This is a NEW "
        "context: neither you nor the reviewer has the conversation in which "
        "the document was written.\n\n"
        "ORIGINAL DOCUMENTATION REQUEST:\n-----\n"
        f"{prompt}\n"
        "-----\n\n"
        f"{document_payload(title=title, body=body)}"
        f"{submitted_flows(flows)}"
        f"{cited_statements(statement_ids)}\n\n"
        f"REVIEW FINDINGS:\n{findings}\n\n"
        "This is the ONE further attempt. A second rejection ends the run "
        "with nothing recorded. Revise the document above instead of starting "
        "over: keep what the findings do not touch and fix what they name. "
        "You may read more from the "
        "substrate if a finding needs material you do not have. The same "
        "grounding rule applies: every statement_ids entry must be one THIS "
        "RUN retrieved, including anything read before the rejection. Then "
        "call emit_document once."
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
