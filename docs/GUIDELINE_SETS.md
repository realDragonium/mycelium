# Guideline sets

A **guideline set** is the writing guidance a documentation-generation run
follows: one set-wide instruction text, one set-wide exposure boundary, plus
one template per document type it can produce. Sets live in the prompt-text
store (`prompt_store`, its own `mycelium-prompts.db`) as ordinary rows, so
adding, editing or replacing one is a tool call — never a code change and
never a redeploy.

Open **AI settings → Documentation profiles** in either UI to create, edit,
duplicate or retire profiles and templates. The shared editor also shows text
history and can restore earlier versions. Writers can save and restore;
administrators can retire profiles or remove existing slots. The configured
default profile's last template is protected until another default is selected.

A save checks the profile revision and appends all changed slots atomically.
Conflicts keep local edits visible until you reload. Existing MCP tools use the
same validation; slot-by-slot creation remains supported, and a profile without
a template is shown as incomplete. Templates keep stable names; duplicating a
profile creates a new identity. Audience/disclosure guidance does not change
access permissions on generated documents.

**Advanced AI instructions** in settings edits the existing ingestion, research
and documentation loop doctrines with the same version history and conflict
checks. These doctrines retain their existing protection against retirement.

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

Having chosen, the run reads its three texts together from one store snapshot — `<set>/guidance`,
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

Startup inserts the starter profile atomically only when no guideline-set
history exists. Saved edits and retirement tombstones take precedence, including
after backup restoration; redeploying does not synchronize template files into
saved profiles. A missing starter file leaves no partial profile and does not
prevent the server from starting.

The optional checkout script `scripts/seed_guideline_sets.py` remains an explicit
import tool. Running it can overwrite UI edits with new versions; it is not part
of startup or the normal editing workflow.

**`internal-doc`** — four rows, a deliberately minimal set for terse
internal notes. It exists to prove that a variant needs no code: it was added
entirely through the management tools and has no source files, no seeding at
startup and no entry anywhere in `src/`.

Its `exposure` row is where the two sets are most visibly different, which is
the argument for the slot being a row rather than a constant. `kb-authoring`
writes for a reader who may be outside the company, so internal hostnames,
service names, ticket ids, staff names and unreleased work all stay out.
`internal-doc` writes for staff, so all of those may be stated; what it
withholds is the narrower set that is secret whoever is reading — live
credentials, personal data about an identifiable person, and material a third
party gave us in confidence. A reviewer would reach opposite verdicts on the
same paragraph depending on which set the run resolved, which is exactly what
a set-wide slot is for.

## Adding a variant set

Save the rows. That is the whole procedure — `internal-doc` was created with
exactly these calls:

```python
save_prompt_text("guideline-set", "internal-doc/guidance",  "…")
save_prompt_text("guideline-set", "internal-doc/exposure",  "…")
save_prompt_text("guideline-set", "internal-doc/how-to",    "…")
save_prompt_text("guideline-set", "internal-doc/reference", "…")
```

Then check it:

```python
list_prompt_texts(type="guideline-set")   # the set's rows are in the listing
get_prompt_text("guideline-set", "internal-doc/how-to")
```

Editing a row is another `save_prompt_text` (it appends a version;
`list_prompt_text_versions` shows the history). Withdrawing one is
`retire_prompt_text`, which hides the name and keeps its past. Bundled templates
can also be retired, subject to the configured default reference.

Saved profiles survive deployments and are included in instance backups.
Source files are needed only for the packaged initial examples, not for profiles
authored in the UI or through MCP.

The cockpit's Documentation screen also offers a per-run Claude/GPT choice.
See [Documentation models](DOCUMENTATION_MODELS.md) for server configuration and
how that selection applies to writing and review.
