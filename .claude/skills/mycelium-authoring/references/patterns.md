# Recurring structural patterns

Shapes that recur. They are combinations of the core rules, not primitives. The link types named are **illustrations, not the available set** — fetch and choose from `list_link_types()`. Organised by what catches a mistake.

## The validator already pushes you toward these

Get the shape wrong and `upsert_statement` rejects it; the rejection message points to the fix (§5). Author, read the rejection, correct — you don't need this memorised.

- **Inputs, not packed text** — a condition or input in a statement's text is rejected. The forced shape: minimal event; user-supplied inputs become `property` labels the event `requires`/`accepts`; missing/invalid inputs become `state`s wired as `when` on a rejection edge.

## Nothing rejects these — get them right yourself

These produce a **valid graph that is wrong**. No rejection fires; the error is silent. This is where the reference earns its place.

- **Base + specifics** — an abstract base statement plus the specific-threshold/case children it `contains`. One coarse statement (*"a near-duplicate verdict is assigned from the similarity score"*) passes validation and silently drops the thresholds — the exact under-decomposition this skill exists to prevent. Author the base **and** each case.

- **Same surface, distinct code paths** — two paths that look like one event but differ in guards are **separate statements**. Merging them and attaching the guards to one record passes validation but mis-scopes every guard. Test: can path A be guarded while B isn't, for the same user? → separate.
  ```
  [event] "Statements are retrieved by vector similarity"      ← no guards
  [event] "Statements are retrieved by exact identifier match"
      restricted by "Semantic ranking is disabled for the request"
      restricted by "The query is a bare identifier"
  ```

- **Convergent branches keep distinct conditions** — two branches reaching the same target keep their separate `when`s. Fusing them into one OR-condition because the target matches makes *"which retrievals reach this because the query was a bare identifier?"* unanswerable.

- **Config + effect** — a configured value (`state`) must link to the `event` it changes. The knob alone is an orphan no consumer can interpret. Not rejected — just useless in isolation.

- **Entity data shape** — to document required vs. optional fields at the entity level, add `requires`/`accepts` edges from the entity to the `property` records (and a config `state` if the configured condition must gate other edges via `when`). Neither is forced; absence is silent.

- **Temporal / provider variation** — reify the date or provider as a `state` and link the override (`replaces` / `restricts`). A merged *"sometimes X"* statement is valid and wrong.

## `near_duplicates` in an upsert response

- **≥0.92, same claim** → `merge_statements` immediately.
- **0.85–0.92, related** → link, don't leave isolated.
- **~0.99, mirror pair** (`reader`/`writer`/`admin`, above/below) → expected; keep both.
