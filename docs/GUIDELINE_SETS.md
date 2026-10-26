# Guideline sets

A **guideline set** is the writing guidance a documentation-generation run
follows: one set-wide instruction text, one set-wide exposure boundary, plus
one template per document type it can produce. Sets live in the prompt-text
store (`prompt_store`, its own `mycelium-prompts.db`) as ordinary rows, so
adding, editing or replacing one is a save in the web app, over MCP or an
HTTP request — never a code change and never a redeploy. No profile ships with
the package: a fresh instance has none until an administrator or writer
creates one. The [profile examples](profile-examples/) are texts to paste,
not profiles the server loads.

Over MCP, `list_writing_profiles`, `get_writing_profile`,
`save_writing_profile`, `retire_writing_profile` and
`restore_writing_profile` do what the editor does, with the same validation,
roles and revision check ([MCP tools](MCP_TOOLS.md)). The generic prompt-text
tools read rows (`get_prompt_text`, `list_prompt_texts`) and retire one
(`retire_prompt_text`).

Open **Settings → Documentation → Writing profiles & templates** to create, edit,
duplicate or retire profiles and templates. The shared editor also shows text
history and can restore earlier versions. Writers can save and restore;
administrators can retire profiles or remove existing slots. The configured
default profile's last template is protected until another default is selected.

A save checks the profile revision and appends all changed slots atomically.
Conflicts keep local edits visible until you reload. The profile HTTP operations use the
same validation; slot-by-slot creation remains supported, and a profile without
a template is shown as incomplete. Templates keep stable names; duplicating a
profile creates a new identity. Audience/disclosure guidance does not change
access permissions on generated documents.

**Advanced AI instructions** in settings edits the existing ingestion and
documentation loop doctrines with the same version history and conflict
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
- `<slot>` is what the row is for:
  - `guidance` — the set-wide instructions: how to research, what counts as
    a fact, how to mark uncertainty, what "done" means. Exactly one per set.
  - `exposure` — the set-wide disclosure boundary: what a finished document
    may reveal and what must stay internal. At most one per set. A set without
    one can still write; its documents are then checked for exposure only
    against the audience's description.
  - `audience` — the id of the audience the set writes for (see
    [Audiences](AUDIENCES.md)). At most one per set; without one the set
    writes for the default internal audience. Set it through the profile
    editor; only an admin changes it.
  - `maintenance` — what happens when one of the set's documents goes out of
    date: `manual` (the default when the row is absent), `propose` or
    `auto-revise`; see [Documentation](DOCUMENTATION_MODELS.md). At most one
    per set.
  - `planning`, `plan_review` and `delivery` — the planning policy, who
    decides proposed plan items, and whether agents may deliver; see
    [Documentation planning](DOCUMENTATION_PLANNING.md). A missing row reads
    as the default (`off`, `person`, `people`).
  - `destinations` — the names of the documentation destinations the set's
    documents may be published to, one per line. Without one they may be
    published to any destination. Only an admin changes it on an existing
    set.
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
list in code — a set saved with three rows is choosable
on the next run, and one whose rows were retired stops being offered. A pair
that does not appear together is sent back once and then refused; the run
writes nothing rather than falling back to a set nobody configured.

Having chosen, the run reads its three texts together from one store snapshot — `<set>/guidance`,
`<set>/exposure`, and `<set>/<type>` — and writes against them. A named set
that is not configured, or a type that set has no template for, is refused at
the door by `request_documentation` instead of failing minutes later inside a
background run.

## Example profiles

[`docs/profile-examples/`](profile-examples/) holds three product-neutral
examples to copy into a new profile:

| Example | Written for | Templates |
|---|---|---|
| [Knowledge base](profile-examples/knowledge-base.md) | the profile's audience, default internal | `tutorial`, `how-to`, `reference`, `explanation`, `troubleshooting` |
| [Help center](profile-examples/help-center.md) | external non-technical: people using the product | `how-to`, `troubleshooting`, `explanation` |
| [Internal guide](profile-examples/internal-guide.md) | internal non-technical: support, sales, customer success | `reference`, `explanation`, `how-to`, `troubleshooting` |

The server never reads them. Their guidance is written for the server-side
writer: the run already gathers, files gaps and emits, so an example says
what the document contains, how it reads and how long it is, and never asks
the reader a question, names a file or path, or walks through tool calls.

Earlier builds seeded a `kb-authoring` profile on first start. An instance
that has it keeps it as saved data; nothing in the package refers to its
texts any more. The documentation setting's default profile is still named
`kb-authoring`, and a fresh instance keeps that name as its default until an
administrator chooses a profile that exists.

## Which profile a run writes against

Everything about what to write for whom — guidance, disclosure rules,
templates, the audience and its description — comes from the profile and its
audience. The code holds only the writer's mechanics: how a run gathers and
cites, the output schema and the review checks. An agent working a
documentation task gets the whole profile in its brief (`profile`), and
the skills tell it to follow that profile, so they carry no writing advice of
their own.

**`internal-doc`** (in the tests) is a deliberately minimal set for terse
internal notes: guidance, disclosure rules, a `how-to` and a `reference`
template, saved through the profile editor's routes. Its `exposure` row is
where it differs most from a public profile: it may state internal hostnames,
service names, ticket ids, staff names and unreleased work, and withholds only
what is secret whoever is reading — live credentials, personal data about an
identifiable person, and material a third party gave us in confidence. A
reviewer would reach opposite verdicts on the same paragraph depending on
which profile the run resolved, which is exactly what a set-wide slot is for.

## Adding a variant set

Save the rows. That is the whole procedure: create the profile in
**Settings → Documentation**, with `save_writing_profile` over MCP, or in one
request with `PUT /api/documentation/profiles/<set>`, whose body carries the guidance,
exposure, audience and templates (`internal-doc` has guidance, exposure, a
`how-to` and a `reference` template).

Then check it:

```python
list_prompt_texts(type="guideline-set")   # the set's rows are in the listing
get_prompt_text("guideline-set", "internal-doc/how-to")
```

Editing a row appends a version (`PUT /api/documentation/prompts`;
`GET /api/documentation/prompts/history` shows the history and
`POST /api/documentation/prompts/restore` brings an earlier one back).
Withdrawing one is
`retire_prompt_text`, which hides the name and keeps its past, subject to the
configured default reference. `retire_writing_profile` retires a whole
profile, and `restore_writing_profile` brings it back with the texts it held
when it was retired. A profile retired by an earlier build is restored text by
text from its history.

Saved profiles survive deployments and are included in instance backups.

The Documents screen also offers a per-run Claude/GPT choice.
See [Documentation models](DOCUMENTATION_MODELS.md) for server configuration and
how that selection applies to writing and review.
