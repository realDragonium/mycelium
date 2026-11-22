## Why

Most statements describe our own product, but integrations bring knowledge about other platforms too: what happens there and the steps a user performs there. Nothing records which app or platform a statement belongs to, so readers and agents cannot tell "this happens in our app" from "do this in the payment platform", and an agent curating from one codebase cannot pick out the work that belongs to it.

## What Changes

- A statement gets an optional **system**: the entity of the app or platform the behaviour or step belongs to. Empty means our own product. Help text: "The app or platform this behaviour or step belongs to, such as our app or a payment platform."
- A system is an ordinary entity, so its names, aliases, description, history and links (`our app uses Paylark`, `Paylark contains Paylark Webhooks`) need nothing new. Sections of another platform are entities the system `contains`; the system itself stays at app level.
- `upsert_statement`, `upsert_statements` (batch default with per-item override), `patch_statement` and `ingest` accept `system`, an entity id or exact name. On an update, an omitted `system` keeps the current one and an explicit `null` clears it. Draft operations carry it like any other field. `open_draft` takes no default system.
- `search_statements`, `list_statements`, `grep_statements` and statement-backed `claim_curation_work` kinds filter by system; `"main"` selects statements without one.
- Unscoped reads (`get_statements`, search hits, list and grep rows, Ask's reads) return `system: {entity_id, name}` when set. Audience-scoped reads leave it out.
- Knowledge health counts statements per system.
- `merge_statements` refuses two statements with different systems. `merge_entities` moves system references to the target. `delete_entity` refuses an entity that is still a statement's system, and such an entity is not `unused`.
- The web app shows and edits a statement's system.
- The authoring skills define a system as an app or platform a user can name, ours or a third party's, never a repository, service or internal component. The guide-authoring note on third-party actions refers to the system.

## Decisions

- **Name `system`.** `source` already means a link's start, an audience label's origin and a draft's PR; `provenance` is Ask's citations; `platform` and `app` read poorly for non-software knowledge bases. The skills already speak of "an external system".
- **An entity reference, not a separate registry.** A system is something users name, not a code location, so it needs exactly what entities already provide. A repository pointer can be added to the entity later if needed.
- **Empty means our product.** No product-name setting is needed, and existing statements do not become a backlog.
- **Set per write, not per draft.** A caller has one open draft, and one integration guide mixes steps in both apps, so a draft-level default would be wrong for half its writes.
- **One system per statement.** Behaviour that spans two apps is split into linked statements. A procedure root belongs to the app whose capability it teaches; each step carries its own system.
- **Documentation does not use the system yet.** How guides present systems is decided with the guides work, so documentation prompts, the scoped-read visibility of system entities and external audiences are unchanged here.

## Impact

- Substrate schema gains one nullable column referencing entities; existing statements read as our product. Archives from older builds import unchanged.
- Existing integration statements are assigned through one reviewed draft, found through the entities they mention.
- Out of scope: documentation runs reading the system, descriptive statements about another platform's own behaviour (and anchoring third-party steps to them), and a missing-anchor health check.
