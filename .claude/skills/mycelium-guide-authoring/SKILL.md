---
name: mycelium-guide-authoring
description: How to write **prescriptive** content into the mycelium substrate — UI procedures (how to configure X, how to set up Y) and diagnostic content (what could be wrong, how to verify, how to resolve). Self-contained for the prescriptive layer. Covers the four prescriptive kinds (`procedure`, `action`, `check`, `cause`), the procedure-as-root pattern (named guide root anchored to a `capability` via `teaches`, composing `property` inputs via `requires` / `accepts` and `action` chains via `contains` / `next`), anchoring action/check/cause to the descriptive layer via `performs` / `verifies` / `violates`, lookup procedures hanging off properties via `obtained-by`, sequencing with `next` / `on-success` / `on-failure`, within-layer links (`confirms` / `refutes` / `resolves`), procedure-to-procedure gating via `when` on a descriptive state, conditional edges via `when`, the procedure shape (linear with branches), the diagnostic shape (cause-driven, branching), phrasing conventions for objective step text, the rule that "Identify X" / "Decide Y" / "Determine Z" are property tells not actions, common patterns (login troubleshooting, MCP connection setup), the prescriptive↔descriptive boundary, plus the shared workflow conventions (tell-before-doing, discovery, batching with `@N` ordering, handling near-duplicates). Use whenever authoring how-to or troubleshooting content, or when calling mycelium write tools (`upsert_statement`, `upsert_statements`, `add_links`, etc.) for prescriptive content (`kind` set to `procedure`, `action`, `check`, or `cause`). For **descriptive** content (event/state/capability/rule/property), use `mycelium-authoring` instead — do not load both.
---

# Mycelium Guide Authoring

The substrate carries two layers:

- **Descriptive** — what the product does, is, and allows (`event`, `state`, `capability`, `rule`, `property`).
- **Prescriptive** — what a *user* should do, what a *diagnostic agent* should check, and what could be wrong. This skill.

The prescriptive layer is only useful when anchored to the descriptive layer. A procedure is meaningful because it teaches a capability the product exposes. A check is meaningful because the state it verifies is required by a capability. An action is meaningful because the event it performs produces a state the user needs. A cause is meaningful because it names a way a required state can fail to hold.

Four prescriptive kinds:

- **`procedure`** — the named root of a how-to guide. *"How to connect an MCP client to a Mycelium server."* Anchors via `teaches` to a `capability`. Composes its body via `contains` / `next` (to `action`s), `requires` / `accepts` (to `property`s the user supplies), and terminates in a final action (send/submit/save) or a `check` that confirms success.
- **`action`** — a step the user performs. *"Click the Save button."* Anchors via `performs` to an `event` statement (the thing that actually happens in the system when the user does this).
- **`check`** — a verification step for a diagnostic agent. *"Verify the user's authentication provider matches the login method attempted."* Anchors via `verifies` to a `state` statement (the condition being inspected).
- **`cause`** — a named failure mode worth investigating. *"User is attempting password login on a social-only account."* Optionally anchors via `violates` to a `state` (when the failure mode is "a required state isn't met"). Free-standing when the failure is environmental, historical, referential, or compound.

**Configurable values the user supplies are not prescriptive.** They live in the descriptive layer as `property` records (`belongs-to` their entity, `valued-by` a rule for format/value-space). The procedure references them through `requires` (mandatory in this guide) or `accepts` (optional in this guide). They are *not* pseudo-actions — see §3.

Pick the kind first, write the text second. **Statement text carries no trailing punctuation** — no period, question mark, or exclamation. Statements are labels in a graph. **One statement = one atomic claim** — compound clauses destroy the substrate's ability to link related knowledge.

## 0. Workflow conventions

These apply to every authoring session, not a specific section. They're load-bearing.

- **Tell before doing — always.** Present the exact statement texts, `kind`s, link types, mentions, and rationale; wait for operator approval before any mutation. Even one-line changes. The substrate has no undo and no audit log.
- **Verify against the actual product, not memory.** A check or action describing a screen, field, or button that doesn't exist (or works differently than described) is worse than no documentation — a diagnostic agent following it will get stuck or send users somewhere wrong. When unsure, open the product and confirm.
- **The descriptive layer is the authority for what the product does.** When writing an action that performs an event *in the modeled product*, the underlying event must already be modeled (or be modeled as part of the same authoring chunk). Don't author prescriptive content over descriptive gaps — flag the gap and pause until it's filled. Dangling anchors are tolerable; *imagined* anchors are not. **Exception:** actions in third-party UIs have no event in the modeled product to anchor to — leave the anchor absent without flagging (§4).
- **State uncertainty explicitly, never bury it.** Use markers inline so the operator can spot what to verify:
  - `> 💡 likely correct: [inference + source].`
  - `> ⚠️ needs verification: [what's unclear and why].`

  Anything without a marker is a claim you can defend from what you read.
- **Check existing records before creating.** `get_statements(ids)` for known ids; `search_statements` + `grep_statements` for the claim you're about to write. The substrate does not dedup — silent duplicates accumulate.
- **Audit links after each chunk.** Newly authored statements are frequently isolated. Before declaring a chunk done, walk the most important new records and inspect both `links` and `incoming_links`. Wire orphans in or reconsider whether they should exist.

## 1. Model the topology before drafting

Two distinct shapes show up; sketch which one you're in before writing.

### Procedure shape (UI / configuration)

A named root (`procedure`) composing user-supplied inputs (`property`) and a chain of UI steps (`action`). Used for *"how to configure X"*, *"how to set up Y"*.

Sketch:

- **Procedure root** — one `procedure` statement names what the user accomplishes (*"How to connect an MCP client to a Mycelium server"*). Anchors to the `capability` it teaches via `teaches`. Every guide has exactly one root.
- **Properties** — the configurable values the user supplies. Each is one `property` record on the descriptive side (`belongs-to` its entity, `valued-by` its value-space rule when applicable). The procedure links to them via `requires` (mandatory) or `accepts` (optional). When a property has a non-trivial lookup ("open Settings → Users & invites and create a service account"), that lookup is itself an `action` or sub-`procedure`, hung off the property via `obtained-by`.
- **Entry point** — what state must the user be in to start? (Logged in as an admin, on a specific settings page, with a prerequisite procedure already completed.) Each prerequisite is a `state` reference (descriptive layer), attached via `when` on the first action's incoming edge if it's a hard gate. **Procedure-to-procedure ordering:** if Guide 1 must complete before Guide 2 can start, gate Guide 2's first action via `when` on the descriptive state Guide 1 establishes. There is no procedure→procedure link type — the existing `when` machinery covers it.
- **Linear actions** — the happy-path UI sequence. Each is one `action` statement; the procedure `contains` them (or chains them via `next`). Only real UI interactions belong here: clicks, navigations, entries, copies, sends.
- **Branches** — when a step has variants. Reify the condition as a state, branch with `on-success` / `on-failure`, or with two `next` edges each carrying a mutually exclusive `when`.
- **Terminal step** — the procedure ends with a final action (send/submit/save) or a `check` confirming success. The terminal *state* (what's true after completion) is descriptive — `establishes`-ed by the final action's event.

**Mental verbs are property tells, not actions.** When you find yourself writing an action like *"Identify the role to grant"*, *"Decide which server to connect to"*, *"Determine the service account name"* — stop. These aren't UI interactions; they describe the user *choosing a value*. The value is a `property` the procedure `requires` or `accepts`. If finding the value involves real UI steps, those go on the property as `obtained-by → action` (or a sub-`procedure`); if the user just types it in, no `obtained-by` is needed.

### Diagnostic shape (troubleshooting)

Tree of `cause` statements with `check` verifications and `action` resolutions. Used for *"why isn't X working"*, *"what could go wrong with Y"*.

Sketch:

- **Entry capability** — the descriptive `capability` that's failing (e.g. `login`). This is the entry point; no symptom record needed.
- **Candidate causes** — the failure modes worth investigating. Each is one `cause` statement.
- **Checks per cause** — how to verify each cause. Each is one `check` statement, linked to the cause via `confirms` / `refutes`.
- **Resolutions** — what to do when a cause is confirmed. Each is one `action` statement, linked to the cause via `resolves`.
- **Diagnostic ordering** — when checks should be run in a particular order (cheap before expensive, common before rare), link them with `next` / `on-success` / `on-failure`.

**The decomposition trap.** Prescriptive writing tends to fuse cause + check + resolution into one sentence (*"If the email looks wrong, check the format and have them retype it"* — three statements). Split before drafting.

## 2. Discover before writing

The substrate doesn't dedup. Search before writing anything.

- **Bulk authoring** — `discover_facts(texts=[…])`. Returns `{text, status, matches}` per input where status is `exists` (≥0.85 — don't duplicate; link or refine via `upsert_statement(id=…)`), `near` (0.6–0.85 — link instead of standing alone), or `new`.
- **Single claim** — `search_statements(query, min_score=0.7, depth=1)` for the claim, then `search_statements(query=<entity-name>)` for each entity you plan to mention.
- **Literal lookup** — `grep_statements(query)` for exact identifiers / phrases that semantic search may miss.
- **Link-type vocabulary** — `list_link_types()` for what's in use; reuse before inventing.

Two extra discovery steps before writing prescriptive content:

- **Search the descriptive layer for the anchor.** Before writing an `action`, search for the `event` it should `performs`. Before writing a `check`, search for the `state` it should `verifies`. Before writing a `cause` that `violates` a required state, search for that state. If the anchor doesn't exist *and the claim sits inside the modeled product*, the descriptive gap comes first. For actions in third-party UIs, no anchor is expected — skip the search (§4).
- **Search existing prescriptive content for the same procedure or diagnostic tree.** A second author writing a parallel "login troubleshooting" tree without finding the existing one is a common failure mode. Search with phrases like *"verify"*, *"check that"*, *"click"*, *"navigate to"*.

**Pre-create entities with descriptions.** `upsert_entity(name, description)` before referencing a fresh entity in `mentions`. The auto-create path produces an entity with an *empty* description — discoverable only by knowing its name. Pre-create with a one-sentence description of what the entity is, even if you'll refine it later.

## 3. Pick the right kind

Routing test — ask which question the statement answers:

| Question | Kind |
|---|---|
| "What is this whole guide for?" | `procedure` — the named root |
| "What does the user do (UI interaction)?" | `action` |
| "What value does the user supply?" | *descriptive* `property` — write that first, then have the procedure `requires` / `accepts` it |
| "What does the diagnostic agent verify?" | `check` |
| "What might be wrong?" | `cause` |
| "What happens in the system as a result?" | *descriptive* `event` — write that first, then anchor the action to it |
| "What condition is being inspected?" | *descriptive* `state` — same; write the state first, then anchor the check |

### Procedure vs action

A `procedure` is the *guide as a whole*. An `action` is a single UI interaction inside it. Every how-to guide has one procedure record at its root; the action chain sits underneath via `contains` or `next`.

A guide *without* a procedure root — just a chain of isolated actions — is wrong shape. The procedure is what consumers query for (*"do we document how to connect over MCP?"*); without it, the guide is unfindable except by walking actions.

### Action vs property — the "Identify / Decide / Determine" tell

If your action text uses a mental verb (*Identify*, *Decide*, *Determine*, *Choose*, *Pick*, *Find*, *Look up*) and the object is a value the user will then plug into a later real action, it is not an action. It is a `property` the procedure consumes. The real UI interactions (open this page, copy this ID, paste it into that field) are the actions.

- ✗ *"Identify the service account's role"* — that's a property, *"Role to grant"*.
- ✗ *"Decide which server to connect to"* — property, *"Server base URL"*.
- ✓ *"Open Settings → Users & invites and create a service account"* — real action; can be `obtained-by` for the *"Service account token"* property.
- ✓ *"Paste the base URL and token into the MCP client configuration"* — real action; terminal step of the procedure.

The exception is genuine inspection without a value being plugged later — e.g. *"Look up the user record in the database"* in a diagnostic context, where the lookup is the verification itself. That's a `check`, not an action and not a property.

### Action vs check

The distinction is who acts and what changes:

- **`action`** — the user takes a step that *modifies* the system. Performs an event. *"Click the Save button"*, *"Enter the API key in the Credentials field"*, *"Navigate to Settings → Integrations"*.
- **`check`** — the diagnostic agent (or support person) *observes* the system without changing it. Verifies a state. *"Verify the API key is non-empty"*, *"Confirm the user's auth provider matches the attempted login method"*, *"Check that the integration status is Connected"*.

A statement framed as a user observation (*"the user can see X"*) is usually a `check` — the agent is checking that the descriptive state holds, not that the user is performing an action.

### Cause vs check

These are easy to conflate:

- **`cause`** — names *what is wrong*. Describes the failure mode itself. *"Email format is invalid"*, *"User signed up via Google but is attempting password login"*, *"Browser cache holds an expired session token"*.
- **`check`** — names *how to find out whether that cause applies*. Describes the verification step. *"Verify the email matches the expected format"*, *"Look up the account and inspect the auth_provider field"*, *"Have the user clear their browser cache"*.

One cause may have multiple checks (different ways to verify). One check may rule out multiple causes (a single inspection distinguishing several failure modes).

### When the claim doesn't fit any of the three

- A factual property of the product → descriptive `state` or `rule`, not prescriptive. *"The session timeout is 30 minutes"* is a `rule` in the descriptive layer, not a check.
- A user-supplied value referenced inside a procedure → descriptive `property` the procedure `requires` or `accepts`, not a prescriptive step (§3).
- An invariant the troubleshooting tree must respect → write it as a `rule` or `state` in the descriptive layer and link the relevant capability or cause to it; the prescriptive record references the descriptive truth.

## 4. Anchoring to the descriptive layer

The prescriptive layer points into the descriptive layer through anchor links.

| Prescriptive | Link | Descriptive |
|---|---|---|
| `procedure` | `teaches` | `capability` |
| `procedure` | `requires` | `property` (mandatory input) |
| `procedure` | `accepts` | `property` (optional input) |
| `action` | `performs` | `event` |
| `check` | `verifies` | `state` |
| `cause` | `violates` | `state` (optional) |

Plus one prescriptive↔prescriptive-or-prescriptive↔descriptive link that bridges layers from the *property* side:

| From | Link | To | Meaning |
|---|---|---|---|
| `property` (descriptive) | `obtained-by` | `action` or `procedure` | How the user finds or produces this value. Empty for values the user simply types in or for derived/computed values. |

Read the link as *"this prescriptive record — [type] → that descriptive record"*. The source is the prescriptive statement; the target is the underlying descriptive truth.

```
[action]  "Click the Save button"
   performs → [event]  "Configuration changes are persisted"

[check]   "Verify the user's authentication provider matches the attempted login method"
   verifies → [state]  "Auth provider on account matches submitted method"

[cause]   "Email format is invalid"
   violates → [state]  "Email is valid format"

[procedure]  "How to connect an MCP client to a Mycelium server"
   teaches  → [capability]  "An MCP client can be connected to a Mycelium server"
   requires → [property]    "Service account token"
                obtained-by → [action] "Open Settings → Users & invites and create a service account"
   accepts  → [property]    "Client display name"
```

### Anchors are optional, not required

The substrate doesn't enforce that every prescriptive statement has an anchor. The reason is substrate evolution — sometimes you need to capture the prescriptive content before the descriptive layer has caught up. Author the prescriptive statement, leave the anchor missing, and flag it:

```
> ⚠️ needs descriptive coverage: this action performs an event that isn't modeled yet
> ("Configuration changes are persisted"). Author the event and add `performs` link.
```

Dangling anchors should be tracked and closed. They are not a permanent state.

### Actions in third-party UIs don't need `performs` anchors

The descriptive layer models *this product's* system — its events, states, and capabilities. When a prescriptive action describes a step in an external system (a third-party admin panel, an integration partner's settings page, a vendor's dashboard), there is no event in the modeled product to anchor to. The action is real and worth documenting (a user genuinely has to click it), but the `performs` link has no valid target.

Leave the anchor absent. Do **not** flag it as a dangling anchor to be closed later — there's nothing to author on the descriptive side. Do **not** invent an event in the modeled product just to give the action a target ("a token is generated in the partner system" is not an event the product observes; if the product observes anything, that's its own event, typically downstream).

Only flag a missing `performs` when the action should trigger an event in the modeled product's own system and that event simply hasn't been authored yet.

### When a cause has no `violates` anchor

A cause is free-standing when the failure mode doesn't reduce to "a required state isn't held". Cases:

- **Environmental** — *"User's network blocks the auth domain"*. No state on a system entity is violated; the failure is outside the system.
- **Historical** — *"Account was created before email verification became required"*. The state at the time was correct; the requirement changed.
- **Referential** — *"User has two accounts and is logging into the wrong one"*. Both accounts hold valid state; the failure is identity confusion.
- **Compound** — *"Stale browser cache combined with an expired session token"*. Multiple states involved; the failure emerges from the combination.

For these, write the cause without `violates`. The cause text itself is the description.

### `verifies` and `violates` can target the same state

The same `state` can be the anchor for a check and the violation target of a cause:

```
[state]  "Email is valid format"
   ↑ verifies      ↑ violates
[check]            [cause]
"Verify the email   "Email format is
matches the         invalid"
expected format"
```

This is the expected pattern. The state is the descriptive truth; the check and cause are two prescriptive framings of it.

## 5. Sequencing and branching

Prescriptive statements form chains. The substrate doesn't enforce ordering on the records themselves; sequence lives entirely in the links.

### `next` — linear sequence

The default. Statement A `next` Statement B means B follows A.

```
[action]  "Navigate to Settings"
   next → [action]  "Click Integrations"
            next → [action]  "Click Add new integration"
```

Use `next` for both procedures and diagnostics when the flow is linear.

### `on-success` and `on-failure` — branching after a check or action

A `check` produces a boolean outcome. An `action` may succeed or fail. Branch with `on-success` and `on-failure`:

```
[check]   "Verify the API key is accepted"
   on-success → [action]  "Save the integration and exit"
   on-failure → [check]   "Verify the API key was copied without trailing whitespace"
                  on-success → [action]  "Re-enter the key with whitespace stripped"
                  on-failure → [check]   "..."
```

This is the diagnostic decision tree. Each branch leads deeper into the flow until a cause is confirmed and an action resolves it.

### When-conditions on prescriptive edges (`when`)

A typed edge holds unconditionally by default. When an edge only fires under a precondition, reify the precondition as its own statement (typically `state`) and attach it as `when` on the link.

`when` is an **expression tree**:

- **leaf** — `{"statement_id": "stm_…"}`. Edge fires when that statement holds.
- **AND** — `{"op": "and", "of": [<child>, <child>, …]}`. All children must hold.
- **OR** — `{"op": "or", "of": [<child>, <child>, …]}`. Any child holding is enough.
- **NOT** — `{"op": "not", "of": [<child>]}`. Exactly one child; edge fires when the child does NOT hold. Use for "this branch is taken when condition C is absent" (e.g. the basic-tab branch in the example below).

Trees nest arbitrarily. The substrate canonicalizes (flattens nested same-op AND/OR nodes, dedupes children, sorts by hash, folds `NOT(NOT(X))` → `X`) so `(A and B)` and `(B and A)` collapse to the same edge.

```
[action]  "Open the Integrations settings"
   next (when: feature-flag-X-enabled) → [action]  "Click the Advanced tab"
   next (when: NOT feature-flag-X-enabled) → [action]  "Click the Basic tab"
```

The condition state lives in the descriptive layer; the `when` references it as a leaf. Don't pack conditions into action text.

To change a condition: `remove_links` the old, `add_links` the new.

### Don't invent ordering when there isn't one

For a diagnostic tree where checks can be run in any order, don't force a `next` chain just to make the structure linear. Leave the checks as siblings under the cause they pertain to. A consumer can pick any order.

## 6. Within-layer links: connecting causes, checks, and actions

The diagnostic loop closes through three within-layer link types:

| From | Link | To | Meaning |
|---|---|---|---|
| `check` | `confirms` | `cause` | If this check passes, this cause is the issue |
| `check` | `refutes` | `cause` | If this check passes, this cause is *not* the issue |
| `action` | `resolves` | `cause` | This action fixes the situation when the cause applies |

```
[cause]   "Email format is invalid"
   ↑ confirms                       ↑ resolves
[check]                             [action]
"Verify the email matches            "Prompt the user to correct
the expected format"                 the email and resubmit"
```

A check can `confirms` multiple causes (when the same observation implicates several failure modes). A cause can be `confirms`-targeted by multiple checks (multiple ways to verify the same thing).

### `confirms` vs `refutes` — pick the polarity that matches the check's text

A check phrased positively (*"Verify the email is valid"*) on success means the state holds — it `refutes` the cause *"Email format is invalid"*.

A check phrased negatively (*"Verify the email is malformed"*) on success means the failure mode applies — it `confirms` the cause.

Prefer positive phrasing for checks (*"Verify X"* rather than *"Verify X is broken"*) and link via `refutes`. This keeps check text readable on its own and avoids double-negatives in the diagnostic flow.

```
[check]   "Verify the email matches the expected format"
   refutes → [cause]  "Email format is invalid"
   on-failure → [action]  "Prompt the user to correct the email and resubmit"
```

The flow: check the state; if it holds (success), the cause is refuted; if it fails (on-failure), take the resolving action.

## 7. Phrasing conventions

The substrate does not currently hard-reject prescriptive phrasing — the conventions below are soft. The agent consuming this content is expected to translate objective step text into a friendly conversational style, so author the *objective* form.

### `procedure` — "How to X" title phrase

A procedure names the user's goal as a guide title. Lead with *"How to"* followed by an imperative verb describing what the user accomplishes.

- ✓ *"How to connect an MCP client to a Mycelium server"*
- ✓ *"How to configure JIT provisioning for an email domain"*
- ✓ *"How to invite a single user to a Mycelium server"*
- ✗ *"Connecting an MCP client"* — gerund, ambiguous between description and instruction; consumers searching for guides expect *"How to"*.
- ✗ *"The user connects an MCP client"* — third-person narration; that's the descriptive event/capability, not the guide.
- ✗ *"How to connect an MCP client and invite users"* — two procedures; split (or this is one procedure whose capability covers both, in which case rename to express the unified goal).

The procedure text is the goal, not the steps. Steps live in `action` records the procedure contains.

### `action` — imperative, second-person elided

The user is the implicit subject. Use the bare imperative verb.

- ✓ *"Click the Save button"*
- ✓ *"Enter the API key in the Credentials field"*
- ✓ *"Navigate to Settings → Integrations"*
- ✗ *"You should click Save"* — chatty; the consumer adds tone
- ✗ *"The user clicks Save"* — third-person narration; this is the descriptive event, not the action
- ✗ *"Click Save and confirm the toast appears"* — two statements (one action + one check); split

### `check` — imperative verification verb

Lead with *Verify*, *Confirm*, *Check*, *Inspect*, *Look up*. The subject of the check is the agent, not the user.

- ✓ *"Verify the user's auth_provider field matches the attempted login method"*
- ✓ *"Confirm the integration status reads Connected"*
- ✓ *"Look up the user record in the database"*
- ✗ *"The email should be valid"* — declarative, not directive; this is the underlying state
- ✗ *"Make sure everything looks right"* — vague; specify what to inspect
- ✗ *"Ask the user to verify their email"* — that's an action (the agent's action is asking; the user does the verifying)

### `cause` — declarative failure-mode statement

State the failure as a condition that holds in the broken case. Reads like a state, but framed as something that *might* be true rather than something that *is* true.

- ✓ *"Email format is invalid"*
- ✓ *"User signed up via Google but is attempting password login"*
- ✓ *"Browser cache holds an expired session token"*
- ✗ *"The email is wrong"* — too vague; specify what's wrong
- ✗ *"Check whether the email is invalid"* — that's a check, not a cause
- ✗ *"Fix the email format"* — that's an action, not a cause

### No conditions in statement text

Conditions go on edges as `when`, not in statement text. The rule applies to all three prescriptive kinds.

- ✗ *"Click Save (only if the form has changed)"* — reify the condition; put it on the edge
- ✗ *"Verify the API key, unless the integration is read-only"* — same
- ✗ *"Email is invalid when it lacks an @ symbol"* — split the cause; specifics live in sub-statements

### Name relationships and their state, not the presence of records

A check or cause that refers to whether something is "set up" should describe the relationship and its state, not the existence of a record. *"X exists in Y"* is CRUD framing — it talks about a row in a table when the meaningful question is what relationship that row represents and what state it's in.

- ✗ *"Verify the user exists on the server"*
- ✓ *"Verify the user has an active account on the server"*

- ✗ *"Confirm the integration record is present"*
- ✓ *"Confirm the integration is connected"*

For causes, the bare-negation form hides the failure mode:

- ✗ *"The user doesn't exist on the server"*
- ✓ *"The user's account has been suspended"* — or — *"The user has never been invited to the server"*

*"Doesn't exist"* collapses *"never invited"* and *"was active, got suspended"* into one statement. They're different failures with different resolutions.

**When the technical term is correct, keep it.** This rule is about CRUD framing specifically, not about scrubbing technical vocabulary. *"Verify the JWT signature is valid"*, *"Confirm the webhook payload includes the X-Signature header"*, *"The OAuth refresh token has expired"* — these are precise and stay as-is. The test isn't *"does this sound business-y"*; it's *"am I talking about a record's existence when I should be talking about a relationship's state?"*

### Atomicity — one statement, one claim

Compound clauses destroy the substrate's ability to link related knowledge. Splits to watch for:

- *"and"* / *"then"* / *";"* joining two steps → split, link with `next`.
- An action and a check fused (*"Click Save and verify the toast appears"*) → two statements.
- A cause that mixes two failure modes (*"Email is invalid or the network is blocked"*) → two causes.
- Subject changes mid-sentence → two statements.

## 8. The procedure shape — worked pattern

### Configuration procedure with properties

When a guide is mostly about *gathering values and submitting them* (an admin filling out a configuration form, an integration setup), the dominant shape is the procedure root composing properties:

```
[procedure]  "How to connect an MCP client to a Mycelium server"
   teaches  → [capability]  "An MCP client can be connected to a Mycelium server"

   requires → [property]    "Server base URL"
                belongs-to  → [entity] MCP Connection
                obtained-by → [action] "Open the server's Connect page and copy the base URL"

   requires → [property]    "Service account token"
                belongs-to  → [entity] MCP Connection
                obtained-by → [action] "Open Settings → Users & invites and create a service account"

   accepts  → [property]    "Role to grant the service account"
                belongs-to  → [entity] MCP Connection
                valued-by   → [rule] "Role to grant is one of reader, writer, admin"

   accepts  → [property]    "Client display name"
                belongs-to  → [entity] MCP Connection

   contains → [action]      "Paste the base URL and token into the MCP client configuration"
                performs → [event] "An MCP initialize request is submitted"
```

Notes on this shape:

- **The procedure is the entry point.** Consumers search *"how to connect over MCP"* and land on the procedure record. From there, `requires` / `accepts` enumerate what they need to gather; `contains` enumerates the UI steps.
- **Properties are shared, not duplicated.** *"Server base URL"* is one record. A second procedure (a diagnostic, a different setup flow) can `requires` the same property without re-authoring it.
- **`obtained-by` is sparse on purpose.** Most properties have no lookup — the user just types in a display name. Only attach `obtained-by` when there's a real lookup with its own UI steps.
- **Action chains stay short.** If the procedure is mostly *gather values, send them*, the action layer contains the *send*. Pre-send "actions" like *"Identify the stage"* are property tells (§3), not actions.

### UI walkthrough with sequential clicks

When a guide is mostly *clicks in sequence* (create a service account through the product's own UI), the action chain dominates and properties may be minimal:

```
[action]   "Navigate to Settings → Users & invites"
   next → [action]   "Click New service account"
            next → [action]   "Enter a name for the service account"
                     next → [action]   "Select a role from the dropdown"
                              next → [action]   "Click Create and copy the generated token"
                                       next → [check]   "Verify a test MCP call with the token returns 200"
                                                on-success → [action]   "Store the token in the client configuration"
                                                on-failure → [cause]   "The service account was created without the required role"
                                                              ↑ resolves
                                                              [action]   "Edit the service account's role and retry"
```

Notes on this pattern:

- **The procedure terminates in a check, not a save.** The step that confirms the procedure worked is itself a check — the user (or the diagnostic agent watching) verifies that the system reports success. The final store action only runs on the success branch.
- **Failure branches transition into diagnostic shape.** *"The test call failed"* fans out into causes — missing role, revoked token, wrong base URL — each with its own resolving action. The procedure and the diagnostic share statements; the same `cause` can be reached either way.
- **Pre-conditions live on the first action's incoming edge.** *"User is logged in as an admin"* and *"The server has authentication enabled"* are descriptive states attached as `when` on the entry edge, not extra action steps.

## 9. The diagnostic shape — worked pattern

Diagnostic trees radiate out from a failing capability. Login can't complete:

```
[capability]   "A user can log in"                                       (descriptive — entry point)
   ↑ (this capability is failing)

[cause]   "User is attempting password login on a social-only account"
   confirms ← [check]   "Look up the account and inspect the auth_provider field"
                          on-failure → [action]   "Direct the user to the correct social-login button"
   violates → [state]   "Auth provider on account matches submitted method"

[cause]   "Email format is invalid"
   confirms ← [check]   "Verify the email matches the expected format"
                          on-failure → [action]   "Prompt the user to correct the email"
   violates → [state]   "Email is valid format"

[cause]   "Network blocks the auth domain"                               (no `violates` — environmental)
   confirms ← [check]   "Have the user attempt the login from a different network"
                          on-failure → [action]   "Advise the user to contact their network admin"

[cause]   "Account predates current email-verification requirement"      (no `violates` — historical)
   confirms ← [check]   "Look up the account creation date against the policy effective date"
                          on-failure → [action]   "Trigger a one-time verification flow for the account"
```

Notes:

- **The entry point is the capability, not a symptom record.** A diagnostic agent receives a user complaint *"I can't log in"*, resolves it to the `login` capability, and walks the cause neighborhood.
- **Causes are siblings, not ordered.** Unless one cause is strictly more likely or strictly cheaper to check, leave them as parallel branches and let the agent decide ordering.
- **Each cause owns its check and resolution.** Don't share checks across causes unless the check genuinely refutes multiple — that's a real `refutes` fan-out, not a shortcut.
- **Free-standing causes use no `violates`.** The environmental and historical causes above carry no descriptive anchor. They're complete in their own text.

## 10. The prescriptive↔descriptive boundary

Watch for cases where the wrong layer is doing the work:

- **A "check" that has no underlying state to verify.** If you can't name the state the check inspects, either the state belongs in the descriptive layer (write it first) or the check is misnamed and is actually an action. *"Check that the user reads the warning"* doesn't verify a system state — it's not a check.
- **An "action" that doesn't perform an event.** If you can't name the event triggered, the action may not be modeling anything observable. *"Action: think carefully about the choice"* isn't an action; it's user advice that doesn't belong as a substrate record.
- **An "action" that's a mental verb.** *"Identify the stage name"*, *"Decide which flow to use"*, *"Determine the rejection reason"* — these aren't UI interactions. The user is *supplying a value*, which means a `property` is missing from the descriptive layer. Write the property first (with `belongs-to` and, if relevant, `valued-by`); have the procedure `requires` / `accepts` it. If finding the value involves real UI work, that UI work becomes an `action` hung off the property via `obtained-by` — not the procedure's main chain. See §3.
- **A "procedure" that just restates a capability.** *"How to log in"* with no inputs and one action *"Click the login button"* adds nothing the `login` capability doesn't already convey. Write the procedure record only when there is real composition (multiple inputs, multi-step UI walkthrough, branching). Otherwise the capability alone is enough.
- **A "cause" that's just a negated state.** If the cause text is exactly the negation of a descriptive state and nothing more, you can skip writing the cause record — a diagnostic agent can derive it by traversing the capability's `requires` edges and inspecting their states. Only write the cause record when it carries information beyond the negation (narrative wording for user-facing communication, additional checks, environmental/historical context).

When in doubt, write the descriptive layer first. Prescriptive content sits on top of descriptive content; the latter is the foundation.

## 11. Isolated prescriptive statements are suspicious

A statement with no incoming AND no outgoing links is almost always wrong: either you forgot to wire it under its parent flow, or the record shouldn't exist.

An action with no `next` in, no `next` out, no `contains`-from-procedure, no `performs` anchor, no `resolves` target, and no `obtained-by` incoming from a property is almost certainly wrong. A check with no `verifies` anchor, no `confirms` / `refutes`, and no place in a sequence is similarly suspect. A `procedure` with no `teaches` link is suspect — every procedure should name the capability it teaches use of.

Exceptions:

- A single-step procedure terminates with one action that has no outgoing `next`. That's fine. But it should have a `performs` anchor (if the step is in the modeled product) and likely an entry condition.
- An action in a third-party UI legitimately has no `performs` anchor (§4). It must still be wired into the procedure via `next` / `on-success` / `on-failure` or `resolves` — sequence connectivity is what saves it from being a true orphan.

The link audit is part of every chunk (§0): after a batch lands, walk the new ids and `get_statements` them. Orphans show up in clusters when the writer focused on text and forgot direction — finding them at chunk boundaries is much cheaper than finding them after another ten chunks have built around them.

## 12. Batch authoring with `upsert_statements`

`upsert_statements(statements=[...])` writes N records in one call with `@N`-references between siblings. Two mechanics matter for ordering:

- **Define dependencies before the things that reference them.** Condition statements and sub-statements go at LOWER indices; the parent / sequencing statements that reference them via `@N` go at HIGHER indices. The substrate validates `@N` against the slot at index N — putting conditions first means rejections cascade *upward* in a predictable direction.
- **Cascade rejection is automatic and transitive.** A phrasing rejection on `@3` propagates to anything that references `@3` via outgoing/incoming links or `when` leaves; the cascade reason in the response is `"depends_on_rejected"` with the offending indices. Items with `allow_phrasing_violations: true` per item bypass their own check but still cascade if a *referenced* sibling was rejected.

Two specifics for prescriptive batches:

- **Author the descriptive anchors before (or in the same batch as) the prescriptive statements** *when an anchor is expected*. If you `upsert_statements` a batch of actions whose `performs` targets don't exist yet, the link writes fail. Either run the descriptive batch first or include the descriptive records at lower `@N` indices. Third-party-UI actions (§4) carry no `performs` link in the batch at all — no ordering concern.
- **Sequencing links go in at the right index too.** When B is `next` after A, define A at a lower index and reference it from B's incoming-link spec, or define both and use a follow-up `add_links` call.

### Pre-create entities before the batch

Mentions auto-create on first use, but in a batch the order is sequential per item — so two siblings mentioning a fresh entity by the same name share the auto-created entity, and the first mention determines its (empty) description. Pre-creating with `upsert_entity(name, description)` before the batch is cheaper than fixing every empty description after.

## Pre-write checklist

1. **Shape identified?** (§1) — procedure or diagnostic. Topology sketched (procedure root + properties + actions; or capability + causes + checks + resolutions).
2. **Discovered?** (§2) — searched existing prescriptive content for the same procedure or diagnostic tree. Searched descriptive layer for anchor targets (capability for the procedure's `teaches`; properties the procedure will require/accept; events / states for action / check anchors). Entities pre-created with descriptions.
3. **Procedure root present?** (§1, §3) — every how-to guide starts with one `procedure` statement, `teaches` a capability, composes properties via `requires` / `accepts`, and contains/sequences its actions. A guide that is just a chain of actions is missing its root.
4. **Configurable inputs modeled as properties, not pseudo-actions?** (§3) — no actions of the form *"Identify X"* / *"Decide Y"* / *"Determine Z"* — those are property tells. Properties live in the descriptive layer with `belongs-to` (and `valued-by` when applicable). Lookups hang off properties via `obtained-by`.
5. **Anchors exist, flagged, or legitimately absent?** (§4) — every `procedure` has a `teaches` capability; every `action` in the modeled product has (or has a flagged need for) a `performs` event; actions in third-party UIs have no anchor and need no flag; every `check` has (or needs) a `verifies` state; every non-free-standing `cause` has a `violates` state.
6. **Right `kind` per statement?** (§3) — procedure / action / check / cause picked by the routing test, not by what feels close.
7. **Phrasing matches the kind?** (§7) — *"How to X"* for procedure, imperative for action, imperative-verification for check, declarative-condition for cause. No conditions in text. No compound steps. One atomic claim per statement.
8. **Within-layer links wired?** (§6) — checks `confirms` / `refutes` causes; actions `resolves` causes. Diagnostic loops close.
9. **Sequencing correct?** (§5) — `next` for linear flow, `on-success` / `on-failure` for branching after checks/actions, `when` on edges for preconditions. Procedure-to-procedure ordering is via `when` on a descriptive state established by the prerequisite procedure — there is no procedure→procedure link.
10. **Boundary check?** (§10) — no checks-without-states, no actions-without-events, no causes-that-are-just-negated-states, no actions-that-are-property-tells, no procedures-that-just-restate-a-capability.
11. **Connected?** (§11) — at least one link in or out per record. Every procedure has `teaches`; every property the procedure consumes has `belongs-to`.
12. **Batch ordered?** (§12) — descriptive anchors (capability, properties, events, states) at lower indices than prescriptive statements (procedure, action, check, cause) that reference them.
13. **Operator approved?** (§0) — no mutation has run yet.

## Handling `near_duplicates` from the upsert response

Every `upsert_statement` / `upsert_statements` returns `near_duplicates` — existing records at cosine ≥0.85.

- **≥0.92, same claim in different wording** → you wrote a duplicate. `merge_statements(from=just-written, into=existing)` immediately.
- **0.85–0.92, related** → not a duplicate, but overlapping ground. Add a link via `add_links` instead of leaving them isolated.

Two specifics for prescriptive content:

- **Parallel diagnostic checks frequently look like near-duplicates.** *"Verify the email format is valid"* and *"Verify the email contains an @ symbol"* score high but are different (one is general, one is specific). They may both stand, with the specific one as a `contains` child of the general one — or the specific one alone is enough. Don't merge reflexively.
- **A "tip" action duplicating a real step is real duplication.** If you authored an action *"Click Save"* and later authored a second action *"After making changes, click Save"* inside the same procedure, that's the same content twice. Merge them.
