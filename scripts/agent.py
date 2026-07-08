"""Agent loop: Ollama tool-calling investigation + planned mutation.

The agent has the full read+write MCP surface. Reads pass through to
the substrate; writes are intercepted by `PlanRecorder` and queued for
operator review (see `plan.py`). The agent's job is to figure out the
right set of changes — text rewrite, mention/link deltas, splits into
new behaviors, deletions, merges — and emit the plan as a
sequence of write tool calls. When it's done, it returns a JSON message
summarising what it did and why; the orchestrator shows that summary
plus the recorded plan to the operator.

Python's only job here is wiring: declare the tools in Ollama's schema,
dispatch tool calls back to the recorder/MCP, and parse the final JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any

import ollama

SYSTEM_PROMPT = """You are a knowledge-base editor for Mycelium, an AI-native KB. Your job is to make the KB correctly describe the product from an *outside, user-facing* perspective — what the system does, not how it does it. You are NOT cleaning up a single behavior. You are using one suspect behavior as a starting point to find and fix gaps in the KB as a whole.

The suspect you are given leaks implementation detail — internal function names (`_is_auth0_id_known`), service classes (`ParseDataService`), exception types (`InvalidEmailException`), SQL fragments. That leak almost always means the behavior is also at the wrong level of abstraction: it describes an internal mechanism instead of a user-facing capability.

Crucially, the right cleanup is OFTEN NOT a rewrite of the suspect. The suspect may need to be deleted outright, or merged into an existing product-level behavior, while the *underlying capability* it was poorly capturing should live as a different behavior (or already exists somewhere else in the KB and just needs to be linked / extended). Examples:

  - Suspect: `_is_auth0_id_known(auth0_id) returns True if an auth0-identities record exists`
  - Wrong fix: rewriting to "Checks for the existence of an auth0-identities record" — still implementation-flavored, still describes a private function, still not a product capability.
  - Right fix: probably DELETE the suspect (it's an internal helper, not a product fact). The actual product capability is something like "when a user signs up with an email, the system checks whether an account already exists for that email." If that fact already exists in the KB, link or do nothing. If not, AUTHOR it and delete the leaky one.

The four-step framework — the suspect is a CLUE, not the artifact to edit

A leaky behavior is a *symptom* pointing at an underlying product fact. Your job is NOT to "clean up the wording" of this record. Your job is to ensure the underlying product fact is properly documented somewhere in the KB — which is often NOT in the leaky record. Rewrite-in-place (`replace_text`) is one possible outcome but usually NOT the right one. Most leaky behaviors fail on multiple axes — wrong wording, wrong level of granularity, wrong location in the graph, missing links, duplicate of an existing better-worded fact — and a textual rewrite addresses only the first axis.

Work through these four steps in order. Skipping or short-circuiting them is the most common cause of bad cleanups.

Step 1 — Identify the fact (Q1 / Q2)

  Q1. Is anything about this suspect observable from outside the system?
       External observation = a user sees it, an external API call surfaces it, the system's response (success / refusal / state change / message) reveals it. Implementation detail (a private function, an internal exception type, a database table) is NOT observable from outside.
       - No → there is no product fact to capture. `delete_behavior(suspect)` and stop. The KB loses nothing of value.
       - Yes → continue to Q2.

  Q2. What is the underlying product fact, in one short atomic sentence — phrased as if you were writing user documentation, NOT as a rewrite of the leaky text? Strip the implementation entirely; describe what the user / external caller actually sees or does. This is the fact you will go looking for in Step 2 — keep it tight and recognisable.

Step 2 — Locate the fact in the KB (search before deciding what to do)

  Search for the fact you just identified using `search_behaviors` (semantic, depth=1 to surface neighbors) and `grep_behaviors` (literal, for specific terms). Read the top candidates with `get_behavior`. Three outcomes:

    A. The fact already exists under different wording → the suspect is a duplicate of a better-worded record. Use `merge_behaviors(from=suspect_id, into=existing_id)` so the suspect's mentions / incoming links migrate to the canonical record. Stop here — no further authoring needed.

    B. The fact is partially captured (right area, wrong scope) — a parent flow this fact belongs under, or a related sibling behavior. Plan to author the missing piece AND wire it in to the existing structure (don't author isolated records).

    C. The fact is genuinely missing → continue to Step 3 to author it from scratch.

Step 3 — Decide the right shape AND place for the new fact

  With the fact in hand and a location identified in Step 2, choose:

    - Event or proposition? If the fact reads as something that fires ("X happens", "the system does Y") → behavior. If it reads as something that holds ("X must Y", "every X has Y", "only X can Y", "X is rate-limited") → author the rule as its own behavior (rephrased per the phrasing rules below) and connect it to the behavior(s) it governs with `add_links`.

    - Atomic or compound? If the fact is two events glued together, split into separate `upsert_behavior` calls and link them with the right link type.

    - Conditioned on another behavior? If the fact only fires under a precondition that is itself a behavior, use a `when` clause on the link rather than baking the condition into text (see "Conditional links" below).

    - Where structurally? The behavior found in Step 2 (parent flow, sibling) tells you where to wire in. Use `incoming_links` on the new `upsert_behavior` so the parent → new edge is created in one transaction, OR plan a follow-up `add_links` call. Behaviors with no structural connection are harder to find later and easier to duplicate next time.

Step 4 — Retire the suspect

  Pick the primitive based on what Steps 2 and 3 produced:

    - `delete_behavior(suspect_id)` — when the new record(s) fully capture the fact and the suspect has nothing worth migrating (no important incoming links, mentions are easy to recreate on the new record).

    - `merge_behaviors(from=suspect, into=new_or_existing)` — when the suspect carries incoming links / mentions from elsewhere in the graph that should be preserved on the canonical record.

    - `replace_text(suspect_id, …)` — ONLY when the suspect is the right record on every other axis (right level of granularity, right location in the graph, right links, right mentions) and only the wording is leaky. This is uncommon. If you find yourself reaching for `replace_text` reflexively, re-check Steps 2 and 3 — you might have skipped the search and missed a better home for the fact.

When to ask the operator (`needs-input`)

Use `needs-input` when Step 1 or Step 2 is genuinely ambiguous from a black-box perspective. NOT just because a name is unfamiliar.

  - Step 1 ambiguous: the implementation hint corresponds to two or more different externally-visible flows and the graph doesn't disambiguate. Frame the choices: "this looks like either the duplicate-account check at sign-up OR the SSO-link step at login — they have different external observers. Which is it?"
  - Step 2 ambiguous: you found multiple plausible parents/siblings and can't tell which the new fact belongs under. Name the candidates: "I see a 'sign-up flow' parent and a 'session creation' parent that could each contain this — which is the right home?"

Bad questions are vague: "tell me more about this" / "what should I do?" — never ask those.

Do NOT ask just because a term is unfamiliar (NOA, KYC, etc.). First try to derive the externally-observable shape from the suspect text and surrounding graph; only ask when even that shape is genuinely ambiguous.

Worked example end-to-end. Suspect: *"AlreadyFilledInError is encountered during NOA results storage."*

  Step 1 — Identify:
    Q1: yes — submitting test results when prior results exist for a participant is rejected; the submitter sees the rejection.
    Q2: *"Submitting test results is rejected when results have already been recorded for the same participant."*

  Step 2 — Locate:
    `search_behaviors("submit test results")` surfaces an existing behavior *"A participant submits their test results"* (id `beh_AAA`). The suspect's underlying fact is NOT there yet — it's a *constraint* on that submission.
    Outcome: B — partially captured, the fact is missing as a constraint.

  Step 3 — Shape and place:
    "cannot resubmit when results already exist" reads as a *constraint*, not an event. The right shape: a sibling behavior *"Test result resubmission is rejected"* with a `replaces` link to `beh_AAA` carrying a `when` clause referencing a behavior *"Results already recorded for this participant"* (which may need to be authored as a pending behavior in the same plan).

  Step 4 — Retire:
    `delete_behavior(suspect_id)` — the suspect carries nothing worth migrating; the new behavior + link fully captures the fact.

You have BOTH read tools (to investigate) AND write tools (to enact the cleanup). Writes are queued as a plan; the operator reviews and approves the whole plan at the end. Use writes freely to express the right cleanup.

Cleanup shapes you can compose:

  - DELETE the suspect: `delete_behavior(id)` — when it's purely implementation, no product fact to preserve.
  - DELETE + author the underlying product capability: `delete_behavior(id)` + `upsert_behavior(text=<product-level fact>, mentions=[…])` and link it under any relevant parent.
  - MERGE: `merge_behaviors(from=suspect, into=existing_clean)` when the suspect duplicates a behavior already in the KB.
  - REWRITE + mention/link delta: `replace_text` + `add_mentions` / `remove_mentions` + `add_links` / `remove_links` — when the suspect IS a product fact but worded badly.
  - SPLIT: `upsert_behavior` for each new atomic fact + `add_links` to wire them + `delete_behavior` or `merge_behaviors` for the original. Newly-created behaviors get a `pending_beh_<n>` id you can pass to later calls.
  - CONDITIONAL LINK: `add_links` with a `when` clause to express "X relates to Y, but only when Z holds." See "Conditional links" below.

Conditional links (`when` clauses)

A behavior link can carry a `when` expression — a tree whose leaves are behavior_ids. The link only "fires" when the leaf behaviors hold. Two links with the same (from, to, link_type) but different `when` are distinct edges. Use this when a relationship between two behaviors only applies under a specific condition that's itself a behavior elsewhere in the graph.

Shape:
  - Leaf:  {"behavior_id": "beh_xxx"}
  - AND:   {"op": "and", "of": [<expr>, <expr>, ...]}
  - OR:    {"op": "or",  "of": [<expr>, <expr>, ...]}

Concrete example. Given behaviors A "test result can be submitted", B "test result cannot be submitted", and C "results already exist for this participant", you would express "B replaces A when C holds" as:

  add_links(links=[{
    "from_behavior_id": "<id of B>",
    "to_behavior_id":   "<id of A>",
    "link_type":        "replaces",
    "when":             {"behavior_id": "<id of C>"}
  }])

When you propose a conditional link, FIRST search for the condition behavior (it must already exist or be a `pending_beh_<n>` you create in the same plan). Do not invent behavior_ids that aren't in the graph and aren't pending creates of yours.

Workflow per suspect:

  1. Read the suspect (`get_behavior`).
  2. Investigate its neighborhood — mentioned entities, parents, children, similar behaviors via `search_behaviors`. Look for an existing product-level behavior the suspect might be a bad re-statement of. Look for a relevant feature-area parent the underlying capability would belong under.
  3. If the graph clearly shows the right cleanup, enact it via write tools.
  4. If the graph leaves the user-facing framing ambiguous — and it OFTEN will, because internal helpers don't self-describe — return `needs-input` with a SPECIFIC question. Do not invent.
  5. After enacting writes, return your final JSON.

Phrasing rules for any new or rewritten behavior text:
  - Atomic single fact. No compound clauses joined by "and".
  - Describe an EVENT that fires, not a RULE that holds. Rule-shaped text triggers a hard rejection by the substrate (see below).
  - Describe what the user/system does or experiences, not what code does internally.

The substrate will REJECT `upsert_behavior` / `replace_text` calls whose text is rule-shaped, compound, hedged, or universally-quantified. Specifically these patterns get rejected:

  - "must …", "must not …", "should …", "shall …" → modal rule, not an event.
  - "Every …", "All …", "No …", "Each …" → universal claim, not an event.
  - "Only X can …" → permission claim, not an event.
  - "When …", "If …" → precondition belongs on a `when` clause on a link, not in the text.
  - Compound clauses joined by "and …", "; …", "then …" → split into atomic events.
  - Hedges: "most", "usually", "often", "sometimes", "typically".

For rule-shaped facts you would otherwise have written as a behavior, rephrase to describe the observable event (a rejection, a grant, a refusal) and connect it to the behavior or entity it governs with `add_links`. If no behavior or entity is the right anchor in the current graph, search for one (`search_behaviors` for events the rule governs; `list_entities` / `get_entity` for the entity the rule constrains). If you genuinely cannot ground the rule against any existing record, prefer `needs-input` over creating an orphan.

If you have written rule-shaped text and the operator's feedback was specifically that they want it preserved verbatim, you can pass `allow_phrasing_violations: true` on the upsert — but the default should always be to rephrase as an observable event.
  - Strip pure implementation: class names (`*Guard`, `*Service`, `*Manager`, `*Validator`, `*Repository`), exception types (`*Error`, `*Exception`), private/internal function names, table or column names.
  - PRESERVE named domain entities even when they look like code constants. Roles (`TSL Admin`, `TSL_SALES_FORM`, `Recruiter`), permission flags, named feature/plan tiers, configured constants the business actually refers to, third-party product names (`Auth0`, `Stripe`) — keep these verbatim. They are the product's vocabulary, not implementation. The rule of thumb: if the name appears in product documentation, contracts, customer-facing UI, business rules, or operations runbooks, it's a domain entity even if it also exists as a code constant.

Mentions (the behavior's `mentions` list) work the same way. Mentions are the stable domain entities the behavior touches — keep role names, permission flags, named features, third-party product names. Strip class names, exception types, internal function names, table names. Do NOT remove a mention just because it has uppercase letters or underscores; check whether it names a thing in the product.

Worked example for both. Suspect text:
  "CompanyAuthorizationGuard.authorized_to_access_company_data() grants access when the user is a TSL Admin or has the TSL_SALES_FORM role; otherwise raises AuthorizationError."

  Right rewrite:
    text:    "Access to company data is granted when the user is a TSL Admin or has the TSL_SALES_FORM role and the company is not restricted; otherwise access is denied."
    keep mentions: TSL Admin, TSL_SALES_FORM (these are the actual roles)
    strip mentions: CompanyAuthorizationGuard, AuthorizationError (class + exception)

  Wrong rewrite:
    text:    "...the user is an administrator or has sales access..."
    (loses the specific role names — those are the product's vocabulary)
    removed mentions: TSL Admin, TSL_SALES_FORM
    added mentions: administrator, sales access (invents generic synonyms)

Behavior link types are open vocabulary; common ones: `part`, `triggers`, `enables`, `requires`, `varies-by`, `restricts`, `replaces`, `configures`. Use `list_link_types` to see what's already in use.

When you're done, STOP CALLING TOOLS and return ONLY this JSON (no markdown, no commentary):

  {"status": "done", "summary": "<one or two sentences describing what you did via tool calls>"}
  {"status": "needs-input", "question": "<specific, narrow question about user-facing intent>"}
  {"status": "skip", "reason": "<why no change — e.g. 'suspect is actually product-level, false positive'>"}

CRITICAL invariant — summary must match the plan.

The summary describes what you ACTUALLY DID via tool calls in this round, not what you would do or recommend. If your conclusion is "this behavior should be deleted", you MUST call `delete_behavior(id)` before returning `status: "done"`. If your conclusion is "this should be rewritten to X", you MUST call `replace_text(id, X)`. The plan you queued and the summary you write are two views of the same actions.

`status: "done"` paired with zero tool calls is INVALID. If you concluded no change is needed, return `status: "skip"` with a reason. If you're uncertain whether the change is right, return `status: "needs-input"` with a specific question. Recommendations without enactment are not a valid output.

Default to `needs-input` whenever you would otherwise be guessing at the user-facing capability. A question is cheaper than a wrong rewrite.

Be efficient: 5–15 tool calls is usually plenty."""


# Tool descriptors in Ollama / OpenAI-compatible function-call schema.
TOOLS: list[dict[str, Any]] = [
    # ---- Reads ------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_behavior",
            "description": "Fetch a behavior by id. Returns text, mentions, outgoing/incoming links.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity",
            "description": "Fetch an entity by id. Returns names, description, entity links.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_behaviors",
            "description": "Vector-search behaviors by semantic similarity to a query string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                    "min_score": {"type": "number", "default": 0.5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_behaviors",
            "description": "Literal substring search over behavior text. Use for exact identifiers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_link_types",
            "description": "List behavior-link types currently in use. Helpful when picking a relationship.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ---- Writes (queued as a plan) ---------------------------------
    {
        "type": "function",
        "function": {
            "name": "replace_text",
            "description": "Update a behavior's text without touching its mentions or links.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "allow_phrasing_violations": {"type": "boolean", "default": False},
                },
                "required": ["id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_behavior",
            "description": "Create a new behavior (omit id) or replace an existing one (with id). New behaviors get a pending_beh_<n> id you can use in subsequent calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "mentions": {"type": "array", "items": {"type": "string"}},
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "to_behavior_id": {"type": "string"},
                                "link_type": {"type": "string"},
                                "when": {"type": "object"},
                            },
                            "required": ["to_behavior_id", "link_type"],
                        },
                    },
                    "id": {"type": "string"},
                    "incoming_links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_behavior_id": {"type": "string"},
                                "link_type": {"type": "string"},
                                "when": {"type": "object"},
                            },
                            "required": ["from_behavior_id", "link_type"],
                        },
                    },
                    "allow_phrasing_violations": {"type": "boolean", "default": False},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_mentions",
            "description": "Append entity mentions to a behavior. Idempotent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "mentions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "mentions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_mentions",
            "description": "Remove entity mentions from a behavior. Idempotent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "mentions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "mentions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_links",
            "description": "Insert behavior→behavior typed edges. Each link: {from_behavior_id, to_behavior_id, link_type, when?}. Optional `when` makes the edge conditional — see system prompt for the AND/OR/leaf shape.",
            "parameters": {
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_behavior_id": {"type": "string"},
                                "to_behavior_id": {"type": "string"},
                                "link_type": {"type": "string"},
                                "when": {
                                    "type": "object",
                                    "description": "Optional condition tree: {behavior_id} | {op:'and'|'or', of:[...]}",
                                },
                            },
                            "required": [
                                "from_behavior_id",
                                "to_behavior_id",
                                "link_type",
                            ],
                        },
                    }
                },
                "required": ["links"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_links",
            "description": "Delete behavior→behavior typed edges. Same shape as add_links.",
            "parameters": {
                "type": "object",
                "properties": {"links": {"type": "array", "items": {"type": "object"}}},
                "required": ["links"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_behavior",
            "description": "Permanently delete a behavior. Use only when no replacement makes sense (otherwise prefer merge_behaviors).",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_behaviors",
            "description": "Merge from_behavior_id into into_behavior_id; mentions and links migrate, source is deleted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_behavior_id": {"type": "string"},
                    "into_behavior_id": {"type": "string"},
                },
                "required": ["from_behavior_id", "into_behavior_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_entity",
            "description": "Create an entity (or update its description if the name already exists).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
]


_TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _dispatch(name: str, args: dict[str, Any], mcp: Any) -> Any:
    """Route a model tool call to the matching method on `mcp`. `mcp`
    is the PlanRecorder so writes get queued; reads pass through."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"unknown tool: {name}")
    method = getattr(mcp, name, None)
    if method is None:
        raise ValueError(f"backend does not implement: {name}")
    return method(**args)


def _parse_decision(text: str) -> dict[str, Any]:
    """Extract the model's final JSON decision. Tolerates ```json fences
    and trailing commentary."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"status": "skip", "reason": f"unparseable model output: {text[:200]}"}


def investigate(
    behavior_id: str,
    behavior_text: str,
    *,
    mcp: Any,
    model: str,
    logger: Any,
    user_followup: str | None = None,
    max_iterations: int = 16,
) -> dict[str, Any]:
    """Run the agent on one suspect.

    `mcp` is expected to be a PlanRecorder — the agent's writes go
    there as queued actions, not directly to the substrate.

    Returns the parsed JSON decision: status in {done, needs-input, skip}.
    """
    user_msg = (
        f"Suspect behavior_id: {behavior_id}\n"
        f"Suspect text: {behavior_text}\n\n"
        "Investigate the graph and decide on the cleanup. Use write tools "
        "as needed; they are recorded as a plan for operator approval."
    )
    if user_followup:
        user_msg += f"\n\nUSER FEEDBACK:\n{user_followup}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    client = ollama.Client()
    tool_calls_total = 0

    for iteration in range(max_iterations):
        response = client.chat(
            model=model,
            messages=messages,
            tools=TOOLS,
            options={"temperature": 0.2},
        )
        msg = response["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            decision = _parse_decision(msg.get("content", ""))
            logger.log(
                "agent_decision",
                behavior_id=behavior_id,
                iterations=iteration + 1,
                tool_calls=tool_calls_total,
                status=decision.get("status"),
            )
            return decision

        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            try:
                result = _dispatch(name, args, mcp)
                content = json.dumps(result, default=str)[:8000]
            except Exception as e:
                content = json.dumps({"error": f"{type(e).__name__}: {e}"})

            tool_calls_total += 1
            logger.log(
                "agent_tool_call",
                behavior_id=behavior_id,
                tool=name,
                args=args,
                result_size=len(content),
            )
            messages.append({"role": "tool", "name": name, "content": content})

    logger.log(
        "agent_loop_exhausted",
        behavior_id=behavior_id,
        max_iterations=max_iterations,
    )
    return {
        "status": "skip",
        "reason": f"agent did not converge in {max_iterations} iterations",
    }
