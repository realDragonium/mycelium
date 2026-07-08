"""Scaffold a new Mycelium knowledge-base directory.

Run via the `mycelium-init` console script:

    uv run mycelium-init /path/to/new-kb

Creates the directory if it doesn't exist (refuses to overwrite a
non-empty one), drops in a `.mcp.json` wired to *this* Mycelium
installation, a `.gitignore` that excludes the substrate binary state,
empty `data/` and `ingest/` subdirs, and a README template.

The `.mcp.json` uses absolute paths and is gitignored — that keeps
machine-specific paths out of any repo the user might initialise on
top of the new directory. If a team wants a shared, portable
`.mcp.json`, they can edit it (drop the absolute path, add a wrapper
script that resolves `MYCELIUM_DATA_DIR` from the spawn cwd, etc.)
after `mycelium-init` runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GITIGNORE = """\
# Mycelium substrate state — never commit. Regenerable from ingest/.
data/

# Project-local MCP config has user-specific absolute paths.
.mcp.json
"""

README_TEMPLATE = """\
# {name}

A Mycelium knowledge base.

## Usage

Open Claude Code in this directory. The Mycelium MCP is wired up via
`.mcp.json` and Claude Code will prompt to approve it on first launch.
Run `/mcp` if it doesn't appear automatically.

## Layout

- `.mcp.json` — project-scoped MCP config pointing at the Mycelium
  installation at `{mycelium_project}`. Contains absolute paths and is
  gitignored.
- `data/` — substrate state (SQLite + hnswlib binary). Gitignored.
  Regenerable from `ingest/` via the substrate's ingest workflow.
- `ingest/` — JSON payloads with extracted entities and statements.
  Commit these.

## Prerequisites

- Mycelium installed at `{mycelium_project}` with `uv sync`.
- Ollama running with `nomic-embed-text` pulled.

See `{mycelium_project}/SETUP.md` for the full setup walkthrough.

## Re-ingesting

If `ingest/` payloads change or you wipe `data/`, re-run an ingest
script.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mycelium-init",
        description="Scaffold a new Mycelium knowledge-base directory.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Path of the new knowledge-base directory.",
    )
    args = parser.parse_args()

    kb_dir = args.directory.expanduser().resolve()
    if kb_dir.exists() and any(kb_dir.iterdir()):
        sys.exit(f"refusing to overwrite non-empty directory: {kb_dir}")
    kb_dir.mkdir(parents=True, exist_ok=True)

    # The Mycelium installation is up two levels from this file:
    # src/mycelium/init_kb.py -> src/mycelium -> src -> <project>.
    mycelium_project = Path(__file__).resolve().parents[2]

    mcp_config = {
        "mcpServers": {
            "mycelium": {
                "command": "uv",
                "args": [
                    "--project",
                    str(mycelium_project),
                    "run",
                    "python",
                    "-m",
                    "mycelium",
                ],
                "env": {
                    "MYCELIUM_DATA_DIR": str(kb_dir / "data"),
                },
            }
        }
    }
    (kb_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n")
    (kb_dir / ".gitignore").write_text(GITIGNORE)
    (kb_dir / "README.md").write_text(
        README_TEMPLATE.format(
            name=kb_dir.name,
            mycelium_project=str(mycelium_project),
        )
    )
    (kb_dir / "data").mkdir()
    (kb_dir / "ingest").mkdir()

    print(f"Created {kb_dir}/")
    print(f"  .mcp.json   → wired to {mycelium_project}")
    print("  .gitignore  → excludes data/ and .mcp.json")
    print("  data/       → empty (substrate writes here)")
    print("  ingest/     → drop your JSON payloads here")
    print("  README.md   → template")
    print()
    print("Next: open Claude Code in this directory.")
    print("On first launch run /mcp and approve the mycelium server.")


if __name__ == "__main__":
    main()
