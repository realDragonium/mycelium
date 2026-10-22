# Mycelium setup guide

This guide starts a local Mycelium substrate over MCP and HTTP.

## 1. Install requirements

Install Python 3.11.4 or later, [`uv`](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/download). Start Ollama:

```sh
ollama serve
```

In another terminal, pull the default embedding model, clone the repository,
and install its dependencies:

```sh
ollama pull nomic-embed-text
git clone https://github.com/realDragonium/mycelium.git
cd mycelium
uv sync
uv run pytest
```

The tests use temporary data and fake embeddings, so they do not need a live
Ollama server.

## 2. Start the server

For the stdio MCP transport:

```sh
uv run python -m mycelium
```

For HTTP and the browser UI:

```sh
uv run mycelium-http
```

Keep HTTP on its default loopback address for unauthenticated local use. Before
binding it to a non-loopback address, enable authentication and supply a strong,
private session secret to the server process:

```sh
MYCELIUM_AUTH=on MYCELIUM_SESSION_SECRET='<random-secret>' uv run mycelium-http
```

Open <http://127.0.0.1:8765/ui/> for the web app or
<http://127.0.0.1:8765/docs> for the generated HTTP API reference. The web app's
sidebar groups screens into Explore, Add knowledge and Curate; Settings holds
tokens, members, models, prompts, draft review, limits and publishing. See
[docs/WEB_APP.md](docs/WEB_APP.md).

Both transports use `./.mycelium` unless `MYCELIUM_DATA_DIR` points elsewhere.
Write serialization is process-local, so run only one server process against a
data directory at a time. Stop one transport before starting the other with the
same directory.

## 3. Connect an MCP client

Configure the client to launch Mycelium from this checkout. For Claude Desktop:

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
        "MYCELIUM_INSTRUCTIONS": "Use this server for questions about PRODUCT. Search statements first and answer from general knowledge when no relevant statement is found."
      }
    }
  }
}
```

Restart the client after saving its configuration. The exact tool list comes
from the `mycelium.server` package (`src/mycelium/server/`); `README.md` describes the main read and authoring
paths.

## 4. Use a separate knowledge base

Keep a real corpus and its runtime state outside the source checkout:

```sh
uv run mycelium-init ~/work/my-new-kb
```

This creates a workspace with its own `.mcp.json` and ignored `data/` directory.
Open the workspace in your MCP client and approve its server configuration.

## 5. Add data

For prose, call `ingest`. It extracts typed statements, proposes links, and
returns a draft. Inspect the draft with `get_draft`, remove unwanted operations
with `discard_draft_op`, then submit it with `submit_draft`.

For direct writes, create named entities with `upsert_entity`, then use
`upsert_statement` or `upsert_statements`. Statements require a `kind`, `text`,
and outgoing `links`; entity mentions are derived from the text.

Use `search_statements` for semantic retrieval and `get_statements` to hydrate
known IDs. Use `list_link_types` and `list_statement_kinds` to inspect the
active vocabularies before authoring unfamiliar edges or kinds.

## 6. Change the browser UI

The browser app at `/ui/` is built from `frontend/ui/` with Vite, React and
TypeScript; [docs/WEB_APP.md](docs/WEB_APP.md) describes its screens. The build output in `src/mycelium/webui/` is
committed, so running the server needs no Node; changing the UI needs Node 24.

```sh
cd frontend
npm ci
npm run dev
```

`npm run dev` serves the app with hot reload at <http://localhost:5173/ui/> and
proxies every other path (API, auth, MCP) to `mycelium-http` on
`127.0.0.1:8765`. Start the server first; if it runs
on another port, start the dev server with the same `MYCELIUM_HTTP_PORT`.

Before committing a UI change, run the checks CI runs and commit the rebuilt
output with the source change:

```sh
npm run typecheck   # tsc, plus the strict-mode ratchet in strict-ratchet.ts
npm run lint        # ESLint; eslint-suppressions.json lists tolerated old findings
npm run build       # writes src/mycelium/webui/
```

CI rebuilds and fails if `src/mycelium/webui/` differs from what you committed.

## Troubleshooting

- If the MCP tools do not appear, run the configured command in a terminal and
  fix any path or dependency error it prints.
- If embeddings fail, confirm
  `curl "${OLLAMA_URL:-http://localhost:11434}/api/tags"` succeeds and that the
  configured model is present.
- If the UI reports a data-load failure, confirm `mycelium-http` is running and
  open <http://127.0.0.1:8765/api/data> directly.
- If a write is rejected, inspect its phrasing violations or submit prose
  through `ingest` for a reviewable draft.
