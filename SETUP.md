# Mycelium setup guide

This guide starts a local Mycelium substrate over MCP and HTTP.

## 1. Install requirements

Install Python 3.11 or later, [`uv`](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/download). Then start Ollama and pull the default
embedding model:

```sh
ollama serve
ollama pull nomic-embed-text
```

In another terminal, clone the repository and install its dependencies:

```sh
git clone https://github.com/dragonium/mycelium.git
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

Open <http://127.0.0.1:8765/ui/> for the UI or
<http://127.0.0.1:8765/docs> for the generated HTTP API reference.

Both transports use `./.mycelium` unless `MYCELIUM_DATA_DIR` points elsewhere.
They may share the directory, but Mycelium supports one writer at a time.

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
from `src/mycelium/server.py`; `README.md` describes the main read and authoring
paths.

## 4. Use a separate knowledge base

Keep a real corpus and its runtime state outside the source checkout:

```sh
uv run mycelium-init ~/work/my-new-kb
```

This creates a workspace with its own `.mcp.json`, ignored `data/` directory,
and `ingest/` directory. Open the workspace in your MCP client and approve its
server configuration.

## 5. Add data

For prose, call `ingest_text`. It segments the input into typed statements,
proposes links, and returns a draft. Inspect the draft with `get_draft`, remove
unwanted operations with `discard_draft_op`, then submit it with `submit_draft`.

For direct writes, create named entities with `upsert_entity`, then use
`upsert_statement` or `upsert_statements`. Statements require a `kind`, `text`,
and outgoing `links`; entity mentions are derived from the text.

Use `search_statements` for semantic retrieval and `get_statements` to hydrate
known IDs. Use `list_link_types` and `list_statement_kinds` to inspect the
active vocabularies before authoring unfamiliar edges or kinds.

## Troubleshooting

- If the MCP tools do not appear, run the configured command in a terminal and
  fix any path or dependency error it prints.
- If embeddings fail, confirm `curl http://localhost:11434/api/tags` succeeds
  and that the configured model is present.
- If the UI reports a data-load failure, confirm `mycelium-http` is running and
  open <http://127.0.0.1:8765/api/data> directly.
- If a write is rejected, inspect its phrasing violations or submit prose
  through `ingest_text` for a reviewable draft.
