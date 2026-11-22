## Why

A profile always wrote for an audience, so a document could only draw on statements whose label granted that audience. An internal reference that should rest on the whole knowledge base depended on one audience staying live and including every other, and on no statement being labelled only for an audience that was since retired. A deployment that retired its widest internal audience could not write such a reference at all.

## What Changes

- A profile's audience can be `all-statements`. Its documents are written, reviewed, planned, checked for freshness and exported from every statement and media item, whatever its audience label.
- `all-statements` is not an audience: it is not listed, edited, retired, labelled for or included, and no audience can take its id.
- The writer and reviewer of such a profile are told the reader is internal and nothing is withheld; the profile's own disclosure rules still apply.
- The profile form offers **All statements · no audience**, and `save_writing_profile` accepts `audience: "all-statements"`. As with any audience, only an administrator changes it on an existing profile.

## Impact

- Documents of such a profile, and the website downloaded from it, can hold anything in the knowledge base. Keeping them internal is the operator's responsibility.
- No stored data changes. Profiles that name an audience behave as before.
