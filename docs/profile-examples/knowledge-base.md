# Example profile: Knowledge base

Every Diátaxis type: tutorials, how-tos, reference, explanations and troubleshooting.

This is an example to copy, not a profile the server loads. Create a profile in **Settings → Documentation** or with `save_writing_profile`, and paste the texts below into it. Adjust them to your product and readers.

- **Suggested name:** `kb-authoring`
- **Audience:** Internal technical, or whichever audience the knowledge base is for.
- **Templates:** `tutorial`, `how-to`, `reference`, `explanation`, `troubleshooting`

## Guidance

````markdown
# Knowledge-Base Authoring from Substrate

Query the mycelium product substrate to gather facts about a topic, then write a
markdown document from the Diátaxis template for the document type you were given.

The substrate is the **source of truth for product behaviour**. Do not fill in template
sections from training-data assumptions. If a fact isn't in the substrate, flag it with
a confidence marker rather than inventing it.

---

## Step 1: Gather the facts the type needs

Gather until every non-trivial section of the template can be backed by at
least one statement. Different types rest on different kinds of statement:

| Type | What to gather |
|---|---|
| `tutorial` | Capability statements (what the user can do), event sequences (what happens when), state statements (what the system looks like at key points) |
| `how-to` | Procedures and their actions, state preconditions, rejection events (what blocks the task) |
| `reference` | State and property statements (fields, settings, values), rule statements (how values are computed or bounded), capability statements |
| `explanation` | Rule statements (why things work a certain way), capability statements, states that vary over time or by plan |
| `troubleshooting` | Cause, check and action statements, rejection events, state preconditions that must hold |

A section the substrate cannot support is a knowledge gap, not a section to
fill from what systems like this usually do.

---

## Step 2: Accuracy and confidence markers

Never state product-specific facts (field names, limits, behaviour, flow order) unless
a substrate statement supports the claim. This applies even to "common knowledge" —
the substrate is the authority.

Two inline markers for uncertainty:

```
> 💡 likely correct: [what was inferred, in the reader's terms].
> ⚠️ needs verification: [what's unclear, in the reader's terms].
```

The markers are for the reader, who never sees the substrate: they never name
it, a statement or entity id, or a tool. Which statements a section rests on
travels beside the document, not in it.

Anything written without a marker must be traceable to a substrate statement.

---

## Step 3: Fill the template

The template for the type you were given is already in front of you. Write
the document using it as the starting point.

Rules that apply to all types when filling in the template:

- **Audience field** — `external` when the audience you write for is external,
  `internal` when it is internal. The audience is fixed for the run; the field
  records it, it does not choose it.
- **Vocabulary** — write about the product, never about the substrate behind
  the document: no "substrate", no statement or entity ids (`stm_…`, `ent_…`),
  no tool names.
- **Tone** — warm and clear, second person ("you"), active voice. Short sentences. No
  "simply", no "just", no fake enthusiasm.
- **One doc = one type.** If the material tempts you to mix steps with conceptual
  explanation, keep to this document's type and leave the rest out.
- **Frontmatter** — fill every field you have a source for, and never leave a
  placeholder in the final output. Two fields have no source in the substrate;
  both are covered below.
- **last_updated** — use today's date (YYYY-MM-DD format).
- **owner** — leave it blank. Ownership is who is accountable for keeping the
  page current, which is a fact about the team rather than about the product, so
  the substrate does not hold it and you cannot know it. A human fills it when
  the page is adopted. Never guess a team or a person: a name here reads as
  though someone agreed to maintain this, and nobody has.
- **related** — list slugs/paths to docs that pair well with this one, and leave
  it `[]` when there are none yet. The cross-link sections in the body follow the
  same rule: link real articles, and delete the section when there are none. A
  link whose path is still `{path}` points nowhere, and a section saying no
  articles exist is not a section.
- **Remove HTML comments** (`<!-- … -->`) — they are authoring notes, not reader
  content.

---

## Quality checklist

- [ ] Every non-trivial fact traces to a substrate statement or carries a confidence marker
- [ ] No placeholder text (`{…}`) left in the document
- [ ] Frontmatter carries every field with a source (`title`, `type`, `audience`, `last_updated`), `related` lists only articles that exist, and `owner` is blank
- [ ] Cross-link sections either link real articles or are deleted
- [ ] Tone: second person, active voice, no "simply" / "just"
- [ ] Tutorial/how-to: one action per numbered step
- [ ] Reference: tables used for structured data; prose only in `Notes` and section preambles
- [ ] Explanation: analogy or mental model present; no step-by-step instructions
- [ ] Troubleshooting: organized by symptom (what the user sees), not by internal cause
````

## Disclosure rules

````markdown
# What a knowledge-base article may reveal

This set writes for a reader who is not in the room and may not be in the
company. The run reads only what its audience may see, and the reviewer also
checks the article against the audience's description. The boundary below
holds on top of both, whatever the audience: a statement the audience may see
can still carry a detail no article should repeat, and a document that leaks
has leaked wherever it was filed.

A reviewer checks the finished article against this text. A writer who applies
it first keeps the run's one retry for something else.

## What stays out

**Where the system runs.** Internal hostnames and IP ranges must not appear,
nor internal service or repository names, nor infrastructure topology that is
not already public. Name the product boundary the reader can see and leave the
machinery behind it out.

**Who the system runs for.** No named customers, no tenant identifiers, and
nothing that identifies an individual — names, contact details, account
numbers. An example drawn from a real case is anonymised, not shortened.

**Anything that authenticates.** Credentials, tokens, private keys and
connection strings never appear. Treat a value as live unless the document
makes plain it is a placeholder that cannot connect to anything.

**Work that has not shipped.** Unreleased and roadmap capability must not be
written as behaviour the reader has today. It may be mentioned only where it
is already published as forthcoming, and only in wording that keeps it
forthcoming. Internal ticket identifiers and staff names stay out with it.

**The run's own bookkeeping.** Statement and entity ids, tool names and the
word "substrate" do not belong in the title or body, and neither does talk of
what the knowledge base holds. Provenance travels beside the document, and a
reader who cannot resolve an id is being shown a reference to nothing. Say
what is not known in the reader's terms: "this is not documented yet", not
"the substrate does not say".

**How to defeat a control.** Describe a security control to the depth a reader
needs to use it — how to turn it on, what it refuses, how to recover from it.
Stop before the detail that helps someone bypass, evade or weaken it.

## What may be revealed

Published product behaviour the substrate supports. Configuration the reader
controls, named and explained. Documented limits and defaults, stated
precisely rather than rounded into vagueness. Error text a user actually sees,
quoted where quoting it helps them act.

These are permissions, not exceptions: none of them licenses anything the
section above withholds.

## The hard case

Sooner or later a section genuinely needs a fact whose only supporting
statement carries an internal detail along with it. That the substrate holds
the detail is evidence the detail exists; it is not permission to publish it.

Separate the reader-visible effect from the implementation that produces it,
and check each half on its own. Write the half that clears the boundary and
drop the other — do not hedge it, euphemise it, or encode it thinly enough to
be reconstructed. If what remains is then unsupported or useless to the
reader, leave the claim out and let the gap stand.

Fail the exposure check when a withheld detail is still in the text, or when a
permitted claim only works because one is. Pass it when everything the article
says is both useful to its reader and inside this boundary.
````

## Templates

### `tutorial`

````markdown
---
title: 
type: tutorial
audience: external
last_updated: YYYY-MM-DD
owner: 
related: []
---

<!--
Leave `owner` blank: a person fills it when the page is adopted. Leave out
any section, table column or field the knowledge base cannot fill, and file a
knowledge gap for it; an omitted column is not a defect.

TUTORIAL — learning-oriented.

Hand-hold a first-time user from zero to a meaningful outcome.
- Concrete steps, no abstraction
- Reassure often ("you should see X — that means it's working")
- Save the "why" for an Explanation doc, link to it
- Pick ONE happy path; alternatives belong in How-to
- Aim for <15 minutes to a real result
-->

# {Title — usually "Get started with X" or "Build your first X"}

Welcome! In this tutorial, you'll {one-sentence outcome — something concrete they can point at}. It takes about {X} minutes.

By the end, you'll know how to:

- {Skill 1}
- {Skill 2}
- {Skill 3}

## Before you start

{Minimal prerequisites. If it's required, list it. If it's optional, leave it out.}

- {Prerequisite}
- {Prerequisite}

## Step 1: {Concrete action}

{One sentence: what we're about to do and why it matters.}

1. {Action}.
2. {Action}.

You should now see {what success looks like at this point}. {Optional reassurance.}

## Step 2: {Next action}

{Continue the narrative — what we're building on.}

1. {Action}.
2. {Action}.

## Step 3: {Final action}

{Bring it home.}

1. {Action}.
2. {Action}.

## You did it!

You just {recap the outcome in plain language}. That's the core loop — everything else builds on this.

## What's next

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

- [How to {related task}]({path}) — when you're ready to {scenario}
- [How {concept} works]({path}) — if you want to understand what just happened
````

### `how-to`

````markdown
---
title: 
type: how-to
audience: external
last_updated: YYYY-MM-DD
owner: 
related: []
---

<!--
Leave `owner` blank: a person fills it when the page is adopted. Leave out
any section, table column or field the knowledge base cannot fill, and file a
knowledge gap for it; an omitted column is not a defect.

HOW-TO — task-oriented.

Reader knows what they want and has basic competence. Get them there.
- Title starts with "How to..." or a clear action verb
- No teaching, no rationale (link to Explanation if needed)
- One task per doc — if you find yourself writing "alternatively...", split it
- Covers configuration/setup tasks too
-->

# {How to X}

{One sentence: what this achieves and when you'd do it.}

## Before you start

- {Prerequisite, permission, or role required}
- {Feature or setting that must be enabled}

## Steps

1. {Action — verb first, specific UI/CLI reference}.
2. {Action}.

   {Image: the screen this step happens on, when one is offered.}

3. {Action}.

{If a step has sub-steps, nest them:}

4. {Parent step}:
   - {Sub-step}
   - {Sub-step}

## Verify it worked

{How to confirm success — what they should see, where to check, what value to expect.}

## Troubleshooting

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

If you hit issues, see [Troubleshooting: {topic}]({path}).

## Related

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

- [Reference: {settings/fields used}]({path})
- [How {concept} works]({path})
````

### `reference`

````markdown
---
title: 
type: reference
audience: external
last_updated: YYYY-MM-DD
owner: 
related: []
---

<!--
Leave `owner` blank: a person fills it when the page is adopted. Leave out
any section, table column or field the knowledge base cannot fill, and file a
knowledge gap for it; an omitted column is not a defect.

REFERENCE — information-oriented.

Dry, accurate, complete, structured. Optimize for lookup, not reading.
- No tutorials, no opinions, no "we recommend..."
- Tables and lists over prose
- If you're tempted to explain "why", that goes in an Explanation doc — link it
- Warmth lives only in the intro/preamble, never in the data
-->

# {Title — the thing being referenced}

{One sentence describing what this references and where it applies.}

## {Group/Category 1}

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `{field}` | {type} | {yes/no} | {default} | {one-line description} |
| `{field}` | {type} | {yes/no} | {default} | {one-line description} |

<!-- Add detailed sections only for fields that need more than a table cell -->

### `{field_name}`

- **Type**: {type}
- **Required**: {yes / no / conditional — see notes}
- **Default**: {default or "none"}
- **Allowed values**: {list or pattern}
- **Example**: `{example}`

{Notes, edge cases, or interactions with other fields.}

## {Group/Category 2}

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `{field}` | {type} | {yes/no} | {default} | {description} |

## Notes

{Global behavior, version differences, deprecations, gotchas that don't fit in any single row.}

## Related

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

- [How to configure {area}]({path})
- [How {concept} works]({path})
````

### `explanation`

````markdown
---
title: 
type: explanation
audience: external
last_updated: YYYY-MM-DD
owner: 
related: []
---

<!--
Leave `owner` blank: a person fills it when the page is adopted. Leave out
any section, table column or field the knowledge base cannot fill, and file a
knowledge gap for it; an omitted column is not a defect.

EXPLANATION — understanding-oriented.

Help the reader build a mental model.
- Discuss "why", trade-offs, design choices
- No step-by-step instructions (that's How-to)
- Not exhaustive (that's Reference)
- Analogies and diagrams pay for themselves here
- It's OK to be opinionated about how to think about it
-->

# {Title — "How X works" / "Understanding X" / "What X is"}

{One sentence definition in plain language. The 30-second version.}

## The short version

{2–3 sentences. If they only read this far, what should they walk away knowing? This is the lede.}

## A mental model

{An analogy mapping the concept to something familiar. Be concrete.}

{Diagram placeholder — replace with an image, mermaid, or ascii sketch if helpful.}

## How it works

{The fuller picture. Walk through the concept with examples. Build up from simple to complex.}

### {Sub-concept 1}

{Explanation.}

### {Sub-concept 2}

{Explanation.}

## Why it works this way

{Design rationale and trade-offs. What were the alternatives? Why did we go this route? What does it optimize for, and what does it give up?}

## Common misconceptions

<!-- Optional. Include a misconception only when the correction rests on
statements you retrieved; a correction you reasoned out yourself is an
invented claim. Delete this section if there are none. -->

- **{Misconception}** — {what's actually true and why}.
- **{Misconception}** — {correction}.

## Related

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

- [How to {related task}]({path})
- [Reference: {related fields/settings}]({path})
````

### `troubleshooting`

````markdown
---
title: 
type: troubleshooting
audience: external
last_updated: YYYY-MM-DD
owner: 
related: []
---

<!--
Leave `owner` blank: a person fills it when the page is adopted. Leave out
any section, table column or field the knowledge base cannot fill, and file a
knowledge gap for it; an omitted column is not a defect.

TROUBLESHOOTING — symptom-driven.

Reader is frustrated and wants a fix. Lead with the most common cause.
- Organize by what the USER SEES, not by what's happening internally
- Quick checks first — covers ~80% of cases without scrolling
- Each symptom: cause in plain English, then steps
- If a fix is risky/destructive, flag it before the steps
- Keep an escalation path at the bottom
-->

# {Title — usually a symptom area: "X isn't working" / "Troubleshooting X"}

{One sentence: what this covers and a small dose of reassurance. Most issues here are fixable in a few steps.}

## Quick checks

Before digging in, try these — they catch most cases:

1. {Most common fix — e.g., "Refresh the page and try again"}.
2. {Second most common}.
3. {Third most common}.

Still seeing the issue? Find your symptom below.

## {Symptom 1 — what the user sees, in their words}

**What's happening**: {plain-English cause}.

**Fix**:

1. {Step}.
2. {Step}.

{Optional: how to verify it's fixed.}

## {Symptom 2}

**What's happening**: {cause}.

**Fix**:

1. {Step}.
2. {Step}.

## {Symptom 3}

**What's happening**: {cause}.

<!-- Use this callout style for destructive or irreversible steps -->
> ⚠️ This will {what gets changed/lost}. {When it's safe to do.}

**Fix**:

1. {Step}.
2. {Step}.

## Still stuck?

{Escalation path: support contact, internal channel, ticket link. Keep it specific — "contact support" alone is too vague.}

## Related

<!-- Link only articles that exist. If none do, delete this whole section:
a link whose path is still a placeholder points nowhere, and an empty
section is worse than no section. -->

- [How to {related task}]({path})
- [How {concept} works]({path})
````
