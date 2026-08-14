# Guideline sets

A **guideline set** is the writing guidance a documentation-generation run
follows: one set-wide instruction text, one set-wide exposure boundary, plus
one template per document type it can produce. Sets live in the prompt-text
store (`prompt_store`, its own `mycelium-prompts.db`) as ordinary rows, so
adding, editing or replacing one is a tool call — never a code change and
never a redeploy.

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
- `<slot>` is what the row is for. Three shapes:
  - `guidance` — the set-wide instructions: how to research, what counts as
    a fact, how to mark uncertainty, what "done" means. Exactly one per set.
  - `exposure` — the set-wide disclosure boundary: what a finished document
    may reveal and what must stay internal. At most one per set; a set without
    one can still write, but its exposure goes unchecked.
  - a **document type** — `tutorial`, `how-to`, `reference`, `explanation`,
    `troubleshooting`, … — the template for producing that type. As many as
    the set supports.

So `kb-authoring/guidance` and `kb-authoring/how-to`.

## Why one row per document type

A generation run writes one document of one type. With a row per type it
fetches exactly three texts — `<set>/guidance`, `<set>/exposure`, and
`<set>/<type>` — instead of pulling a kilobytes-long omnibus row and slicing
the right section out of it with a parser that the store would then have to
guarantee. Editing one template also versions only that template, so the
history of `kb-authoring/reference` is the history of that template and
nothing else.

The cost is that a set is several rows rather than one, which is why the
`<set>/` prefix exists: the listing groups them by eye, and
`list_prompt_texts(type="guideline-set")` stays the index.

## How a run picks one

`request_documentation` takes `guideline_set` and `document_type`, and both
are optional. What it does not get, the generation run decides for itself and
records on the run row, so a caller who knows what they want can say and a
caller who does not can just describe the document.

The run's choice is bounded by the same listing this document describes: the
loop reads `guideline-set` rows, groups them into sets, and offers the model
exactly those set names and document types to choose between. It is not a
list in code — a set saved with three `save_prompt_text` calls is choosable
on the next run, and one whose rows were retired stops being offered. A pair
that does not appear together is sent back once and then refused; the run
writes nothing rather than falling back to a set nobody configured.

Having chosen, the run fetches its three texts — `<set>/guidance`,
`<set>/exposure`, and `<set>/<type>` — and writes against them. A named set
that is not configured, or a type that set has no template for, is refused at
the door by `request_documentation` instead of failing minutes later inside a
background run.

## Sets that exist

**`kb-authoring`** — seven rows, and the one set that ships. Its sources are
under `src/mycelium/guidelines/kb-authoring/`: one file for set-wide guidance,
one for the exposure boundary, and the files under `templates/` for `tutorial`,
`how-to`, `reference`, `explanation` and `troubleshooting`. Substrate-first:
it instructs the writer to flag facts the substrate does not support rather
than invent them.

The files sit inside the package because that is what a deployment gets. The
wheel carries `src/mycelium/` and the image copies it, the same way the loop
doctrines travel, so startup can seed the set with no checkout and nothing for
an operator to run. An instance with an empty store has nothing to generate
against, and that is not a state worth supporting.

The guidance is written for a generation run, whose only handle on the set is
the store — so it names each template as the sibling row it is, reaches for no
file, and carries no skill frontmatter. The `kb-authoring` skill in `.claude/`
is a consumer of that same text, not a second copy of it: it points a reader
who has a checkout at the guidance file and translates the row names into
paths.

**Two writers, on purpose.** `server.init` seeds through `save_if_absent`,
which never supersedes: a boot against a store that already has these rows
writes nothing, and an operator's edit outlives every restart and every
redeploy. `scripts/seed_guideline_sets.py` writes through `save`, which
compares each row against the stored latest version and appends a new one
where the source has moved on — that is how an author publishes a reworked
template into an instance they hold a checkout of, and `--dry-run` reports
what it would supersede first. Both read the same files and build the same
names, from `mycelium.guidelines`; only the write differs.

Because startup re-seeds them, these seven names cannot be retired.
`retire_prompt_text` refuses them outright rather than letting the next
restart quietly undo the retirement — edit them with `save_prompt_text`
instead.

**`internal-doc`** — four rows, a deliberately minimal set for terse
internal notes. It exists to prove that a variant needs no code: it was added
entirely through the management tools and has no source files, no seeding at
startup and no entry anywhere in `src/`.

## Adding a variant set

Save the rows. That is the whole procedure — `internal-doc` was created with
exactly these calls:

```python
save_prompt_text("guideline-set", "internal-doc/guidance", "…")
save_prompt_text(
    "guideline-set",
    "internal-doc/exposure",
    (
        "These notes are for staff. Internal hostnames may be stated when "
        "useful and supported. Service and repository names, infrastructure "
        "topology, ticket IDs, staff names, and unreleased work may be stated "
        "too. This inverts the external boundary: the question is not whether "
        "a reader is outside the company, but whether the material is secret "
        "whoever is reading.\n\nWithhold live credentials, tokens, and private "
        "keys; personal data about an identifiable person; and material a "
        "third party gave us in confidence. A secret is a secret whoever is "
        "reading.\n"
    ),
)
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
`retire_prompt_text`, which hides the name and keeps its past — unless
startup seeds the name, which it does only for `kb-authoring`.

A set only needs source files when it has to survive a fresh deployment, as
`kb-authoring` does. A set authored directly in the store has none, is not
seeded, and needs neither.
