# Mycelium

Mycelium is an AI-native knowledge base substrate exposed over MCP and HTTP. It
stores typed statements, named entities, and links between them in SQLite, with
hnswlib indexes backed by Ollama embeddings.

See `project_vision.md` for the product direction, `SETUP.md` for a guided local
setup, and `docs/mycelium.md` for detailed contracts.
See [internal draft review](docs/DRAFT_REVIEW.md) for optional GPT assessment and
automatic application configuration.

## Requirements

- Python 3.11.4+
- [`uv`](https://docs.astral.sh/uv/)
- Ollama with the configured embedding model (default: `nomic-embed-text`)

```sh
uv sync
ollama pull nomic-embed-text
```

Install the optional CPU NLI classifier with `uv sync --extra nli`. Configure
it with `MYCELIUM_NLI_MODEL`, `MYCELIUM_NLI_CONFIDENCE`, and
`MYCELIUM_NLI_MAX_PAIRS`.

## Run

Start the stdio MCP server:

```sh
uv run python -m mycelium
```

Start the HTTP transport and browser UI:

```sh
uv run mycelium-http
```

The HTTP server listens on `127.0.0.1:8765` by default. Interactive API docs
are available at `/docs` and the browser UI at `/ui/`.

To start a separate knowledge base without putting runtime state in this
repository:

```sh
uv run mycelium-init ~/work/my-new-kb
```

The scaffolder creates a `.mcp.json`, ignored `data/`, and an `ingest/`
directory.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MYCELIUM_DATA_DIR` | `./.mycelium` | SQLite and vector-index directory |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `EMBED_MODEL` | `nomic-embed-text` | 768-dimensional embedding model |
| `MYCELIUM_HTTP_HOST` | `127.0.0.1` | HTTP bind host |
| `MYCELIUM_HTTP_PORT` | `8765` | HTTP bind port |
| `MYCELIUM_AUTH` | `off` | Require authenticated HTTP and remote MCP requests when `on` |
| `MYCELIUM_SESSION_SECRET` | unset | Cookie-signing secret; required when authentication is on |
| `MYCELIUM_INSTRUCTIONS` | unset | Deployment-specific MCP guidance |

Keep the default loopback bind for unauthenticated use. Before binding HTTP to a
non-loopback address, set `MYCELIUM_AUTH=on` and provide a strong, private
`MYCELIUM_SESSION_SECRET`.

The same substrate backs both transports, but write serialization is
process-local. Only one server process may use a data directory at a time.

## Current tool model

Statements are typed claims. Their `kind` describes the shape of the claim,
such as `event`, `state`, or `capability`. Entity mentions are derived from
names found in statement text. Statement links use `to_id` and `from_id`.

The main read path is:

- `search_statements` for semantic retrieval and shallow graph expansion.
- `get_statements` for full hydration of known statement IDs.
- `survey_statements` and `ask` for broader retrieval and synthesized answers.
- `search_entities`, `list_entities`, and `get_entity` for entity discovery.
- `list_link_types`, `list_statement_kinds`, and `list_entity_link_types` for
  the active vocabularies.

The main authoring path is:

- `ingest_text` or `submit_connected_batch` to create a reviewable draft.
- `get_draft`, `discard_draft_op`, and `submit_draft` to inspect and revise it.
- `upsert_statement` and `upsert_statements` for direct typed writes.
- `patch_statement`, `add_links`, and `remove_links` for focused changes.
- `merge_statements` and `delete_statement` for consolidation and removal.

The MCP schema and `/docs` are the authoritative signature reference. Both are
generated from the decorated functions in `src/mycelium/server.py`.

## Example

Create an entity, write a typed statement, then retrieve it:

```text
upsert_entity({"name": "Login", "description": "User authentication"})

upsert_statement({
  "kind": "capability",
  "text": "Login can authenticate a user with email and password.",
  "links": []
})

search_statements({
  "query": "How does authentication work?",
  "mentions": ["Login"]
})
```

For multi-statement prose, prefer `ingest_text`. It segments the text, assigns
statement kinds, proposes links, and returns a draft for review.

Historical annotation tables may remain in old databases but are inert. The
current migration runner leaves them intact for compatibility, and archive
imports skip their records rather than converting them into statements.

## Tests

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```
