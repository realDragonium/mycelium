---
name: mycelium-guide-authoring
description: How to write prescriptive knowledge into a Mycelium knowledge base — how-to guides (how to configure X, how to set up Y) and troubleshooting (what could be wrong, how to verify it, how to resolve it). Covers the four prescriptive kinds (procedure, action, check, cause), the procedure root that teaches a capability and composes property inputs and action chains, anchoring to the descriptive layer (teaches, performs, verifies, violates, obtained-by), sequencing (next, on-success, on-failure, when), the diagnostic loop (confirms, refutes, resolves), objective step phrasing, and why "Identify X" or "Decide Y" is a property, not an action. Use whenever you write procedure, action, check or cause statements, or turn a how-to or troubleshooting page into knowledge. Load mycelium-authoring alongside it for the shared workflow and the descriptive layer the guides anchor to.
---

# Mycelium Guide Authoring

The substrate carries two layers:

- **Descriptive** — what the product does, is, and allows (`event`, `state`, `capability`, `rule`, `property`).
- **Prescriptive** — what a *user* should do, what a *diagnostic agent* should check, and what could be wrong. This skill.

The prescriptive layer is only useful when anchored to the descriptive layer. A procedure is meaningful because it teaches a capability the product exposes. A check is meaningful because the state it verifies is required by a capability. An action is meaningful because the event it performs produces a state the user needs. A cause is meaningful because it names a way a required state can fail to hold.

Four prescriptive kinds:

- **`procedure`** — the named root of a how-to guide. *"How to connect a reporting tool to a workspace."* Anchors via `teaches` to a `capability`. Composes its body via `contains` / `next` (to `action`s), `requires` / `accepts` (to `property`s the user supplies), and terminates in a final action (send/submit/save) or a `check` that confirms success.
- **`action`** — a step the user performs. *"Click the Save button."* Anchors via `performs` to an `event` statement (the thing that actually happens in the system when the user does this).
- **`check`** — a verification step for a diagnostic agent. *"Verify the user's authentication provider matches the login method attempted."* Anchors via `verifies` to a `state` statement (the condition being inspected).
- **`cause`** — a named failure mode worth investigating. *"User is attempting password login on a social-only account."* Optionally anchors via `violates` to a `state` (when the failure mode is "a required state isn't met"). Free-standing when the failure is environmental, historical, referential, or compound.

**Configurable values the user supplies are not prescriptive.** They live in the descriptive layer as `property` records whose text names their entity, producing a derived mention (`valued-by` a rule for format/value-space when applicable). The procedure references them through `requires` (mandatory in this guide) or `accepts` (optional in this guide). They are *not* pseudo-actions — see §3.

Pick the kind first, write the text second. By convention statement text carries no trailing punctuation — statements are labels in a graph. **One statement = one atomic claim** — compound clauses destroy the substrate's ability to link related knowledge.

## 0. Workflow conventions

The shared workflow is in `mycelium-authoring` §8: where your writes land, tell before doing, verify against the code, mark uncertainty, discover before writing, audit links after each chunk, read `near_duplicates`, and batch with `@N`. Two additions for the prescriptive layer:

- **Verify against the actual product, not memory.** A check or action describing a screen, field, or button that doesn't exist (or works differently than described) is worse than no documentation — a diagnostic agent following it will get stuck or send users somewhere wrong. When unsure, open the product and confirm.
- **The descriptive layer is the authority for what the product does.** When writing an action that performs an event *in the modeled product*, the underlying event must already be modeled (or be modeled as part of the same authoring chunk). Don't author prescriptive content over descriptive gaps — flag the gap and pause until it's filled. Dangling anchors are tolerable; *imagined* anchors are not. **Exception:** actions in third-party UIs have no event in the modeled product to anchor to — leave the anchor absent without flagging (§4).

## 1. Model the topology before drafting

Two distinct shapes show up; sketch which one you're in before writing.

### Procedure shape (UI / configuration)

A named root (`procedure`) composing user-supplied inputs (`property`) and a chain of UI steps (`action`). Used for *"how to configure X"*, *"how to set up Y"*.

Sketch:

- **Procedure root** — one `procedure` statement names what the user accomplishes (*"How to connect a reporting tool to a workspace"*). Anchors to the `capability` it teaches via `teaches`. Every guide has exactly one root.
- **Properties** — the configurable values the user supplies. Each is one `property` record on the descriptive side whose text names its entity so a derived mention anchors it (`valued-by` its value-space rule when applicable). The procedure links to them via `requires` (mandatory) or `accepts` (optional). When a property has a non-trivial lookup (creating an API key under **Settings → API keys**), that lookup is itself an `action` or sub-`procedure`, hung off the property via `obtained-by`.
- **Entry point** — what state must the user be in to start? (Logged in as an admin, on a specific settings page, with a prerequisite procedure already completed.) Each prerequisite is a `state` reference (descriptive layer), attached via `when` on the first action's incoming edge if it's a hard gate. **Procedure-to-procedure ordering:** if Guide 1 must complete before Guide 2 can start, gate Guide 2's first action via `when` on the descriptive state Guide 1 establishes. There is no procedure→procedure link type — the existing `when` machinery covers it.
- **Linear actions** — the happy-path UI sequence. Each is one `action` statement; the procedure `contains` them (or chains them via `next`). Only real UI interactions belong here: clicks, navigations, entries, copies, sends.
- **Branches** — when a step has variants. Reify the condition as a state, branch with `on-success` / `on-failure`, or with two `next` edges each carrying a mutually exclusive `when`.
- **Terminal step** — the procedure ends with a final action (send/submit/save) or a `check` confirming success. The terminal *state* (what's true after completion) is descriptive — `establishes`-ed by the final action's event.

**Mental verbs are property tells, not actions.** When you find yourself writing an action like *"Identify the role to grant"*, *"Decide which workspace to connect to"*, *"Determine the API key name"* — stop. These aren't UI interactions; they describe the user *choosing a value*. The value is a `property` the procedure `requires` or `accepts`. If finding the value involves real UI steps, those go on the property as `obtained-by → action` (or a sub-`procedure`); if the user just types it in, no `obtained-by` is needed.

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

Run the discovery in `mycelium-authoring` §8 (`discover_facts` for a batch, `search_statements` and `grep_statements` for single claims, `list_link_types()` for the vocabulary). Two extra steps before writing prescriptive content:

- **Search the descriptive layer for the anchor.** Before writing an `action`, search for the `event` it should `performs`. Before writing a `check`, search for the `state` it should `verifies`. Before writing a `cause` that `violates` a required state, search for that state. If the anchor doesn't exist *and the claim sits inside the modeled product*, the descriptive gap comes first. For actions in third-party UIs, no anchor is expected — skip the search (§4).
- **Search existing prescriptive content for the same procedure or diagnostic tree.** A second author writing a parallel "login troubleshooting" tree without finding the existing one is a common failure mode. Search with phrases like *"verify"*, *"check that"*, *"click"*, *"navigate to"*, and filter with `kind="procedure"` (or `action`, `check`, `cause`).

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

A guide *without* a procedure root — just a chain of isolated actions — is wrong shape. The procedure is what consumers query for (*"do we document how to connect a reporting tool?"*); without it, the guide is unfindable except by walking actions.

### Action vs property — the "Identify / Decide / Determine" tell

If your action text uses a mental verb (*Identify*, *Decide*, *Determine*, *Choose*, *Pick*, *Find*, *Look up*) and the object is a value the user will then plug into a later real action, it is not an action. It is a `property` the procedure consumes. The real UI interactions (open this page, copy this ID, paste it into that field) are the actions.

- ✗ *"Identify the API key's role"* — that's a property, *"API key role"*.
- ✗ *"Decide which workspace to connect to"* — property, *"Workspace API base URL"*.
- ✓ *"Create an API key under Settings → API keys"* — real action; can be `obtained-by` for the *"API key"* property.
- ✓ *"Paste the API key into the reporting tool's connection form"* — real action; terminal step of the procedure.

The exception is genuine inspection without a value being plugged later — e.g. *"Look up the user record in the database"* in a diagnostic context, where the lookup is the verification itself. That's a `check`, not an action and not a property.

### Action vs check

The distinction is who acts and what changes:

- **`action`** — the user takes a step that *modifies* the system. Performs an event. *"Click the Save button"*, *"Enter the API key in the Credentials field"*, *"Navigate to Settings → Integrations"*.
- **`check`** — the diagnostic agent (or support person) *observes* the system without changing it. Verifies a state. *"Verify the API key is non-empty"*, *"Confirm the user's auth provider matches the attempted login method"*, *"Check that the integration status is Connected"*.

A statement framed as a user observation (*"the user can see X"*) is usually a `check` — the agent is checking that the descriptive state holds, not that the user is performing an action.

### Cause vs check

These are easy to conflate:

- **`cause`** — names *what is wrong*. Describes the failure mode itself. *"Email format is invalid"*, *"User signed up via Google but is attempting password login"*, *"Browser cache holds an expired session token"*.
- **`check`** — names *how to find out whether that cause applies*. Describes the verification step. *"Verify the email matches the expected format"*, *"Inspect the auth_provider field on the account"*, *"Have the user clear their browser cache"*.

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

[procedure]  "How to connect a reporting tool to a workspace"
   teaches  → [capability]  "A reporting tool can be connected to a workspace"
   requires → [property]    "API key"
                obtained-by → [action] "Create an API key under Settings → API keys"
   accepts  → [property]    "Reporting tool display name"
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

The prescriptive kinds are checked like events: the validator refuses compound text (*"Click Create and copy the token"*), conditions in the text, universal claims (*every*, *all*, *each*), hedges, rule-shaped wording (*must*, *should*, *never*, *always*), property-shaped wording (*is a*, *has a*) and sequencing (*will*). Read the rejection and split or rephrase; pass `allow_phrasing_violations` only for a verbatim quote. The conventions below go further than the validator: they keep step text objective, and the agent consuming it translates that into a friendly conversational style.

### `procedure` — "How to X" title phrase

A procedure names the user's goal as a guide title. Lead with *"How to"* followed by an imperative verb describing what the user accomplishes.

- ✓ *"How to connect a reporting tool to a workspace"*
- ✓ *"How to configure SSO for a workspace"*
- ✓ *"How to invite a single member to a workspace"*
- ✗ *"Connecting a reporting tool"* — gerund, ambiguous between description and instruction; consumers searching for guides expect *"How to"*.
- ✗ *"The admin connects a reporting tool"* — third-person narration; that's the descriptive event/capability, not the guide.
- ✗ *"How to connect a reporting tool and invite members"* — two procedures; split (or this is one procedure whose capability covers both, in which case rename to express the unified goal).

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

- ✗ *"Verify the member exists in the workspace"*
- ✓ *"Verify the member's account in the workspace is active"*

- ✗ *"Confirm the integration record is present"*
- ✓ *"Confirm the integration is connected"*

For causes, the bare-negation form hides the failure mode:

- ✗ *"The member doesn't exist in the workspace"*
- ✓ *"The member's account has been suspended"* — or — *"The user has not been invited to the workspace"*

*"Doesn't exist"* collapses *"not invited"* and *"was active, got suspended"* into one statement. They're different failures with different resolutions.

**When the technical term is correct, keep it.** This rule is about CRUD framing specifically, not about scrubbing technical vocabulary. *"Verify the JWT signature is valid"*, *"Confirm the webhook payload includes the X-Signature header"*, *"The OAuth refresh token has expired"* — these are precise and stay as-is. The test isn't *"does this sound business-y"*; it's *"am I talking about a record's existence when I should be talking about a relationship's state?"*

### Atomicity — one statement, one claim

Compound clauses destroy the substrate's ability to link related knowledge. Splits to watch for:

- *"and"* / *"then"* / *";"* joining two steps → split, link with `next`.
- An action and a check fused (*"Click Save and verify the toast appears"*) → two statements.
- A cause that mixes two failure modes (*"Email is invalid or the network is blocked"*) → two causes.
- Subject changes mid-sentence → two statements.

## 8–9. Worked patterns

Full examples of both shapes are in `references/worked-patterns.md`: a configuration procedure composing properties, a UI walkthrough whose failure branch turns diagnostic, and a login diagnostic tree with free-standing causes. Read it before authoring your first guide in a session.

## 10. The prescriptive↔descriptive boundary

Watch for cases where the wrong layer is doing the work:

- **A "check" that has no underlying state to verify.** If you can't name the state the check inspects, either the state belongs in the descriptive layer (write it first) or the check is misnamed and is actually an action. *"Check that the user reads the warning"* doesn't verify a system state — it's not a check.
- **An "action" that doesn't perform an event.** If you can't name the event triggered, the action may not be modeling anything observable. *"Action: think carefully about the choice"* isn't an action; it's user advice that doesn't belong as a substrate record.
- **An "action" that's a mental verb.** *"Identify the stage name"*, *"Decide which flow to use"*, *"Determine the rejection reason"* — these aren't UI interactions. The user is *supplying a value*, which means a `property` is missing from the descriptive layer. Write the property first, name its entity in the text for a derived mention, and add `valued-by` when relevant; have the procedure `requires` / `accepts` it. If finding the value involves real UI work, that UI work becomes an `action` hung off the property via `obtained-by` — not the procedure's main chain. See §3.
- **A "procedure" that just restates a capability.** *"How to log in"* with no inputs and one action *"Click the login button"* adds nothing the `login` capability doesn't already convey. Write the procedure record only when there is real composition (multiple inputs, multi-step UI walkthrough, branching). Otherwise the capability alone is enough.
- **A "cause" that's just a negated state.** If the cause text is exactly the negation of a descriptive state and nothing more, you can skip writing the cause record — a diagnostic agent can derive it by traversing the capability's `requires` edges and inspecting their states. Only write the cause record when it carries information beyond the negation (narrative wording for user-facing communication, additional checks, environmental/historical context).

When in doubt, write the descriptive layer first. Prescriptive content sits on top of descriptive content; the latter is the foundation.

## 11. Isolated prescriptive statements are suspicious

A statement with no incoming AND no outgoing links is almost always wrong: either you forgot to wire it under its parent flow, or the record shouldn't exist.

An action with no `next` in, no `next` out, no `contains`-from-procedure, no `performs` anchor, no `resolves` target, and no `obtained-by` incoming from a property is almost certainly wrong. A check with no `verifies` anchor, no `confirms` / `refutes`, and no place in a sequence is similarly suspect. A `procedure` with no `teaches` link is suspect — every procedure should name the capability it teaches use of.

Exceptions:

- A single-step procedure terminates with one action that has no outgoing `next`. That's fine. But it should have a `performs` anchor (if the step is in the modeled product) and likely an entry condition.
- An action in a third-party UI legitimately has no `performs` anchor (§4). It must still be wired into the procedure via `next` / `on-success` / `on-failure` or `resolves` — sequence connectivity is what saves it from being a true orphan.

The link audit is part of every chunk (`mycelium-authoring` §8): after a batch lands, walk the new ids and `get_statements` them. Orphans show up in clusters when the writer focused on text and forgot direction — finding them at chunk boundaries is much cheaper than finding them after another ten chunks have built around them.

## 12. Batch ordering for prescriptive content

`upsert_statements` with `@N` references, and how rejections cascade, are covered in `mycelium-authoring` §8. Two specifics for prescriptive batches:

- **Author the descriptive anchors before (or in the same batch as) the prescriptive statements** *when an anchor is expected*. If you `upsert_statements` a batch of actions whose `performs` targets don't exist yet, the link writes fail. Either run the descriptive batch first or include the descriptive records at lower `@N` indices. Third-party-UI actions (§4) carry no `performs` link in the batch at all — no ordering concern.
- **Sequencing links go in at the right index too.** When B is `next` after A, define A at a lower index and reference it from B's incoming-link spec, or define both and use a follow-up `add_links` call.

Create the concepts the batch names first (`upsert_entity`), so the derived mentions resolve: a statement mentions a concept only when one of its names appears in the text, and nothing is created on first use.

## Pre-write checklist

1. **Shape identified?** (§1) — procedure or diagnostic. Topology sketched (procedure root + properties + actions; or capability + causes + checks + resolutions).
2. **Discovered?** (§2) — searched existing prescriptive content for the same procedure or diagnostic tree. Searched descriptive layer for anchor targets (capability for the procedure's `teaches`; properties the procedure will require/accept; events / states for action / check anchors). Concepts the texts name exist, with descriptions.
3. **Procedure root present?** (§1, §3) — every how-to guide starts with one `procedure` statement, `teaches` a capability, composes properties via `requires` / `accepts`, and contains/sequences its actions. A guide that is just a chain of actions is missing its root.
4. **Configurable inputs modeled as properties, not pseudo-actions?** (§3) — no actions of the form *"Identify X"* / *"Decide Y"* / *"Determine Z"* — those are property tells. Properties live in the descriptive layer, name their entity for a derived mention, and use `valued-by` when applicable. Lookups hang off properties via `obtained-by`.
5. **Anchors exist, flagged, or legitimately absent?** (§4) — every `procedure` has a `teaches` capability; every `action` in the modeled product has (or has a flagged need for) a `performs` event; actions in third-party UIs have no anchor and need no flag; every `check` has (or needs) a `verifies` state; every non-free-standing `cause` has a `violates` state.
6. **Right `kind` per statement?** (§3) — procedure / action / check / cause picked by the routing test, not by what feels close.
7. **Phrasing matches the kind?** (§7) — *"How to X"* for procedure, imperative for action, imperative-verification for check, declarative-condition for cause. No conditions in text. No compound steps. One atomic claim per statement.
8. **Within-layer links wired?** (§6) — checks `confirms` / `refutes` causes; actions `resolves` causes. Diagnostic loops close.
9. **Sequencing correct?** (§5) — `next` for linear flow, `on-success` / `on-failure` for branching after checks/actions, `when` on edges for preconditions. Procedure-to-procedure ordering is via `when` on a descriptive state established by the prerequisite procedure — there is no procedure→procedure link.
10. **Boundary check?** (§10) — no checks-without-states, no actions-without-events, no causes-that-are-just-negated-states, no actions-that-are-property-tells, no procedures-that-just-restate-a-capability.
11. **Connected?** (§11) — at least one statement link in or out per record. Every procedure has `teaches`; every property the procedure consumes is linked through `requires` or `accepts` and names its entity for a derived mention.
12. **Batch ordered?** (§12) — descriptive anchors (capability, properties, events, states) at lower indices than prescriptive statements (procedure, action, check, cause) that reference them.
13. **Operator approved?** (`mycelium-authoring` §8) — no live mutation has run yet.

## `near_duplicates` in prescriptive content

Handle `near_duplicates` as `mycelium-authoring` describes. Two specifics:

- **Parallel diagnostic checks frequently look like near-duplicates.** *"Verify the email format is valid"* and *"Verify the email contains an @ symbol"* score high but are different (one is general, one is specific). They may both stand, with the specific one as a `contains` child of the general one — or the specific one alone is enough. Don't merge reflexively.
- **A "tip" action duplicating a real step is real duplication.** If you authored an action *"Click Save"* and later authored a second action *"After making changes, click Save"* inside the same procedure, that's the same content twice. Keep one.
