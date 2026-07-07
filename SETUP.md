# Mycelium setup guide

A hand-holding walkthrough from zero to a working Mycelium substrate, with
both transports (MCP for Claude Desktop, HTTP for the browser UI) live and
connected. Targeted at macOS; notes on Linux/Windows where relevant.

If you just want a reference of what's available, see `README.md`. Use this
guide if you're setting it up for the first time.

---

## What you'll have at the end

- A local SQLite substrate with vector search over Ollama embeddings
- An MCP server connected to Claude Desktop (you can ask Claude to query or
  write data through five tools)
- A FastAPI server on `http://127.0.0.1:8765/` exposing the same tools as
  REST endpoints, plus a read-only browser UI at `/ui/`

Estimated time: **15 minutes** if Python and Ollama are new, **5 minutes**
if they're already on your machine.

---

## 1 · Prerequisites

You need four pieces of software before touching the project.

### 1.1 Python 3.11 or later

Check what you have:

```sh
python3 --version
```

If it says `3.11.x` or higher, skip ahead. Otherwise, install via Homebrew:

```sh
brew install python@3.13
```

(Linux/Windows: use your package manager or https://www.python.org/downloads/.)

### 1.2 uv (the Python package manager we use)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```sh
uv --version
# uv 0.x.y (...)
```

`uv` handles virtual envs and the lockfile in one tool — there's no
`pip install`, `python -m venv`, or `requirements.txt` step in this project.

### 1.3 Ollama

Ollama runs the embedding model locally. Download from
<https://ollama.com/download> (drop the .app into `/Applications` on macOS),
or install via Homebrew:

```sh
brew install ollama
```

Start it (it runs as a background HTTP server on port 11434):

```sh
ollama serve &
```

Verify it's listening:

```sh
curl -sS http://localhost:11434/api/tags
# {"models":[...]}
```

If you installed the .app, launching it once from Finder also starts the
service automatically; you don't need `ollama serve` on subsequent boots.

### 1.4 The embedding model

Mycelium uses `nomic-embed-text`, a 768-dim local embedding model. Pull it:

```sh
ollama pull nomic-embed-text
```

The first download is ~270 MB and takes a minute or two. Verify:

```sh
ollama list | grep nomic-embed-text
# nomic-embed-text:latest    ...    274 MB
```

---

## 2 · Getting the project

```sh
git clone <wherever-this-lives> mycelium
cd mycelium
```

Or skip the clone if you already have the directory.

---

## 3 · Installing dependencies

From inside the project directory:

```sh
uv sync
uv run python -m spacy download en_core_web_sm
```

`uv` reads `pyproject.toml` + `uv.lock`, creates `.venv/`, and installs
everything pinned. This takes about 10 seconds the first time and is a
no-op on subsequent runs unless deps change. The second command installs
the spaCy model that phrasing validation loads at runtime (the Docker
image bakes it in the same way).

---

## 4 · Verifying the install

Run the unit tests — these don't touch Ollama or the network:

```sh
uv run pytest -q
# ...............                                                          [100%]
# 15 passed in 0.5s
```

Then run the in-process smoke test, which exercises the substrate end-to-end
against a temporary data directory and a fake embedding (still no Ollama):

```sh
uv run python scripts/smoke.py
# ... lots of output, ending with:
# SMOKE TEST PASSED
```

If both pass, the substrate code is healthy. If either fails, stop and
re-check `python3 --version` and `uv sync` output.

---

## 5 · Running the server

There are two transports. They share the same data directory (single-writer
rule — don't run both at once writing to the same `MYCELIUM_DATA_DIR`).

### 5.1 The data directory

Mycelium stores its SQLite database and vector index under whatever
`MYCELIUM_DATA_DIR` points at; the default is `./.mycelium/` next to wherever
you launched the process. For your first run, let it use the default.

### 5.2 MCP transport (for Claude Desktop)

```sh
uv run python -m mycelium
```

This starts the MCP server speaking JSON-RPC over stdio. It looks like it
hangs because stdio is occupied — that's expected. The server is now waiting
for a client. **Don't keep it running by hand**; Claude Desktop will spawn
its own copy. Press `Ctrl+C`.

### 5.3 HTTP transport (for the browser UI)

```sh
uv run mycelium-http
# INFO:     Uvicorn running on http://127.0.0.1:8765
```

Leave this one running in a terminal. In another terminal, verify:

```sh
curl -sS http://127.0.0.1:8765/list-link-types
# []   ← empty array because no data yet
```

You can stop the server with `Ctrl+C` whenever.

---

## 6 · Connecting Claude Desktop

Quit Claude Desktop completely (⌘Q — closing the window doesn't count; the
config is only re-read on full launch).

Open the config file:

```sh
open -t "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

If there's no `mcpServers` block, add one. If there is, add `mycelium` next
to the existing entries. Use **absolute paths** — Claude Desktop's spawn
environment doesn't include your shell's PATH:

```json
{
  "mcpServers": {
    "mycelium": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": [
        "--directory",
        "/absolute/path/to/mycelium",
        "run",
        "python",
        "-m",
        "mycelium"
      ],
      "env": {
        "MYCELIUM_DATA_DIR": "/absolute/path/where/data/lives",
        "OLLAMA_URL": "http://localhost:11434",
        "EMBED_MODEL": "nomic-embed-text",
        "PATH": "/Users/YOU/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"
      }
    }
  }
}
```

Find your `uv` path with `which uv`. Replace `/Users/YOU/...` with your
actual home directory.

Save the file. Launch Claude Desktop. In a new chat, click the tools icon
(usually a wrench or a hammer) — you should see seven Mycelium tools:

- `search_behaviors`
- `upsert_entity`
- `upsert_behavior`
- `upsert_name`
- `merge_entities`
- `move_name`
- `list_link_types`

If they don't appear, see the troubleshooting section below.

---

## 7 · Opening the browser UI

With `mycelium-http` running (section 5.3), open
<http://127.0.0.1:8765/> in any browser. The root path 307-redirects to
`/ui/`.

You should see a dark-themed page titled "Mycelium — read-only" with stats,
a search field, and a list of behaviors. If the substrate is empty, you'll
see zeros and a brief empty-state. The page uses React-via-CDN — no build
step needed; it loads in-browser.

---

## 7.5 · Standing up a separate knowledge base

The browser UI you just opened is using `./.mycelium/` inside this
project as its substrate. That works for trying things out, but for a
*real* corpus — internal docs, a product manual, anything you don't
want commingled with the substrate code — you'll want a separate
workspace dir with its own data and its own MCP wiring.

The scaffolder does this in one command:

```sh
uv run mycelium-init ~/work/my-new-kb
```

Creates `~/work/my-new-kb/` with:
- `.mcp.json` — wired to this Mycelium installation; spawns the
  substrate with `MYCELIUM_DATA_DIR` pointing at `data/` inside the
  new dir, so all writes land there
- `.gitignore` — excludes `data/` (binary substrate state) and
  `.mcp.json` (machine-specific paths)
- `data/` — empty; substrate writes here on first use
- `ingest/` — drop your JSON payloads here when bulk-importing
- `README.md` — short orientation

Open Claude Code in `~/work/my-new-kb`, approve the MCP via `/mcp`,
and you have a separate substrate whose database file lives entirely
outside this repo. The Mycelium tools (`mcp__mycelium__*`) work the
same way — they just hit a different data directory.

## 8 · Adding data to the substrate

Two paths depending on what you want.

### 8.1 Empty substrate, populate via Claude Desktop

In a Claude Desktop chat, ask:

> "Use the mycelium tools to record that 'A user logs in with email and
> password' is a behavior, and link it to the entity 'Login'."

Claude will figure out the right tool calls. After a few turns of writing,
hit `search_behaviors` to query what's there. Refresh the browser UI to
see the new records.

### 8.2 Bulk ingest from JSON payloads

If you've got a corpus of source documents you want to load programmatically,
the pattern is:

1. **Extract**: have an LLM (or a script) read each document and produce a
   JSON payload with the schema:

   ```json
   {
     "entities": [{"name": "...", "description": "..."}],
     "behaviors": [
       {
         "key": "<local-id>",
         "text": "...",
         "mentions": ["entity-name", ...],
         "links": [{"to": "<other-local-id>", "type": "contains"}]
       }
     ]
   }
   ```

2. **Ingest**: run a script that loads each JSON, calls `upsert_entity` /
   `upsert_behavior` for every record, and records the local-key →
   `behavior_id` mapping so cross-references in `links` resolve.

3. **Run**:

   ```sh
   MYCELIUM_DATA_DIR=/path/to/your/kb/data \
     uv run python /path/to/your/kb/scripts/ingest.py
   ```

Ingestion is roughly **one Ollama embed per behavior + one per link
update** — about 30 seconds for ~1,000 behaviors on a recent Mac.

---

## 9 · Troubleshooting

### "Connection refused" on port 11434

Ollama isn't running. Start it:

```sh
ollama serve &
```

Or open the .app from Finder. Verify with `curl http://localhost:11434/api/tags`.

### "model not found" or dimension mismatch errors

Either you didn't pull `nomic-embed-text`, or you've changed `EMBED_MODEL`
to something with a different output dimension. Mycelium hard-codes
`DIM = 768` in `src/mycelium/vector.py`. If you want to swap embed models,
both the env var **and** that constant need to match the new model's dim.

```sh
ollama pull nomic-embed-text
```

### "Address already in use" on port 8765

Either an old `mycelium-http` is still running, or something else grabbed
the port. Find it:

```sh
lsof -iTCP:8765 -sTCP:LISTEN
```

Kill the offender, or override the port:

```sh
MYCELIUM_HTTP_PORT=8766 uv run mycelium-http
```

### Tools don't appear in Claude Desktop after restart

1. **Did you actually quit and relaunch?** Closing the window doesn't
   reload the config — it must be ⌘Q + relaunch.
2. **Are paths absolute?** `command: "uv"` won't work; use the full path
   from `which uv`.
3. **Check the MCP server log**:

   ```sh
   ls -lt ~/Library/Logs/Claude/mcp-server-mycelium*.log | head -1
   tail -30 ~/Library/Logs/Claude/mcp-server-mycelium*.log
   ```

   The log will show the spawn command and any error from the substrate
   (e.g., "ModuleNotFoundError: mycelium" → wrong `--directory`, or
   "Connection refused" → Ollama down).

### "Failed to load /api/data" on the browser UI

The HTTP server isn't running, or your browser is hitting a different
host. Confirm `mycelium-http` is up and visit
<http://127.0.0.1:8765/api/data> directly — you should see a JSON dump.

### Behavior text re-embeds on every link update

That's expected and naive. The ingest script's pass-2 (linking) calls
`upsert_behavior` again with the same text, which forces an Ollama
embedding re-fetch. For small corpora it's fine; for large ones it's
~30% of total ingest time. The fix (a `set_links` primitive that doesn't
re-embed) is on the deferred list.

### A wipe-and-reingest produces different `behavior_id`s

`behavior_id`s are random UUIDs generated at create time. Two ingests
of the same JSON payload will produce two different sets of ids. The
*content* is deterministic; the surrogate ids aren't. If you need stable
ids, persist the local key → `behavior_id` mapping after ingest.

---

## 10 · Where things live

| path | what |
|---|---|
| `src/mycelium/server.py` | The five (well, seven) MCP tools and the substrate state |
| `src/mycelium/store.py` | SQLite schema + CRUD |
| `src/mycelium/embed.py` | Ollama client wrapper |
| `src/mycelium/vector.py` | hnswlib cosine vector index |
| `src/mycelium/http.py` | FastAPI app — auto-generates endpoints from the tool registry, plus HTTP-only routes for the UI |
| `src/mycelium/ui/` | The bundled read-only browser UI |
| `scripts/smoke.py` | Generic substrate smoke test (no Ollama required) |
| `tests/` | pytest unit tests for store, vector, and HTTP layers |
| `MYCELIUM_DATA_DIR/mycelium.db` | SQLite (entities, names, behaviors, mentions, links) |
| `MYCELIUM_DATA_DIR/mycelium.vec` | hnswlib index file (768-dim cosine) |

---

## What's next

Once everything is running, the most useful next steps:

- Read `project_vision.md` for the design philosophy (why naive, why
  AI-first, why a separate browser UI)
- Open `src/mycelium/server.py` and look at how the `@tool` decorator
  registers a function with both transports — adding a new tool is a
  single decorator and a function body
- Try editing `src/mycelium/ui/screens.jsx` and reloading the browser
  UI — Babel-Standalone transpiles JSX in the browser, no build step
