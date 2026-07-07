---
name: mycelium-authoring
description: How to write knowledge into the mycelium substrate. Covers the authoring workflow, the action-layer depth to document at, picking a statement `kind` (event/state/capability/rule/property), atomicity, per-kind phrasing, and linking statements as METHOD (direction discipline, triggers-vs-contains, conditions via `when`, when to ask) — link-type meanings are NOT listed here; they live in `list_link_types()` / `list_entity_link_types()`. Use this whenever calling upsert_statement, upsert_statements, upsert_entity, upsert_name, add_links, remove_links, add_entity_links, remove_entity_links, merge_statements, delete_statement, merge_entities, or move_name — even for a one-line change.

This skill defers two things to live tools on purpose: link-type definitions and the exact `when` grammar come from `list_link_types()` / `list_entity_link_types()`, and phrasing word-lists come from the validator's rejection messages. Always call those tools at author time rather than relying on memory or on the few type names this skill happens to mention — the live vocabulary is larger and grows; the names here are illustrations of method, not the menu.
---

# Mycelium Authoring

A **statement** is the substrate's unit of meaning — one atomic claim about the product. Every statement carries a `kind` declaring the *shape* of the claim. **The kinds and their definitions live in `upsert_statement`'s documentation — read them there; this skill does not duplicate them**, for the same reason it doesn't list link types: one source, no drift, current across every client. The starting vocabulary is `event`, `state`, `capability`, `rule`, and `property`; it is open — add a kind when none fits.

This skill covers the part the tool's definitions can't — **how to choose the right kind and dodge the traps**: valid state vs. derived condition (§4a), valid property vs. state (§4c), cross-kind redundancy (§4b), phrasing routing (§5), and the rule/state distinction (`references/rule-kind.md`).

Pick the kind first, write the text second — the kind selects the phrasing rules the validator enforces (§5). **Statement text carries no trailing punctuation.**

**One statement = one atomic claim** (§4). The vocabulary is open and decisions have no undo — so two disciplines run through everything below: **tell the operator before you mutate**, and **the code is authoritative, the substrate is not**.

---

## 1. Document at the action layer — the thing that matters most

Mycelium captures product behaviour **one level above code**: the discrete actions the product performs and the conditions that hold, named so they **survive a reimplementation** (§3). Below that line is code mechanics; above it is a vague summary. Aim for the middle and you get a graph that actually explains how the product behaves.

**Decompose every distinct action into its own statement, and wire them in execution order.** The order is part of the record, not incidental.

**A domain decomposes along two axes, and both produce walkable chains.** *Flows* — actions in time — decompose into ordered events and states (`proceeds`, `contains`, `establishes`, `triggers`). *Derivations* — computed values — decompose into intermediate values and the rules that produce them (`valued-by`, `composes`, `cases`). A config/scoring domain is mostly the second axis: it has few actions and many values + rules. The action-only instinct enumerates the knobs and leaves the computation itself as one opaque node — see §1e.

The dominant failure mode is **under-decomposition**: collapsing a sequence of distinct actions — or the stages of a computation — into one coarse statement, which silently deletes steps the substrate should hold. Resist it.

### 1a. Linear sequences still decompose

A flow with no branching is still multiple statements. *"The candidate is routed to Auth0 signup"* and *"an Auth0 signup callback is received"* are two distinct actions in sequence — two statements joined by an ordering link, **not** one merged "signup happens" event. The get-or-create, the channel pick, the route, the callback — each is a node even when nothing forks around it.

This inverts the instinct to summarise. When a method runs A then B then C and each is a recognisable product action, that is **three** statements in order, not one.

### 1b. What to keep shallow

Collapse a step into its parent **only** when it is genuinely indivisible at the product level, or is invisible plumbing with no product-observable consequence: logging, metrics, cache invalidation, encryption, retry/Celery scheduling, ORM/DB write mechanics, framework idioms. These could be swapped wholesale without changing what the product does — skip them.

### 1c. The depth test

For each candidate step, in order:

1. Would someone who knows the product, asking *"what does it do here, and in what order?"*, expect this step named? → **statement.**
2. Does it change ordering, branch the flow, or produce a distinct outcome? → **statement.**
3. Is it invisible internal mechanism with no product-visible name or consequence? → **skip.**
4. **Unsure → decompose.** Depth is mandatory; over-splitting one action is cheap and reversible, losing a step is neither.

### 1d. A complete domain answers all of these

Depth without coverage is still a best-case-scenario record. Before declaring a domain done, the substrate must answer:

- **What can happen?** Every outcome from every entry point — success, failure, fallback, silent drop.
- **What causes each outcome?** The guards, conditions, and config states that select the branch.
- **What prevents the main outcome?** Rejections, guard clauses, idempotency returns, validation failures.
- **What happens on absent or invalid input?** Every input has a fallback default, a silent suppression, or an explicit rejection — one must be true.
- **What fires asynchronously?** Webhook callbacks, delivery-failure handlers, retry exhaustion — these re-enter the state space from outside and belong to the story.
- **Does it read as one connected graph?** Pick the domain's central object and try to *walk* it — entry point, through intermediates, to a terminal or a leaf rule. If every path is one hop (leaf → hub → dead end), the domain is a star, not a story: the mechanism the domain exists to explain is hiding inside an undecomposed node. Many statements converging on one node by the same link type — especially `configures` or `governed-by` — is the tell. This is the §1 under-decomposition signal applied to *links*: too-complex-to-walk means too-little-decomposed.

A substrate full of valid happy-path events with no failure, fallback, or async branches is **under-documented even when every statement is correct**. So is a flat star of correct statements with no walkable chain through it.

### 1e. Derivations decompose like flows

A computed value is **not** one node `valued-by` one rule. It is a chain: the final value `valued-by` its master rule, that rule `composes` the stage rules, and each stage's intermediate value is its own `state`/`property` `valued-by` its own rule. A consumer walks value → rule → input-value → rule up the pipeline — the same progressive disclosure a flow gives through `proceeds`/`contains`.

The §1c depth test applies verbatim, one word swapped: *would someone asking "how is this computed, in what order?" expect this stage named?* → statement. A weighting step, a summation, a threshold cut, a penalty — each is a node, not a clause buried inside one master rule's text.

The trap is the **opaque computation hub**: a `capability` (*"X can be computed"*) with config knobs `configures`-ing into it and no master rule beneath it. The knobs are easy — they are config structs — but the mechanism they configure was never decomposed, so there is nothing to attach them *to* except the hub. The fix is the missing trunk: author the master rule the capability is `governed-by`, decompose it into stages, then attach each knob to the **stage it governs**, not to the capability.

**The worked shape is in `references/rule-kind.md`** (capability →`governed-by`→ master rule →`composes`→ stage rules →`cases`→ branches). Read it whenever a domain computes a value — *including config/scoring domains*, which are exactly this shape even though they don't announce themselves as "deterministic computation" up front.

---

## 2. Topology before drafting

Drafting paragraph-by-paragraph produces rework — shared targets, branches, and sub-steps only become visible after wrong shapes get rejected. For each entry point, **write out the outcomes first** (don't keep them mental): success path, failure/rejection, fallback/silent drop, conditional sub-paths, async handlers. Then map the structural elements:

- **Shared states** — conditions multiple paths reach. Author once; link from each path. Don't duplicate per path.
- **Branches** — fork points. Each branch is its own statement; the fork condition is its own `state`, attached via `when` (§6).
- **Sub-steps** — work *within* a parent → `contains` children, not `triggers` targets (§6).
- **Capabilities** — what an actor is *allowed* to do, regardless of whether it is happening now.

---

## 3. Frame from the product's outside

A statement records what the *product* does or is true of — not how code implements it. Two layers belong in the substrate:

- **Externally-observable claims** — anything a user, API caller, or integration sees. Includes the integration surface: emitted/accepted webhooks, rejection of a bad webhook, OAuth callbacks, signed-URL redirects, IP allowlists. The test isn't *"is this fancy UX?"* — it's *"does an external observer see this happen, succeed, or fail?"*
- **Product-internal claims** — named pieces of the product's own process or shape that exist regardless of implementation (*"the extraction agent runs"*, *"a participant record holds a name and email"*).

**The refactor test:** imagine the codebase rewritten in another language. *"Embeddings are generated"* survives → write it. *"The `OllamaEmbedder` is constructed"* vanishes → skip it. Strip `*Service`/`*Manager`/`*Handler`/`*Error`, function names, table/column names from text and `mentions`. **Preserve named domain entities verbatim** — roles (`TSL Admin`), plan tiers, third-party products (`Auth0`, `Stripe`) — anything that appears in product docs, contracts, UI, or business rules.

| Code mechanic (don't) | Product claim (do) |
|---|---|
| *"`validateInvite()` rejects emails missing `@`"* | *"An invite is rejected when the email is malformed"* (event) |
| *"The `participants` table has columns id, name, status"* | *"A participant record holds a name, an email, and a status"* (state) |
| *"`WebhookController` calls `verifyHmac()`"* | *"An incoming webhook is rejected when its HMAC signature is invalid"* (event) |

---

## 4. Atomicity — strict on order, pragmatic on phrasing

One statement records exactly one claim. Split when you see: `and`/`;`/`then` joining actions; an event fused with the state it produces (*"is set to"*, *"becomes"*, *"transitions to"*); an action mixed with a permission rule; a subject change mid-sentence; two finite verbs for distinct actions.

**Strip inputs and requirements from statement text.** *"An invite is created"* — not *"…by submitting a name and email."* Dense text closes off the connections that tell the rejection story. Model requirements as states + rejection events, or as `property` records the statement `requires`/`accepts` (§4c, `references/patterns.md`).

### Pragmatic carve-out (this is deliberate, not sloppy)

**Depth and order beat text purity.** Two cases are tolerated rather than fought:

- **Single conceptual actions English phrases compoundly** — *"a user record is retrieved by matching contact details, or created when no match is found"* (get-or-create). One action, one node.
- **Low-value inline guards** that would cost more to reify than they're worth.

When decomposing one of these would burn time for little graph value, **write the fused text and pass `allow_phrasing_violations=True`**. Move on.

**The carve-out does NOT cover separately-orderable actions.** *"A is created and a notification is sent"* are two actions with an order between them — splitting them is the whole point of §1. Fusing those destroys the ordering the substrate exists to capture. The tolerance is for *one* action awkwardly phrased, never for *two* actions hidden in one sentence.

### 4a. Valid state

Genuinely persisting, observable conditions of a named entity: **enum/status values** (`Sent`, `Shared`), **config flags** (`Auto result sharing enabled`), **observable conditions at a decision point** (`No name on the invite`). **Not** states: derived/computed conditions (model the event that produces them instead), internal mechanism steps (have the upstream event `establishes` the state directly — §5), single-use gating conditions (consider a `when` expression over existing states instead of a new record).

### 4b. Cross-kind redundancy

Changing a statement's `kind` does not create new information. Before writing, apply the **structural necessity test**: does this statement have a concrete graph role nothing existing can fill — source/target of a story-bearing link, a `when` leaf, or the root of a rule tree? If not — if it merely restates an existing claim in modal (`capability`), nominal (`state`), or passive form — it is an idle echo. Drop it.

### 4c. Valid property

A *value slot* where the meaningful question is *what value*, not *does this hold*. Valid: user-supplied config/inputs (*"Email"*, *"Vacancy ID"*), derived values (*"Match score"*, authored with `valued-by → rule` and no input source). **Not** properties: binary conditions (those are `state`), enum *cases* (one property; legal values come from a `rule` via `valued-by`), the computation itself (that's the `rule`). Anchor a property to its entity by listing the entity in `mentions` — there is no `belongs-to` link. The full inputs-as-properties pattern is in `references/patterns.md`.

---

## 5. Kinds & phrasing — route, don't memorise

The validator checks text against the chosen `kind` and **rejects with a reason** (`compound`, `hidden_event_state`, `precondition_in_text`, `universal_claim`, `hedge`, rule-shaped, property-shaped, …). The validator is the source of truth for the exact word-lists — this skill does not reproduce them. When a statement is rejected, **route the fix**:

- **Wrong kind for the wording** → change the `kind` (don't bypass). If you reached for `can`/`may`, it's a `capability`, not a `state`. If you wrote a bare number or *"is a …"* on an `event`, it's almost always a `state`.
- **Condition in the text** (`when`/`if`/`before`/`after`/`unless`, sentence-initial *or* mid-sentence) → reify the condition as a `state` and attach it via `when` on the link (§6).
- **Compound** → split into atomic statements and link them.
- **Hidden event+state** (*"is set to"*, *"becomes"*) → split into one `event` + one `state`. Link with `establishes`. **Internal-mechanism exception:** when the state change is the direct automatic consequence of a well-understood upstream event, skip the intermediate "setting" event entirely and have the upstream event `establishes` the state directly.
- **Hedge** → drop it, or lift the exception out as its own statement.
- **Universal** (`every`/`all`/`each` — yes, `each` too) → rephrase singular. (`No` is allowed.)

`allow_phrasing_violations=True` bypasses the check — use it for verbatim quotes/contract clauses and the §4 carve-out, not to dodge a real split.

Rule phrasing (`equals`, `is one of`, `is bounded`) is independent and does **not** trip the event/state/capability checks. The rule/state distinction is the easiest place to go wrong → `references/rule-kind.md`.

---

## 6. Linking — method, not vocabulary

**Always call `list_link_types()` (statement↔statement) and `list_entity_link_types()` (entity↔entity) before choosing a link — every session, not only when unsure.** They return the full, current vocabulary, each type with its canonical meaning and direction. **That returned list is your menu. The few type names mentioned in this skill and its references are illustrations of the method below — not the set to choose from.** The live set is larger than anything this skill names and grows over time; picking only from names you happen to remember from here caps you to a fraction of the vocabulary and pushes you to invent duplicates of types that already exist. So: fetch the list, choose the existing type that fits, and invent a new one only when nothing returned does. This section teaches how to choose well; the tool supplies what to choose from.

### Chain-forming vs attachment links — reach for the chain

The vocabulary splits in two, and the split decides whether the graph is walkable. **Chain-forming** links thread one statement into the next so a consumer can traverse a path: `proceeds`, `contains`, `establishes`, `triggers`, `composes`, `valued-by`, `cases`, `fallback-to`. **Attachment** links pin a fact to another without extending a path: `configures`, `governed-by`, `varies-by`, `requires`, `restricts`. (Confirm membership against `list_link_types()` — the set grows; this is the method, not the menu.)

Both are correct in their place, but the default instinct over-reaches for attachment because it is easy: a config value "configures the thing," a capability "is governed by a rule," and you stop. The result is a star — every fact one hop from a hub, no path longer than two. Before settling on an attachment link, ask: **is there an intermediate this should thread through instead?** A knob usually `configures` a *specific stage* of a decomposed mechanism, not the abstract capability; if the only thing to attach it to is a hub, the mechanism is under-decomposed (§1e), and the fix is to build the chain, not to add another spoke.

`configures` is a smell in bulk — its own glossary entry says use it sparingly, `contains` is often cleaner. Several `configures` edges into one node almost always means a missing trunk.

**Hard rule — a `configures` (or `governed-by`) edge may not terminate on a bare capability.** A `capability` is *"X can be done"*; it is not a mechanism, so there is nothing concrete for a knob to parameterise on it. Pointing config at it is what produces the star. Before proposing any such edge, **name the stage node it actually targets** — the master rule, or one of its `composes` stages (§1e). If that node doesn't exist yet, you have two honest options: **author it** (go read the computation/scoring code and decompose the mechanism the capability stands for), or **scope it out explicitly** — leave the edge unproposed and note in the draft which future draft will decompose that mechanism. What you may not do is terminate the edge on the capability and move on; a knob attached to a capability is never the answer. The one tolerated case is when the capability genuinely *is* the unit being parameterised and no value-bearing mechanism exists beneath it (rare — verify against code before claiming it).

### Direction — the single most common mistake

Links are **top-down**. Read every edge as **"this record —[type]→ target"**. The **source** is the bigger / earlier / wrapping / primary claim; the **target** is the smaller / later / contained / dependent one.

**Flip test:** if the edge reads naturally as *"target [type] this record"* (*"X is part of Y"*, *"X is triggered by Y"*), you have it backwards — the link belongs on the other statement. A few types read against intuition (e.g. priority/precedence chains, prerequisite links); when direction isn't obvious, **read the type's description from `list_link_types()`** rather than guessing — it states the direction.

### `triggers` vs `contains` — the most-conflated pair

The cheap test: would the target still make sense as a standalone statement — own children, own downstream — if you deleted the parent? **Yes → `triggers`** (separate downstream process). **No → `contains`** (sub-step inherent to the parent). A notification queued after invite creation is `triggers`; default-flow application *within* invite creation is `contains`.

### Conditions on edges — `when`

An edge holds unconditionally by default. When it only fires under a precondition, **reify the precondition as its own statement** (usually `state`) and attach it as a `when` expression on the link — **never bake a condition into statement text** (§5). The expression is a small AND/OR/NOT tree over statement-id leaves; **read the full grammar from `list_link_types()`** (it has gained operators — do not assume from memory what it supports).

**Conjunctive conditions never collapse into one compound state.** *"First step is a Checklist"* AND *"channel is WhatsApp"* are two separate states ANDed in the `when`, not one fused state — otherwise *"which flows are Checklist-first?"* becomes unanswerable. Model a shared condition once and reference it from every edge that needs it.

### Which tool, and isolation

- **statement↔statement** and **entity↔statement** edges → `add_links` (`{from_id, to_id, link_type, when?}`; routed by id prefix).
- **entity↔entity** structural edges → `add_entity_links` (separate vocabulary, no `when`).

A statement with **no** incoming and **no** outgoing links is almost always wrong — either unwired or shouldn't exist. The one exception: a `state` used only as a `when` leaf is intentionally link-free; do **not** add `enables` to "fix" it.

### When to stop and ask

If you can't tell whether two statements should link, which type fits, or whether the product even has that relationship — **ask the operator with the candidates named** (*"should A `contains` B, or do they sequence?"*). Wrong links propagate: every consumer then reads the relationship through the wrong frame.

---

## 7. Recurring shapes

These are combinations of the rules above, not special primitives. Recognising them up front saves rework. Full worked examples → `references/patterns.md`.

- **Base + specifics** — one abstract base statement `contains` the specific thresholds/cases. Reach for it on *"depends on…"* / *"falls into one of these buckets."*
- **Derivation chain** — a computed value decomposes into intermediate values + their rules, walkable via `valued-by`/`composes`/`cases`; never one *"X can be computed"* hub with knobs hanging off it (§1e, `references/rule-kind.md`).
- **Validation / rejection** — submission event stays minimal; missing/invalid inputs are `state`s wired as `when` on the rejection edge; happy path is unconditional.
- **Config + effect** — a config value is a `state` that `configures` the **specific** `event`/stage it changes, not an abstract capability hub; authoring the knob without the effect leaves an uninterpretable orphan, and attaching every knob to one hub leaves a star (§1e, §6).
- **Inputs as properties** — user-supplied fields are `property` records the event `requires`/`accepts`, never packed into event text, never authored as states.
- **Same surface, distinct code paths** — two paths that look like the same event but differ in guards are **separate statements**; merging them and attaching guards mislabels which path each guard restricts.
- **Temporal / provider variation is structural** — reify the date/provider condition and use `replaces`/`restricts`, don't bury it in text.

---

## 8. Workflow

- **Tell before doing.** Present exact texts, kinds, links, mentions, and rationale; wait for approval before any mutation. No undo, no audit log.
- **Verify against code.** The substrate may hold records authored from wrong assumptions. Read the implementation; if substrate and code disagree, the code wins and the substrate gets fixed.
- **Mark uncertainty inline.** `> 💡 likely correct: [inference + source]` / `> ⚠️ needs verification: [what's unclear]`. Anything unmarked is a claim you can defend.
- **Discover before writing — the substrate does not dedup.** Bulk: `discover_facts(texts=[…])` (`exists ≥0.85` → don't duplicate; `near 0.6–0.85` → link instead). Single: `search_statements(query, min_score=0.7)` for the claim *and* for each entity you'll mention; `grep_statements` for exact identifiers. **Pre-create entities** with a one-line description via `upsert_entity` before mentioning them — auto-create on first mention leaves an empty, undiscoverable description.
- **Audit links after each chunk.** Walk the new ids, inspect `links` and `incoming_links`, wire orphans in or reconsider them. Orphans cluster when the writer focused on text and forgot direction; catching them at chunk boundaries is far cheaper than ten chunks later. **Also walk the chain:** from the chunk's entry point, can you traverse through the new statements to a terminal, or did everything attach to one hub? A flat fan that passes the orphan check still fails §1d.
- **Batch (`upsert_statements`).** Define dependencies (conditions, sub-statements) at **lower** indices than the parents that reference them via `@N`, so rejections cascade upward predictably. Cascade rejection is automatic and transitive. **Mirror pairs** (Low/Medium/High, above/below) score ~0.99 against each other — that's expected; do **not** merge them. Merge only exact-same-claim duplicates.

---

## Pre-write checklist

**Completeness (before writing anything):** outcomes enumerated for every entry point — success, failure, fallback, conditional, async — and every entry point reaches a terminal (§1d, §2). The domain's central object walks as a chain, not a star (§1d, §1e).

**Per statement:**

1. **Decomposed to the action *and* derivation layer?** Distinct actions are separate statements wired in order (`proceeds`/`contains`); computation stages are separate statements wired in derivation order (`valued-by`/`composes`/`cases`); nothing collapsed except indivisible actions and invisible plumbing (§1, §1e).
2. **Framed from outside?** Survives the refactor test; no class/function/table names; domain entities preserved (§3).
3. **Atomic — or a justified carve-out?** One claim, or one get-or-create/inline-guard with `allow_phrasing_violations`; never two orderable actions fused (§4).
4. **Inputs as properties, real states as states?** (§4a, §4c)
5. **Right `kind`, phrasing routed not bypassed?** (§5)
6. **No redundant echo?** Passes the structural-necessity test (§4b).
7. **No conditions in text?** Reified as `when` (§6).
8. **Links: consulted `list_link_types()`, direction checked, `triggers`-vs-`contains` tested, chain-forming preferred over attachment where an intermediate exists, uncertain ones asked?** (§6)
9. **Connected — and walkable?** Every statement has a link in or out (or is a deliberate `when`-leaf state), *and* the domain's central object walks as a chain, not a star — no opaque hub with N same-type spokes (§1d, §1e, §6). Chunk got its link audit (§6, §8).
10. **Operator approved?** No mutation has run (§8).
