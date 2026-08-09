# Knowledge-Base Authoring from Substrate

Query the mycelium product substrate to gather facts about a topic, then write a
markdown document using a Diátaxis template that matches what the reader needs.

The substrate is the **source of truth for product behaviour**. Do not fill in template
sections from training-data assumptions. If a fact isn't in the substrate, flag it with
a confidence marker rather than inventing it.

---

## Step 0: Determine template type and output path

Before querying anything, settle two things:

**Template type** — answer the question "what does the reader want right now?"

| Reader wants to… | Template |
|---|---|
| Walk through their first success with a topic | `tutorial` |
| Accomplish a specific task (incl. configuration) | `how-to` |
| Look something up: settings, fields, params, limits | `reference` |
| Understand how or why something works | `explanation` |
| Fix a problem they're hitting right now | `troubleshooting` |

If the user's request doesn't clearly map to one type, prefer `how-to` for action-oriented
requests and `explanation` for concept-oriented ones. If genuinely ambiguous, ask once.

**Output path** — infer from context:

- User-facing public article → `user-docs/pages/<topic>/`
- Internal staff article → `user-docs/internal/en-GB/<topic>/`
- Standalone knowledge doc → wherever the caller specifies

Always confirm the output path with the caller if it isn't obvious.

---

## Step 1: Build a substrate knowledge map

Query the substrate systematically before writing. The goal is to accumulate enough
verified facts that every non-trivial section of the template can be backed by at least
one statement.

### 1a. Identify entities and statements

```
search_statements(query=<topic>, min_score=0.7, depth=2)
```

Run this first. Then expand into the returned entities:

```
get_entity(name=<entity-name>)      # includes all linked statements
```

Repeat for each entity that's central to the topic. Aim for 2–4 passes before writing.

### 1b. Gather specific fact types by template

Different templates need different fact shapes from the substrate:

| Template | What to collect from substrate |
|---|---|
| `tutorial` | Capability statements (what the user can do), event sequences (what happens when), state statements (what the system looks like at key points) |
| `how-to` | Action/event sequences, state preconditions, rejection events (what blocks the task) |
| `reference` | State statements (fields, config flags, values), rule statements (how values are computed/bounded), capability statements |
| `explanation` | Rule statements (why things work a certain way), capability statements, temporal/provider variation states |
| `troubleshooting` | Cause/check/action statements, rejection events, state preconditions that must hold |

### 1c. Check for gaps

If a section of the template requires a fact you cannot find in the substrate:

1. Try `grep_statements(query=<literal term>)` — semantic search may have missed it.
2. If still absent, mark it with a confidence marker (§ Accuracy below) rather than
   inventing the fact.

---

## Step 2: Accuracy and confidence markers

Never state product-specific facts (field names, limits, behaviour, flow order) unless
a substrate statement supports the claim. This applies even to "common knowledge" —
the substrate is the authority.

Two inline markers for uncertainty:

```
> 💡 likely correct: [what was inferred and from which statement/entity].
> ⚠️ needs verification: [what's unclear and why the substrate doesn't resolve it].
```

Anything written without a marker must be traceable to a substrate statement.

---

## Step 3: Load and fill the template

The template for each type is a sibling row of this one: same `guideline-set` type,
named for the document type it produces.

| Type | Row |
|---|---|
| Tutorial | `kb-authoring/tutorial` |
| How-to | `kb-authoring/how-to` |
| Reference | `kb-authoring/reference` |
| Explanation | `kb-authoring/explanation` |
| Troubleshooting | `kb-authoring/troubleshooting` |

Load the row for the type you settled on in Step 0 — fetching it yourself is
`get_prompt_text("guideline-set", "kb-authoring/tutorial")` — and write the document
using it as the starting point.

Rules that apply to all types when filling in the template:

- **Audience field** — choose `external` (customers/end-users), `internal` (staff only),
  or `both` (visible everywhere, written for the most cautious audience).
- **Tone** — warm and clear, second person ("you"), active voice. Short sentences. No
  "simply", no "just", no fake enthusiasm.
- **One doc = one type.** If writing tempts you to mix steps with conceptual explanation,
  split and link.
- **Frontmatter** — fill all fields; do not leave placeholders in the final output.
- **last_updated** — use today's date (YYYY-MM-DD format).
- **related** — populate with slugs/paths to docs that pair well with this one.
- **Remove HTML comments** (`<!-- … -->`) before saving — they are authoring notes, not
  reader content.

---

## Step 4: Save and verify

1. Save to the agreed output path. Use kebab-case filenames.
2. If the doc contains relative links, validate them where the docs they point at
   live — `go run tools/validate-links.go` in that repository. Without a checkout,
   hand the links back to the caller as unvalidated rather than claiming they hold.
3. Check the quality checklist below before declaring done.

---

## Quality checklist

- [ ] Template type matches what the reader actually needs right now
- [ ] Every non-trivial fact traces to a substrate statement or carries a confidence marker
- [ ] No placeholder text (`{…}`) left in the saved file
- [ ] Frontmatter is fully populated (`title`, `type`, `audience`, `last_updated`, `owner`, `related`)
- [ ] Tone: second person, active voice, no "simply" / "just"
- [ ] Tutorial/how-to: one action per numbered step
- [ ] Reference: tables used for structured data; prose only in `Notes` and section preambles
- [ ] Explanation: analogy or mental model present; no step-by-step instructions
- [ ] Troubleshooting: organized by symptom (what the user sees), not by internal cause
- [ ] Related links populated where appropriate
