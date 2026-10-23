# The `rule` kind

Read this when authoring deterministic computation, defaults, bounds, or enumerations. The canonical definition of the `rule` kind lives in `upsert_statement`; this file is the **rule-vs-state discrimination test** the definition can't give you. The test: a rule is **non-contingent** — it holds the same way across all instances and moments. If the same claim could be otherwise for a specific entity or at a specific time, it is **not** a rule.

## Rule vs. state — the easiest place to go wrong

| Claim | Kind | Why |
|---|---|---|
| "Invoice total is never negative" | rule | Definitional — always true |
| "The member's role is Viewer" | state | Could be Owner for another member |
| "Default export format is CSV" | rule | The default itself is fixed |
| "The workspace exports as XLSX" | state | Per-instance override |
| "Invoice status is one of: draft, finalized, paid, void" | rule | Defines the value space |
| "Seat count is a number between 1 and 500" | rule | Value-space rule |
| "The workspace has 35 seats" | state | Current value for this instance |

The contingency test: **configured/input values** → current value is a `state`, the value space/default/computation is a `rule`. **Derived values** → current value is a `state` (or `property`) `valued-by` the `rule` that computes it.

## Sub-shapes (all `kind=rule`; link patterns differ)

- **Calculation** — a formula. Decomposes via `composes` into sub-formulas.
- **Default** — the value chosen when nothing overrides.
- **Enumeration** — the possible values for an attribute (*"Invoice status is one of: draft, finalized, paid, void"*).
- **Option semantics** — what each enum branch means computationally. Links to its parent via `cases`.

## Phrasing tells

| Pattern | Indicates |
|---|---|
| "X equals Y", "X is computed as", "X is the sum of", "X is determined by" | calculation |
| "Default X is Y" | default |
| "X is one of: …" | enumeration |
| "X is bounded by", "X is between A and B" | bound |
| "X must Y", "X must not Y", "X shall Y", "X may Y", "X is required to Y", "X never Y" | obligation, prohibition or permission |

Rule phrasing is independent of the event/state/capability catalogs — the modal, copular and mathematical constructions those kinds reject are valid here. The validator still rejects hedges (`sometimes`), conditions (mid-sentence `if`), universal quantifiers, compounds and `will`. It does not tell permission `may` from possibility `can` / `might`: a claim that could be otherwise for one instance fails the contingency test, so make it a `capability` or `state` yourself.

## `cases` vs. `when`-on-`composes` — not interchangeable

- **`cases`** — only for enumeration over a **named, finite value set** (invoice statuses, plans). Each `cases` edge points to one branch; the branches are option-semantics rules.
- **`when` on a `composes` edge** — for **continuous predicates or conditional applicability**. Edge cases are parallel `composes` children of the same parent carrying **mutually exclusive** `when`-conditions (e.g. *"The workspace is tax exempt"* vs. its negation via `NOT`).

There is no `sibling`/`parallel` link type — edge cases are just parallel `composes` edges with exclusive `when`s. (Confirm exact link-type availability and direction with `list_link_types()`.)

## When an enumeration needs its own rule statement

Only when **other rules traverse it via `cases`** — `cases` requires statement targets. If nothing in the rule graph references the value space, the entity description is enough. `cases` edges can also point straight from a parent rule to the option-semantics rules; a separate enumeration rule is only needed to assert closed-set completeness or to reference the value space elsewhere.

## What NOT to do

- Rule `triggers` X — rules don't fire.
- Event `enables` Rule — rules aren't gated by events.
- Rule `establishes` State — events establish states; rules determine the value a state takes (use `valued-by` on the state/property side, pointing at the rule).

## Worked example (sketch)

```
[capability] "An invoice total can be computed"
   governed-by → [R0]

[R0] "Invoice total equals the line subtotal plus tax minus discount"
   composes → [R1 line subtotal]   composes → [R2 tax amount]   composes → [R3 discount]

[R1] "Line subtotal equals the sum of the line amounts"

[R2] "Tax amount equals the line subtotal times the tax rate"
   composes (when NOT "The workspace is tax exempt") → [R2a tax rate]
   composes (when "The workspace is tax exempt") → [Rule: "Tax amount is zero"]

[R3] "Discount is determined by the plan"
   cases → ["Discount on the Starter plan is zero"]   cases → [other plans] … etc.
```

A consumer enters at the capability and follows `governed-by → composes → cases` to assemble the full computation. Decompose into atomic rules over monolithic statements — compound sentences with multiple subjects or qualifying clauses almost always conceal multiple rules.
