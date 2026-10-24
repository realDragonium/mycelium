## Why

What to write for whom is the instance's decision, not the package's. The
package seeded a `kb-authoring` profile and offered starter profiles from
files, the audience labeller's default carried its own rule about what
external audiences never get, and an agent working a documentation task got
the profile only woven into a prompt, while the skills added advice of their
own for particular audiences. Profiles could not be managed over MCP at all.

## What Changes

- No profile ships with the package. Startup seeds none, the starter files,
  `GET /api/documentation/starters`, the editor's starter actions and the
  `seed_guideline_sets.py` script are removed. Example profiles are plain
  text in `docs/profile-examples/`, which the server never reads. A profile
  seeded by an earlier build stays as saved data.
- MCP tools `list_writing_profiles`, `get_writing_profile`,
  `save_writing_profile`, `retire_writing_profile` and
  `restore_writing_profile`, through the editor's validation, roles and
  revision check. Restoring a retired profile brings back the texts it held
  when it was retired.
- Documentation, document review, documentation planning and plan review
  task briefs carry the whole profile (`profile`). The skills tell the agent
  to follow it and carry no per-audience writing advice.
- The audience labelling default no longer lists what external audiences
  never get; the audience descriptions say it. An instance that ran with the
  old default and never saved its own keeps the old text as a saved
  `upgrade` version. The seeded External non-technical description names
  what the old rule added.
- Saving documentation settings keeps a default profile name no profile has
  yet, so a fresh instance can configure destinations before creating one.

## Impact

- Specs: documentation, agent-tasks, audiences, ai-providers.
- No schema change. Startup writes one prompt version on instances that ran
  with the old labelling default.
