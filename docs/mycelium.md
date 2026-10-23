# Data model and invariants

What the substrate stores and which rules hold on every write. Tool signatures
are not listed here: the MCP schema and the HTTP API docs at `/docs` are
generated from `src/mycelium/server/` and are authoritative.
[The MCP tool manifest](MCP_TOOLS.md) explains which tools MCP advertises.

## Records

The substrate stores three record kinds (entities, names and statements) and
two link kinds (statement to statement, and entity to entity). Names connect
entities to statement text through derived mentions. There are no
entity-to-statement links; schema 14 removed them (see
[the migration notes](ENTITY_STATEMENT_MIGRATION.md)).

An **entity** is a long-lived domain referent: an opaque id, a description and
a preferred name. It has no name field of its own; its identity as text lives
in its names.

A **name** belongs to exactly one entity. Name text is unique case-insensitively
across the whole substrate, so no two entities can share an alias, and a
case-variant lookup resolves to the existing entity. Regular plurals are
generated as names of their own. Names have their own vector index for entity
search and alias-aware retrieval; exact name matching still decides identity.
See [Names and aliases](NAMES_AND_ALIASES.md).

A **statement** is an atomic unit of knowledge: an opaque id, a `kind` and text.
It is the unit that carries meaning, is embedded and searched, and links to
other statements.

A **mention** associates a statement with a *name*, not directly with an entity.
Mentions are derived from the distinctive names found in a statement's text
and recomputed when names change; no caller asserts them. An ambiguous match
also counts while an earlier curator approval of it still matches (see
[Mentions](MENTIONS.md)). Keeping the name preserves which alias matched, and the
mention's entity is whichever entity that name currently belongs to, so
merging entities or moving a name re-points mentions without rewriting text.
See [Mentions](MENTIONS.md).

A **statement link** is a directed, typed edge between two statements. Cycles
and multiple parents are allowed; there is no root statement and no canonical
hierarchy, so any statement is a valid entry point.

A statement link may carry a `when` condition: an expression tree whose leaves
are statements (`{"statement_id": "stm_…"}`) and whose inner nodes are
`{"op": "and" | "or", "of": [...]}` or `{"op": "not", "of": [<one child>]}`.
Conditions keep "A triggers B when C" out of the statement text, and each leaf
can be searched and linked like any other statement. Trees are canonicalized on
write (nested same-op nodes flattened, children deduplicated and sorted) and
hashed. Edges with the same endpoints and type but different conditions are
distinct; the unique key is `(from, to, link_type, when_hash)`, with the
sentinel `NONE` for an unconditional edge.

An **entity link** is a directed, typed edge between two entities for
structural relationships: a product `contains` a module, one provider
`replaces` another. Its type vocabulary is separate from statement link types.
Entity links are not embedded; to find statements about a relationship, search
statements that mention both entities.

Claims *about* a statement or entity (permissions, invariants, defaults,
calculations) are statements of the appropriate kind, linked to what they
govern. The earlier annotation records were removed; older databases may keep
their tables, inert, and archive import skips their records.

## Vocabularies

The installed glossary defines statement kinds, statement link types and
entity link types, each with a description. Read them with
`list_statement_kinds`, `list_link_types` and `list_entity_link_types`.
Seeded statement kinds are `event`, `state`, `capability`, `rule`, `property`,
`procedure`, `action`, `check` and `cause`.

The vocabularies are open: a write with a kind or link type the glossary does
not list is accepted. What the substrate does enforce is below.

## Invariants enforced on write

- **Phrasing.** Every write that creates or replaces statement text runs a
  phrasing check before mutating. A common catalog applies to every kind
  (compound clauses, conditions written into the text, universal claims,
  hedges, an event and its resulting state packed into one statement), and
  `event`, `state` and `capability` add rules of their own. `rule` adds only
  the ban on `will`, because obligations ("must", "may", "is required to") and
  definitions ("is a", "is one of") are what a rule states. Other kinds get the
  `event` rules. A violation rejects the write with
  `{"rejected": true, "violations": [...]}`. `allow_phrasing_violations=true`
  writes anyway and returns the violations as a warning; use it only for text
  whose exact wording is the fact.
- **Link direction.** Link types whose ends have fixed kinds (for example
  `teaches` from a `procedure` to a `capability`, or `performs` from an `action`
  to an `event`) reject an edge that is provably backwards and say to swap the
  ends. The rules live in `link_rules.LINK_DIRECTION`.
- **References.** Foreign keys are enforced on every connection, so a link
  cannot point at a missing statement and a name cannot point at a missing
  entity. A statement used as a condition leaf cannot be deleted until the
  condition is rewritten or removed.
- **Entity links** cannot point an entity at itself.
- **Drafters do not write directly.** For a `drafter` principal, every
  substrate write tool queues its call as an operation on an open draft
  instead of changing the substrate. Other tools that change state (draft
  submission, documentation runs, settings) keep their own role checks; see [Managing users](USERS.md#roles) and
  [Internal draft review](DRAFT_REVIEW.md).
- **History.** Every change to entities, names, statements, mentions,
  statement links and entity links records an event in the history database,
  in the same transaction as the write. Changes to audience labels, knowledge
  gaps, the glossaries, link type aliases and duplicate dismissals are not
  recorded there.

## Storage

All state lives in `MYCELIUM_DATA_DIR` (default `./.mycelium/`):

| File | Holds |
| --- | --- |
| `mycelium.db` | The substrate: entities, names, statements, mentions, links and conditions, glossaries and link type aliases, knowledge gaps, audience labels, historical mention decisions and dismissed duplicate pairs. Also the work queued against it (audience labelling and mention recompute queues, curation attempts and leases), receipts of applied reviewed drafts, and the vector-id mappings |
| `mycelium-history.db` | The audit log of substrate changes |
| `mycelium-drafts.db` | Operational work built on the substrate: drafts, their operations, reviews, review runs and applications; generated documents, their revisions, documentation runs, publication receipts, documentation plans and maintenance decisions; the AI usage ledger. Not disposable |
| `mycelium-auth.db` | Users, tokens, invites, OAuth clients and pending OAuth codes and consents |
| `mycelium-prompts.db` | Instance configuration: editable prompts and writing profiles with their history, audiences, model, draft review and product settings, GitHub connections and credential references (the secrets stay in the environment) |
| `mycelium.vec`, `mycelium-names.vec` | hnswlib indexes of statement and name embeddings |
| `entity-positions.json` | The entity map layout, rebuilt when missing |
| `ask_trace.jsonl`, `ingest_trace.jsonl`, `traces/` | Run traces and profiling output; see [Deployment](DEPLOYMENT.md) |

Instances that predate its removal may also hold `mycelium-ops.db`, which
nothing reads.

`mycelium export` writes the instance to one archive and `mycelium import`
restores it; see [Deployment](DEPLOYMENT.md) for what it leaves out. An index
file missing at startup is rebuilt by re-embedding the stored text, which
needs the embedding service.

Writes are serialized within one process, and each request reads from its own
connection. Serialization does not extend across processes: run one server
process per data directory. Startup upgrades every database in place before
serving: the substrate through versioned migrations, the other databases by
upgrading themselves.

Embeddings come from Ollama (`OLLAMA_URL`, default `http://localhost:11434`;
`EMBED_MODEL`, default `nomic-embed-text`). The indexes are 768-dimensional
cosine indexes; a model with a different dimension also needs `DIM` in
`vector.py` changed and the indexes rebuilt. Entity descriptions are not
embedded.
