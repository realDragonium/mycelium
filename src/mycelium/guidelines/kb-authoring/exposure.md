# What a knowledge-base article may reveal

This set writes for a reader who is not in the room and may not be in the
company. An article's frontmatter names its audience as `external`, `internal`
or `both`, but the boundary below holds for all three: an audience label is a
routing hint, not a control, and a document that leaks has leaked wherever it
was filed.

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

**The run's own bookkeeping.** Substrate statement ids do not belong in the
body. Provenance travels beside the document, and a reader who cannot resolve
an id is being shown a reference to nothing.

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
