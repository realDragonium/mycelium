# Exposure review for knowledge-base articles

Review the finished document as material that may reach an external reader.
The frontmatter may name its audience as `external`, `internal`, or `both`,
but this set uses the most cautious boundary for all three.
An audience label does not make sensitive material safe to publish.
The writer should apply the same boundary before handing the document over.

## What must stay out

Internal hostnames and IP ranges must not appear.
Do not expose internal service or repository names.
Do not describe infrastructure topology that is not already public.
Replace those details with the reader-visible product boundary or omit them.

Do not name customers or include tenant identifiers.
Do not include names, contact details, account details, or other information
that identifies an individual.
Examples and diagnostics must be anonymised rather than merely shortened.

Never include credentials, tokens, private keys, or connection strings.
Treat a value as live unless the document makes clear that it is a synthetic
placeholder that cannot authenticate or connect to anything.

Do not present unreleased or roadmap capability as available behaviour.
Future work may appear only when it is already published as such and the
wording preserves that status.
Internal ticket identifiers and staff names must not appear.

Do not put substrate statement ids in the document body.
Provenance travels beside the document, not inside the text readers receive.

Describe a security control only to the depth needed to use it safely.
Withhold implementation detail that would help someone bypass, evade, or
weaken the control rather than configure, operate, or recover from it.

## What may be revealed

Published product behaviour may be stated when the substrate supports it.
Configuration that the reader controls may be named and explained.
Documented limits and defaults may be given precisely.
Error text that a user actually sees may be quoted when it helps them act.
These permissions do not override any exclusion above.

## How to decide a hard case

First identify the exact fact the section needs the reader to understand.
Then separate its reader-visible effect from its internal implementation.
Check each half independently against the exclusions above.

A substrate statement holding an internal detail is evidence that the detail
exists; it is not permission to publish that detail.
If the reader-visible half is supported, write that half and leave the
internal half out.
Do not hedge, euphemise, or partially encode the internal half into the body.
If removing it makes the remaining claim unsupported or unusable, omit the
claim and leave the gap for a safer source or formulation.

Return the document when any forbidden detail remains or when a permitted
claim depends on revealing one.
Pass exposure review only when every included detail is both useful to the
reader and inside this boundary.
