# Guideline sets

A **guideline set** is the writing guidance a documentation-generation run
follows: one set-wide instruction text plus one template per document type it
can produce. Sets live in the prompt-text store (`prompt_store`, its own
`mycelium-prompts.db`) as ordinary rows, so adding, editing or replacing one
is a tool call — never a code change and never a redeploy.

This document is the convention. Nothing enforces it: `type` and `name` are
free strings and the store never enumerates them. That is the point — a new
documentation variant is data.

## The convention

**Type** — `guideline-set`, for every row of every set.

One type for the whole kind, so `list_prompt_texts(type="guideline-set")`
answers "which sets exist and what can each of them write?" in one call. It
is distinct from every other steering-text type in the store (loop doctrines,
ask preambles, server instructions), so guideline-set names can never collide
with theirs.

**Name** — `<set>/<slot>`.

- `<set>` is the variant's name, kebab-case: `kb-authoring`, `internal-doc`.
  It is the shared prefix that makes a set greppable in a listing.
- `<slot>` is what the row is for. Two shapes:
  - `guidance` — the set-wide instructions: how to research, what counts as
    a fact, how to mark uncertainty, what "done" means. Exactly one per set.
  - a **document type** — `tutorial`, `how-to`, `reference`, `explanation`,
    `troubleshooting`, … — the template for producing that type. As many as
    the set supports.

So `kb-authoring/guidance` and `kb-authoring/how-to`.

## Why one row per document type

A generation run writes one document of one type. With a row per type it
fetches exactly two texts — `<set>/guidance` and `<set>/<type>` — instead of
pulling a kilobytes-long omnibus row and slicing the right section out of it
with a parser that the store would then have to guarantee. Editing one
template also versions only that template, so the history of
`kb-authoring/reference` is the history of that template and nothing else.

The cost is that a set is several rows rather than one, which is why the
`<set>/` prefix exists: the listing groups them by eye, and
`list_prompt_texts(type="guideline-set")` stays the index.

## Sets that exist

**`kb-authoring`** — six rows, seeded by `scripts/seed_guideline_sets.py`:
`guidance` from `guidelines/kb-authoring/guidance.md`, plus `tutorial`,
`how-to`, `reference`, `explanation` and `troubleshooting` from
`.claude/skills/kb-authoring/templates/`. Substrate-first: it instructs the
writer to flag facts the substrate does not support rather than invent them.

The guidance has a source of its own, separate from the kb-authoring skill's
`SKILL.md`, because the two address readers with different reach. The skill
runs in a repo checkout and points at its templates by path; a generation run
holds the store and nothing else, and reaches the same templates as sibling
rows. So the guidance names rows, and carries no skill frontmatter — that
metadata dispatches a local skill and tells a generation run nothing. A
template reads the same to either reader, which is why those five rows are
the skill's own files.

The seed compares each row against the stored latest version and appends only
what differs, so re-running it against unchanged sources writes nothing. The
store is append-only — the seed never rewrites a version, and an operator's
edit is only ever superseded by a later save.

**`internal-doc`** — three rows, a deliberately minimal set for terse
internal notes. It exists to prove that a variant needs no code: it was added
entirely through the management tools and has no seed script, no source files
and no entry anywhere in `src/`.

## Adding a variant set

Save the rows. That is the whole procedure — `internal-doc` was created with
exactly these calls:

```python
save_prompt_text("guideline-set", "internal-doc/guidance", "…")
save_prompt_text("guideline-set", "internal-doc/how-to",   "…")
save_prompt_text("guideline-set", "internal-doc/reference", "…")
```

Then check it:

```python
list_prompt_texts(type="guideline-set")   # the set's rows are in the listing
get_prompt_text("guideline-set", "internal-doc/how-to")
```

Editing a row is another `save_prompt_text` (it appends a version;
`list_prompt_text_versions` shows the history). Withdrawing one is
`retire_prompt_text`, which hides the name and keeps its past.

A set only needs a seed script when its source of truth is files in this
repo, as `kb-authoring`'s is. A set authored directly in the store does not
have one, and does not need one.
