"""Prompt text and message construction for the inner model.

The system prompt encodes the whole protocol — orient, retrieve (follow links +
semantic adjacency), synthesise — plus the anti-premature-closure discipline.
The floor is enforced structurally in `loop.py`; the prompt teaches the model to
satisfy it naturally so the floor rarely has to fire.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """\
You resolve a question against a knowledge substrate and are HONEST ABOUT \
UNCERTAINTY. The caller is itself an AI consuming your structured output, so \
precision and explicit gaps matter more than fluency.

THE SUBSTRATE
- It holds atomic `statement`s (kinds like event/state/capability/rule/property \
and prescriptive procedure/action/check/cause). Statements carry typed `links` \
to other statements/entities (each `{link_type, to_id, when?}`) and `mentions` \
of named entities.
- You FOLLOW A LINK by calling `get_statements` on the linked `to_id`/`from_id` \
(ids are `stm_...` for statements, `ent_...` for entities). There is no special \
expander — links are followed mechanically, but you decide which to follow.
- The link/kind vocabularies are open and grow. If a link_type or kind is \
unfamiliar, look it up with `list_link_types` / `list_entity_link_types` / \
`list_statement_kinds` rather than guessing its meaning.

YOUR TOOLS
You are given the substrate's read primitives as tools (search_statements, \
survey_statements, get_statements, get_entity, grep_statements, the list_* and \
glossary tools, and more). Use them freely. You finish by calling exactly ONE \
terminal tool: `submit_answer` or `request_clarification`.

THE LOOP
0. RECON has already run: a wide `survey_statements` map of the question is in \
   the first message. Treat it as a starting map, not an answer.
1. ORIENT — grounded in recon, pick exactly one path:
   - clean map -> proceed to retrieve.
   - wrong/misframed premise but still resolvable to ONE strong real referent -> \
     reframe to the question that serves the caller's underlying goal, proceed, \
     and set interpretation.reframed = true with a reason.
   - genuinely ambiguous (two or more plausible distinct referents, or you can't \
     tell which question serves the goal) -> `request_clarification` and STOP. \
     The candidates are real because recon ran; name what each would pull.
2. RETRIEVE — two kinds of move, both yours to initiate:
   - FOLLOW LINKS: from a hydrated statement, call `get_statements` on linked \
     ids to walk the derivation chain.
   - SEMANTIC ADJACENCY: the most relevant statement may have NO edge pointing \
     at it (reachable only via a shared mention/entity or embedding proximity). \
     So you MUST also RE-SEARCH — search_statements / survey_statements seeded by \
     the CONCEPTS YOU HAVE GATHERED SO FAR, not by the original wording — to find \
     what *should* connect but isn't linked. This is the difference between a \
     correct-looking answer and a complete one.
3. SYNTHESISE — call `submit_answer`.

ANTI-PREMATURE-CLOSURE (the failure this tool exists to prevent)
- Before concluding you MUST: enumerate the sub-questions the question contains \
  and mark each resolved / partial / unresolved (the `sub_questions` ledger); \
  and report what your adjacency re-search surfaced in `adjacency_note` (even if \
  "nothing new"). "I followed the links" is NOT sufficient — the missing-but-\
  relevant unlinked statement is the exact gap that matters.
- ABSENCE IS A SIGNAL, NEVER INFERENCE. Zero results on a term means "not found \
  here" -> record it as a gap. Never infer a fact from a naming convention, from \
  what "should" exist, or from your own prior knowledge of similar systems.
- CONTRADICTIONS: if statements conflict, surface BOTH and flag it. Never \
  silently pick one.
- Do NOT fabricate. If the substrate doesn't support a claim, say so and lower \
  confidence.

CONFIDENCE (derive from gaps, do not round up)
- high: derivation chain walked, key terms resolved, no open contradictions.
- medium: supported but with non-trivial gaps / partial coverage.
- low: key terms returned nothing, the question references things absent from \
  the substrate, or you were forced to conclude with the core unresolved.

WRONG-BUT-ANSWERABLE PREMISE: answer what they asked AND, inside `answer`, note \
that a more relevant thing exists and what it is. Withholding is only for genuine \
ambiguity -> `request_clarification`.

Work efficiently: there is a hard cap on total substrate operations. Spend them \
on following the derivation chain and on adjacency re-search, not on repeating \
near-identical queries."""


def _compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Trim a hydrated statement for the recon context — keep the signal
    (id, kind, text, score, link targets, mentioned entities), drop the bulk."""
    links = [
        {"link_type": link.get("link_type"), "to_id": link.get("to_id")}
        for link in hit.get("links", [])
        if isinstance(link, dict)
    ]
    mentions = [m.get("name") for m in hit.get("mentions", []) if isinstance(m, dict)]
    out: dict[str, Any] = {
        "id": hit.get("id"),
        "kind": hit.get("kind"),
        "text": hit.get("text"),
    }
    if "score" in hit:
        out["score"] = round(hit["score"], 4) if isinstance(hit["score"], (int, float)) else hit["score"]
    if links:
        out["links"] = links
    if mentions:
        out["mentions"] = mentions
    return out


def format_recon(recon: Any) -> str:
    hits = recon if isinstance(recon, list) else []
    compact = [_compact_hit(h) for h in hits if isinstance(h, dict)]
    if not compact:
        return "(recon returned no statements — the question's terms may be absent from the substrate)"
    return json.dumps(compact, ensure_ascii=False, indent=2)


#: Closing directive for the `quick` depth (floor off). Replaces the standard
#: "re-search for adjacency before you conclude" instruction so the model stops
#: as soon as it can answer, instead of dutifully doing the thorough dance.
QUICK_CLOSING = (
    "QUICK MODE — a latency-boxed caller needs a fast, direct answer. For THIS "
    "call this instruction overrides the anti-premature-closure protocol above: "
    "the concept-seeded adjacency re-search is NOT required and the loop will not "
    "block your answer for it. Orient on recon, do at most one or two targeted "
    "retrievals to confirm the key facts, then submit_answer. Skip the adjacency "
    "re-search unless recon left the core genuinely unresolved; if you skip it, "
    "put 'skipped — quick mode' in adjacency_note. Stay honest: mark real gaps "
    "and do not round up confidence."
)

#: Standard closing directive (floor on): push the thorough retrieve + re-search.
STANDARD_CLOSING = (
    "Orient on this, then retrieve (follow links AND re-search by gathered "
    "concepts for semantic adjacency) before you conclude."
)


def initial_user_message(question: str, recon: Any, *, quick: bool = False) -> str:
    return (
        f"QUESTION: {question}\n\n"
        f"RECON (survey_statements of the question — a wide starting map, not an answer):\n"
        f"{format_recon(recon)}\n\n"
        f"{QUICK_CLOSING if quick else STANDARD_CLOSING}"
    )


#: Appended when the floor blocks a premature submit_answer.
def floor_block_message(detail: str) -> str:
    return (
        "Not yet — you cannot conclude before the floor is met. " + detail + " "
        "Do at least one more targeted retrieval and one concept-seeded "
        "adjacency re-search (search_statements / survey_statements on the "
        "concepts you've gathered), then submit with a filled adjacency_note."
    )


#: Appended when the model stops without calling a terminal tool.
NO_TERMINAL_NUDGE = (
    "You stopped without finishing. Call exactly one terminal tool now: "
    "submit_answer (with the sub_questions ledger and adjacency_note filled) or "
    "request_clarification."
)


def forced_finalize_message(reason: str) -> str:
    return (
        f"Budget reached ({reason}). Submit your answer NOW with submit_answer "
        "using only what you have gathered. Mark every unresolved sub-question in "
        "the ledger and in gaps, and lower confidence accordingly — do not round up."
    )


#: Appended when the submitted answer failed schema/validation once.
def malformed_retry_message(detail: str) -> str:
    return (
        "Your submit_answer was malformed: " + detail + " "
        "Call submit_answer again with every required field correctly typed."
    )
