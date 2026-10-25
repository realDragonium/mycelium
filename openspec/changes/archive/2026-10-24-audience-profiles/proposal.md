## Why

An instance shipped one writing profile, written partly as a coding-agent
skill: it walked the server-side writer through tool calls, asked it to pick
an audience label in frontmatter, and called that label a routing hint,
contradicting how audiences now bound what a run reads. No profile served
internal non-technical readers, and nothing stopped a document written for an
internal audience from being published to the same destination as customer
documentation.

## What Changes

- A profile can name the destinations its documents publish to (`destinations`
  slot, admin-only on an existing profile). Publication by people, agents and
  automatic revisions refuses any other destination; a profile without the
  slot publishes anywhere.
- Three packaged starters: `kb-authoring` (knowledge base, seeded as before),
  `help-center` (external non-technical) and `internal-guide` (internal
  non-technical), each with guidance written for the server-side writer,
  disclosure rules matching its audience, and its own templates.
- `GET /api/documentation/starters` returns them. Settings → Documentation
  creates a profile from a starter, and an admin resets a profile's texts to
  one; both go through the existing profile save.
- The seeded `kb-authoring` guidance no longer walks through tool calls or
  lets the writer choose an audience, and its disclosure rules no longer call
  the audience a routing hint.

## Impact

- Specs: documentation.
- Code: profile slots and save, publication, the starters route, the profile
  editor and the document's destination picker.
- Existing profiles and instances need no migration: a missing slot keeps
  today's behaviour, and saved profiles are not changed by the new starter
  files.
