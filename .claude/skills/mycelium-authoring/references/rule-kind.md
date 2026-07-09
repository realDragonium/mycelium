# The `rule` kind

Read this when authoring deterministic computation, defaults, bounds, or enumerations. The canonical definition of the `rule` kind lives in `upsert_statement`; this file is the **rule-vs-state discrimination test** the definition can't give you. The test: a rule is **non-contingent** — it holds the same way across all instances and moments. If the same claim could be otherwise for a specific entity or at a specific time, it is **not** a rule.

## Rule vs. state — the easiest place to go wrong

| Claim | Kind | Why |
|---|---|---|
| "Cosine similarity is bounded between -1 and 1" | rule | Definitional — always true |
| "This user's role is `admin`" | state | Could be `reader` for another user |
| "Default result ordering is similarity-descending" | rule | The default itself is fixed |
| "Statement S is pinned above the similarity ordering" | state | Per-instance override |
| "Statement kind is one of: event, state, capability, rule, property" | rule | Defines the value space |
| "Kind boost is a number between 0 and 100" | rule | Value-space rule |
| "Statement S has kind boost 35" | state | Current value for this instance |

The contingency test: **configured/input values** → current value is a `state`, the value space/default/computation is a `rule`. **Derived values** → current value is a `state` (or `property`) `valued-by` the `rule` that computes it.

## Sub-shapes (all `kind=rule`; link patterns differ)

- **Calculation** — a formula. Decomposes via `composes` into sub-formulas.
- **Default** — the value chosen when nothing overrides.
- **Enumeration** — the possible values for an attribute (*"Statement kind is one of: event, state, capability, rule, property"*).
- **Option semantics** — what each enum branch means computationally. Links to its parent via `cases`.

## Phrasing tells

| Pattern | Indicates |
|---|---|
| "X equals Y", "X is computed as", "X is the sum of", "X is determined by" | calculation |
| "Default X is Y" | default |
| "X is one of: …" | enumeration |
| "X is bounded by", "X is between A and B" | bound |

Rule phrasing is independent of the event/state/capability catalogs — copular and mathematical constructions that those kinds reject are valid here. Contingent language (`can`, `may`, `sometimes`, mid-sentence `if`) is rejected.

## `cases` vs. `when`-on-`composes` — not interchangeable

- **`cases`** — only for enumeration over a **named, finite value set** (statement kinds, link types). Each `cases` edge points to one branch; the branches are option-semantics rules.
- **`when` on a `composes` edge** — for **continuous predicates or conditional applicability**. Edge cases are parallel `composes` children of the same parent carrying **mutually exclusive** `when`-conditions (e.g. `total_kind_weight > 0` vs. `= 0`).

There is no `sibling`/`parallel` link type — edge cases are just parallel `composes` edges with exclusive `when`s. (Confirm exact link-type availability and direction with `list_link_types()`.)

## When an enumeration needs its own rule statement

Only when **other rules traverse it via `cases`** — `cases` requires statement targets. If nothing in the rule graph references the value space, the entity description is enough. `cases` edges can also point straight from a parent rule to the option-semantics rules; a separate enumeration rule is only needed to assert closed-set completeness or to reference the value space elsewhere.

## What NOT to do

- Rule `triggers` X — rules don't fire.
- Event `enables` Rule — rules aren't gated by events.
- Rule `produces` State — events produce states; rules determine the value a state takes (use `valued-by` on the state/property side).

## Worked example (sketch)

```
[capability] "A rank score can be computed for a query and a statement"
   governed-by → [R0]

[R0] "Rank score equals similarity contribution plus recency boost minus staleness penalty"
   composes → [R1 similarity contribution]   composes → [R2 recency bound]   composes → [R3 staleness penalty]

[R1] "Similarity contribution equals cosine similarity times kind weight share"
   composes (when total_kind_weight > 0) → [R1a kind weight share formula]
   composes (when total_kind_weight = 0) → [Rule: kind contribution is zero]
   composes → [R1b kind weight]

[R1b] "Kind weight is determined by statement kind"
   cases → [descriptive kind weights]   cases → [prescriptive kind weights]
       cases → [capability weight is 1.0] … etc.

[R2] "Recency boost is bounded between 0 and 20"
```

A consumer enters at the capability and follows `governed-by → composes → cases` to assemble the full computation. Decompose into atomic rules over monolithic statements — compound sentences with multiple subjects or qualifying clauses almost always conceal multiple rules.
