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
