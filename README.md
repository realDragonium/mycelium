# Mycelium

Mycelium is an AI-native knowledge base substrate exposed over MCP and HTTP. It
stores typed statements, named entities, and links between them in SQLite, with
hnswlib indexes backed by Ollama embeddings.

See `project_vision.md` for the product direction, `SETUP.md` for a guided local
setup, and `docs/mycelium.md` for the data model and its invariants.
See [AI model configuration](docs/AI_MODELS.md) to select Claude or GPT independently for each action.
See [AI prompts](docs/AI_PROMPTS.md) to edit per-action instructions in the UI without redeploying.

See [the documentation workflow](docs/DOCUMENTATION_MODELS.md) to configure writing profiles,
generate and revise documents, and publish GitHub pull requests from the web app.

See [internal draft review](docs/DRAFT_REVIEW.md) for configurable Claude/GPT assessment and
automatic application configuration.

## Requirements

- Python 3.11.4+
- [`uv`](https://docs.astral.sh/uv/)
- Ollama with the configured embedding model (default: `nomic-embed-text`)

```sh
uv sync
ollama pull nomic-embed-text
```

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
are available at `/docs` and the web app at `/ui/`: Ask and Find from any
screen, browse and graph the knowledge base, ingest text, curate
drafts, gaps, names and the glossary, and configure everything under Settings.
[docs/WEB_APP.md](docs/WEB_APP.md) maps its screens and addresses. The former
`/cockpit` app is part of it now; old `/cockpit` links redirect.

To start a separate knowledge base without putting runtime state in this
repository:

```sh
uv run mycelium-init ~/work/my-new-kb
```

The scaffolder creates a `.mcp.json` and an ignored `data/` directory.

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
| `MYCELIUM_ALLOWED_HOSTS` | unset | Hostnames answered besides loopback; see [Deployment](docs/DEPLOYMENT.md#hostnames-the-server-answers) |
| `MYCELIUM_MAX_BODY_BYTES` | `4194304` | Largest request body accepted |
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

MCP advertises 37 tools. Every registered tool also has an HTTP route, so
configuration, curation and draft-review tools remain available over HTTP and in
the UI. See [the MCP tool manifest](docs/MCP_TOOLS.md) for which tools are
advertised over MCP and why.

The read path is:

- `search_statements` for semantic retrieval and shallow graph expansion.
- `get_statements` for full hydration of known statement IDs.
- `find_statement_connections` for several bounded routes between two IDs or
  text-matched statements, or a graph connecting additional `required` statements
  on branches. See [connection search](docs/CONNECTIONS.md).
- `grep_statements` and `list_statements` for literal lookup and enumeration.
- `discover_facts` to check many candidate texts against existing knowledge.
- `ask` for synthesized answers.
- `search_entities`, `list_entities`, and `get_entity` for entity discovery.
- `list_link_types`, `list_statement_kinds`, and `list_entity_link_types` for
  the active vocabularies.

The authoring path is:

- `ingest` to turn prose into a reviewable draft.
- `upsert_statements` then `submit_draft` for statements you already wrote; the
  internal draft reviewer checks their links, duplicates, and contradictions
  against the graph. `set_draft_review_evidence` gives the reviewer your source.
- `get_draft`, `discard_draft_op`, and `list_my_drafts` to inspect and revise drafts;
  curators use `list_drafts` to see the review queue.
- `upsert_entity` and `upsert_name` for the entities statements mention.
- `upsert_statement` to create or wholly replace one statement.
- `patch_statement`, `add_links`, and `remove_links` for focused changes.
- `add_entity_links` and `remove_entity_links` for entity↔entity structure.
- `merge_statements`, `merge_entities`, and `delete_statement` for consolidation
  and removal.
- `report_knowledge_gap` for knowledge you could not find.

Documentation is requested with `request_documentation`, followed with
`get_documentation_run` and `get_generated_document`, and iterated with
`revise_document`.

The MCP schema and `/docs` are the authoritative signature reference. Both are
generated from the decorated functions in `src/mycelium/server/`.

## Skills for agents

`skills/` holds Claude Code skills for agents that work with a Mycelium server,
packaged as the `mycelium` plugin. Install it in Claude Code:

```text
/plugin marketplace add realDragonium/mycelium
/plugin install mycelium@mycelium
```

| Skill | Use it to |
|---|---|
| `mycelium-knowledge-source` | Answer from the knowledge base, cite statements and report gaps |
| `mycelium-authoring` | Write descriptive knowledge: statements, kinds, links, concepts |
| `mycelium-guide-authoring` | Write how-to and troubleshooting knowledge |
| `mycelium-draft` | Research a domain in a codebase and propose it as a reviewed draft |
| `mycelium-draft-review` | Work the draft queue alongside the internal reviewer |
| `mycelium-documentation` | Have the server write, revise and plan documents |
| `mycelium-curation` | Knowledge health, the connect pass, duplicates and gaps |

See [skills/README.md](skills/README.md). A checkout of this repository loads
the same skills through `.claude/skills`.

## Example

Create an entity, write a typed statement, then retrieve it:

```text
upsert_entity({"name": "Login", "description": "User authentication"})

upsert_statements({"statements": [{
  "kind": "capability",
  "text": "Login can authenticate a user with email and password."
}]})

search_statements({
  "query": "How does authentication work?",
  "mentions": ["Login"]
})
```

For multi-statement prose, use `ingest`. An LLM extracts atomic statements,
checks them against existing knowledge, proposes links, and returns a draft for
review. While [internal draft review](docs/DRAFT_REVIEW.md) is on, the draft is
submitted to the reviewer at once.

Historical annotation tables may remain in old databases but are inert. The
current migration runner leaves them intact for compatibility, and archive
imports skip their records rather than converting them into statements.

## Tests

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```

The suite runs on four [pytest-xdist](https://pytest-xdist.readthedocs.io/)
workers by default. Use `uv run pytest -n0` to run it in one process when
debugging with `pdb` or `-s`. Each test gets its own temporary data
directory, and the suite fails a test that starts the server without one.

Ask streaming, combined retrieval, provenance and client compatibility are documented in [docs/ASK.md](docs/ASK.md).
