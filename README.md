# Mycelium

AI-native knowledge base substrate, exposed over MCP. Naive MVP — single-writer
SQLite + in-memory hnswlib + Ollama embeddings. See `project_vision.md` for
the why.

> **First time setting this up?** Follow `SETUP.md` for a step-by-step
> walkthrough from a fresh laptop to a working substrate with Claude
> Desktop and the browser UI both connected. The rest of this README is
> reference material.

## Prerequisites

1. **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).
2. **Ollama** running locally with the embedding model pulled:
   ```sh
   # https://ollama.com/download
   ollama serve &
   ollama pull nomic-embed-text
   ```

## Install

```sh
uv sync
uv run python -m spacy download en_core_web_sm  # phrasing validation model
```

## Run the server

Two transports, same substrate underneath. Both read/write the same
`MYCELIUM_DATA_DIR` (no concurrency safety — single-writer is the rule).

### MCP over stdio

```sh
uv run python -m mycelium
```

Used by Claude Desktop and other MCP clients.

### Standing up a new knowledge base

To author into a *separate* substrate (different corpus, different
data dir, no risk of binary state landing in this repo), use the
scaffolder:

```sh
uv run mycelium-init ~/work/my-new-kb
```

Creates `~/work/my-new-kb/` with a `.mcp.json` already wired to this
Mycelium installation, a `.gitignore` excluding the substrate state,
and empty `data/` and `ingest/` subdirs. Open Claude Code in that
directory and approve the MCP via `/mcp`.

### HTTP via FastAPI

```sh
uv run mycelium-http
```

Listens on `127.0.0.1:8765` by default. Each tool gets its own endpoint
named after it (kebab-cased) — see the table below. Interactive docs at
<http://127.0.0.1:8765/docs>. A read-only browser UI is bundled at
<http://127.0.0.1:8765/> (root redirects to `/ui/`); it loads the
substrate via the HTTP-only `GET /api/data` endpoint that is not exposed
over MCP.

Data is persisted under `./.mycelium/` (SQLite at `mycelium.db`, vector
index at `mycelium.vec`). Override with `MYCELIUM_DATA_DIR`.

### Environment variables

| var | default | meaning |
|---|---|---|
| `MYCELIUM_DATA_DIR` | `./.mycelium` | where the db + vector index live |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama HTTP endpoint |
| `EMBED_MODEL` | `nomic-embed-text` | embedding model (must be 768-dim) |
| `MYCELIUM_HTTP_HOST` | `127.0.0.1` | FastAPI bind host |
| `MYCELIUM_HTTP_PORT` | `8765` | FastAPI port |
| `MYCELIUM_INSTRUCTIONS` | *(unset)* | Server-level prompt surfaced to MCP clients on initialize. The strongest "when to reach for this server" signal — name the product, list the kinds of questions the substrate covers, give a fallback for when nothing relevant comes back. Per-deployment, since Mycelium itself is generic. |

## Connect from Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mycelium": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mycelium",
        "run",
        "python",
        "-m",
        "mycelium"
      ],
      "env": {
        "MYCELIUM_DATA_DIR": "/absolute/path/to/mycelium/.mycelium",
        "MYCELIUM_INSTRUCTIONS": "This server is the internal knowledge base for [PRODUCT]. Reach for these tools whenever a question could be product-specific — features, flows, behaviors, integrations, configurations, who-is-allowed-to-X, what-happens-when-Y. Default: search_behaviors depth=1, min_score=0.6. If nothing relevant comes back (top < 0.5), answer from general knowledge instead."
      }
    }
  }
}
```

Restart Claude Desktop. The Mycelium tools should appear in the tools panel.

`MYCELIUM_INSTRUCTIONS` is what tells Claude *when* to reach for this
server without the user having to say "this is a product question."
The text above is a sketch — name your product, list the kinds of
questions the substrate covers in the wording users actually use, and
give a clear fallback for when search returns nothing relevant. The
instruction lands in the system prompt alongside the tool list, so
specificity wins.

## Tools (the entire v1 surface)

A single `@tool` decorator in `server.py` registers a function with both
transports — adding a tool gives you both an MCP tool and a FastAPI
endpoint at `/<kebab-case-name>` for free. The HTTP method is `GET` if
the tool takes no arguments, `POST` otherwise; the request body's
Pydantic schema is derived from the function signature.

| MCP tool | HTTP endpoint | description |
|---|---|---|
| `search_behaviors(query, limit=10, min_score=-1.0, depth=0, direction="both", mentions=[])` | `POST /search-behaviors` | Vector search. `min_score` is a cosine-similarity floor (range `[-1, 1]`, practical floors 0.5–0.8). `depth>0` walks the link graph from each direct hit; `direction` is `"both"`, `"children"`, or `"parents"`. Optional `mentions` is a list of name texts — when set, hits must mention every named entity (AND semantics). Each hit's `mentions` is `[{name_id, name, entity_id}]`. |
| `get_behavior(id)` | `POST /get-behavior` | Direct lookup by id. Returns `{id, text, mentions, links, incoming_links}` — same shape as a search hit plus an `incoming_links` field listing every behavior that points at this one. 400 on unknown id. |
| `get_entity(id)` | `POST /get-entity` | Direct lookup by id. Returns `{id, description, names: [{id, text}], links: [{to_entity_id, link_type}], incoming_links: [{from_entity_id, link_type}]}` with all attached aliases plus entity↔entity edges in both directions. 400 on unknown id. |
| `list_entities(prefix="", limit=50, offset=0)` | `POST /list-entities` | Paginated, sorted by primary name. Optional case-insensitive `prefix` filter. Returns `{total, entities: [{id, name, description}]}`. |
| `list_behaviors(limit=50, offset=0, entity_id?, name?)` | `POST /list-behaviors` | Paginated, insertion order. Optional `entity_id` or `name` (mutually exclusive) restricts to behaviors that mention that entity; passing a name collapses across all its aliases. Returns `{total, behaviors: [{id, text}]}` — text only, use `get_behavior` for full structure. |
| `upsert_entity(name, description)` | `POST /upsert-entity` | Create or update by name. If `name` already exists, updates that entity's description; otherwise creates a fresh entity + name. |
| `upsert_behavior(text, mentions, links, id?, incoming_links?, strict_mentions?)` | `POST /upsert-behavior` | Embed and store a behavior. `mentions` is a list of name texts; unknown texts auto-create unless `strict_mentions=True`. Outgoing `links` items are `{to_behavior_id, link_type, when_behavior_id?}` and are wholesale-replaced on update. `incoming_links` items are `{from_behavior_id, link_type, when_behavior_id?}` and are idempotent-insert. The optional `when_behavior_id` reifies a condition as a third behavior — e.g. *A — triggers (when C) → B*. Every referenced behavior id is validated before any mutation. **Response includes `near_duplicates: [{id, text, score}]`** — any existing behavior at cosine ≥ 0.85 to the new text. Soft signal, never blocks the write. |
| `upsert_behaviors([{text, mentions?, links?, incoming_links?}], strict_mentions?)` | `POST /upsert-behaviors` | Bulk-insert behaviors in one atomic call. Sibling cross-references via `"@N"` (0-based index) in any `to_behavior_id`, `from_behavior_id`, or `when_behavior_id`. References validated up front; nothing is written if any ref is invalid. Returns `{behavior_ids: [...]}` in input order, plus `near_duplicates: {<behavior_id>: [...]}` covering both pre-existing matches and freshly-inserted siblings. |
| `replace_text(id, text)` | `POST /replace-text` | Update only the text of an existing behavior. Re-embeds; mentions and links untouched. |
| `add_mentions(id, mentions, strict_mentions?)` | `POST /add-mentions` | Append mentions to an existing behavior. Idempotent (already-present skipped). |
| `remove_mentions(id, mentions)` | `POST /remove-mentions` | Drop specific mentions from an existing behavior. Missing ones are no-ops. |
| `upsert_name(text, entity_id)` | `POST /upsert-name` | Alias an existing entity. Idempotent if the name already points at `entity_id`; 400 if taken by a different entity (use `move_name` or `merge_entities`). |
| `merge_entities(from_entity_id, into_entity_id)` | `POST /merge-entities` | Reassign every name from `from` to `into` and delete the source entity. Behavior mentions follow the names automatically. |
| `merge_behaviors(from_behavior_id, into_behavior_id)` | `POST /merge-behaviors` | Merge one Behavior into another when the source's meaning lives on through the target (duplicates, parallel drafts, "this was wrong, replaced by X"). Mentions and both link directions are unioned onto the target (deduped on `name_id` / `(other, link_type, when_behavior_id)`); self-loops created by the merge are dropped; source's vector is marked deleted in hnswlib; source record is removed. Returns counts moved. |
| `delete_behavior(id)` | `POST /delete-behavior` | Permanently delete a behavior with no replacement (feature removed, fact obsolete, etc.). Cascades: mentions, incoming links, outgoing links, and any edge anywhere referencing this as `when_behavior_id` are removed; vector slot is freed for reuse. Returns cascade counts. For "this is a duplicate of X" use `merge_behaviors` instead so relationships survive on the target. |
| `move_name(name_id, to_entity_id)` | `POST /move-name` | Reassign one name to a different entity. Name text unchanged; behaviors that mentioned it now report the new entity_id. Combine with `upsert_entity` to split a name into its own entity. |
| `add_links([{from_behavior_id, to_behavior_id, link_type, when_behavior_id?}])` | `POST /add-links` | Bulk-insert behavior→behavior typed edges between *existing* behaviors, optionally conditioned on a third behavior via `when_behavior_id`. Idempotent (`INSERT OR IGNORE`); same `(from, to, type)` with vs without a `when` are *distinct* edges. Validates every behavior id up front. |
| `remove_links([{from_behavior_id, to_behavior_id, link_type, when_behavior_id?}])` | `POST /remove-links` | Bulk-delete the matching edges. Match is exact on the `when` field — omitting it removes only the unconditional edge. Missing edges are a no-op. |
| `list_link_types()` | `GET /list-link-types` | Snapshot of `link_type` values currently materialised on at least one `behavior_links` row. NOT the substrate's allowed vocabulary — the vocabulary is open. To learn what specific types mean, search behaviors that describe them. |
| `add_entity_links([{from_entity_id, to_entity_id, link_type}])` | `POST /add-entity-links` | Bulk-insert entity→entity typed edges. For structural relationships between long-lived entities — parent/subsidiary, kind-of, partner-of, replaces, etc. — distinct from behavior-links (`add_links`) which connect atomic facts. Idempotent; rejects self-loops; validates every entity id up front. |
| `remove_entity_links([{from_entity_id, to_entity_id, link_type}])` | `POST /remove-entity-links` | Bulk-delete entity→entity edges. Missing edges are a no-op. |
| `list_entity_link_types()` | `GET /list-entity-link-types` | Snapshot of `link_type` values currently materialised on at least one `entity_links` row. Separate vocabulary from behavior-link types. |
| `find_duplicates(threshold=0.92, limit=50)` | `POST /find-duplicates` | Audit the substrate for near-duplicate behavior pairs by walking every behavior's vector and reporting pairs whose cosine similarity is at or above `threshold`. Sorted descending, capped at `limit`. Default 0.92 surfaces high-confidence duplicates; drop to 0.85 for "related, possibly worth linking instead". Each pair: `{a_id, a_text, b_id, b_text, score}`. |
| `grep_behaviors(query, case_sensitive=False, entity_id?, name?, limit=50, offset=0)` | `POST /grep-behaviors` | Literal substring search over behavior `text`. Complements `search_behaviors` (vector) with deterministic case-insensitive substring matching for exact phrases, identifiers, or quoted strings. Glob/regex characters in `query` are matched literally. Optional entity filter via `entity_id` or `name`. Returns `{total, behaviors: [{id, text}]}`. |
| `discover_facts(texts, exists_threshold=0.85, near_threshold=0.6, matches_per_text=5)` | `POST /discover-facts` | Bulk pre-write classifier: for each candidate text, embeds it, queries the index, and returns `{text, status, matches}` where `status` is `"exists"` (top match ≥ `exists_threshold`), `"near"` (≥ `near_threshold`), or `"new"`. Compresses the per-fact discovery loop into a single call. Match `text` is truncated to a 100-char snippet. |

### HTTP-only endpoints (not exposed via MCP)

These exist purely to back the bundled web UI; they are not registered
as MCP tools.

| HTTP endpoint | description |
|---|---|
| `GET /` | Redirects to `/ui/`. |
| `GET /ui/*` | Static assets for the read-only browser UI. |
| `GET /api/data` | Dumps the entire substrate as `{entities, names, behaviors, links}` for the UI to render in-memory. |

### Data model

Three record kinds, two link kinds. Names are first-class — every entity
reference flows through a name, and `behavior_mentions` records which
name a behavior used (not just which entity), so `merge_entities` and
`move_name` preserve provenance.

```
entities(id, description)
names(id, text UNIQUE, entity_id → entities)
behaviors(id, text)
behavior_mentions(behavior_id → behaviors, name_id → names)   -- which name the writer chose
behavior_links(from_behavior_id, to_behavior_id, link_type, when_behavior_id?)
                                                          -- when_behavior_id reifies a condition;
                                                          -- unique key is (from, to, type, COALESCE(when, ''))
entity_links(from_entity_id, to_entity_id, link_type)     -- structural entity↔entity edges
                                                          -- (parent/subsidiary, kind-of, etc.)
```

Propositions that *hold* (permissions, invariants, properties) rather
than events that *fire* are modeled as ordinary records with a rule- or
property-flavored `kind`, linked to what they govern. (A separate
annotation subsystem once covered this; it was deprecated and removed.)

## Manual smoke test

In Claude Desktop, exercise each tool:

1. `upsert_entity({"name": "Login", "description": "User authentication surface"})`
   → returns an `entity_id`.
2. `upsert_behavior({"text": "User logs in with email and password",
   "mentions": ["Login", "Email"], "links": []})`
   → returns a `behavior_id`. Note `Email` is auto-created.
3. `upsert_behavior({"text": "Server issues a session token after login",
   "mentions": ["Session"], "links": [{"to_behavior_id": "<beh from step 2>",
   "link_type": "triggered_by"}]})`
   → second behavior, linked to the first.
4. `list_link_types()` → `["triggered_by"]`.
5. `search_behaviors({"query": "how does authentication work"})` →
   should return both behaviors with similarity scores.
6. `upsert_name({"text": "sign-in", "entity_id": "<Login id>"})` → alias.

## Tests

```sh
uv run pytest
```

Store, vector, and HTTP layers have unit coverage. The Ollama embedding
client and the MCP wire layer are exercised by the manual smoke test above.

## Non-goals (in MVP)

No concurrent-write safety, reranking, fuzzy-name matching, name embeddings,
auth, web UI, query language, or migrations. We wipe and rebuild during MVP
iteration.
