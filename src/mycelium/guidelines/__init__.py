"""The guideline sets that ship with the package — where their files are and
what their rows are called.

A guideline set is what a documentation-generation run writes against: one
set-wide `guidance` row plus one template row per document type. Sets live in
`prompt_store` so an operator can edit or add one with a tool call, but an
instance with an empty store has nothing to generate against — so one set
ships as files and reaches the store on its own.

The files sit under `src/mycelium/` for the same reason the loop doctrines do:
that is the tree the wheel carries and the image copies, so a deployment gets
them without a checkout and without an operator running anything. `.claude/`
is a local tool's configuration directory; nothing that has to reach a server
can live there.

Two callers read this module, and they want different writes:

- `server.init` seeds through `save_if_absent`, which never supersedes. An
  operator's edit outlives every restart, and a boot against a seeded store
  writes nothing.
- `scripts/seed_guideline_sets.py` writes through `save`, which appends a new
  version whenever the file has moved on. That is how an author pushes a
  reworked template into an instance they hold a checkout of.

Neither write belongs to the other, which is why this module stops at the
paths and the names: it is the shared half — where each row's text comes from
and what the row is called — and each caller keeps its own write.
"""

from __future__ import annotations

from pathlib import Path

#: The prompt-store `type` every row of every guideline set is stored under.
#: See `docs/GUIDELINE_SETS.md` for the naming convention this implements.
TYPE = "guideline-set"

#: The one set that ships. A second set is data — added through the tools,
#: with no source files and no entry here (see `internal-doc` in the doc).
SET_NAME = "kb-authoring"

_SET_DIR = Path(__file__).resolve().parent / SET_NAME

#: Row slot -> the file whose contents that row holds verbatim. `guidance` is
#: the set-wide instruction; the rest are named for the document type they
#: produce, so a run fetches exactly the template it is writing.
#:
#: Explicit rather than a directory scan: this list is also what startup
#: refuses to let an operator retire, and a name that becomes un-retirable
#: because a file appeared next to the templates would be a surprise.
SOURCES: dict[str, Path] = {
    "guidance": _SET_DIR / "guidance.md",
    "tutorial": _SET_DIR / "templates" / "tutorial.md",
    "how-to": _SET_DIR / "templates" / "how-to.md",
    "reference": _SET_DIR / "templates" / "reference.md",
    "explanation": _SET_DIR / "templates" / "explanation.md",
    "troubleshooting": _SET_DIR / "templates" / "troubleshooting.md",
}


def row_name(slot: str) -> str:
    """The prompt-store name a slot is stored under: `<set>/<slot>`."""
    return f"{SET_NAME}/{slot}"


def read_rows() -> dict[str, str]:
    """Every shipped row as {name: text}, each its source file verbatim.

    All six or an exception — the caller that wants a per-row failure to cost
    only that row (startup) reads `SOURCES` itself and guards each read."""
    return {
        row_name(slot): path.read_text(encoding="utf-8")
        for slot, path in SOURCES.items()
    }
