"""Guideline sets: what a set is called in the store, and which one ships.

Two halves, both about the same convention (`docs/GUIDELINE_SETS.md`).

The naming half — `TYPE`, `row_name`, and the two readers `catalogue` /
`texts` — is about every set, shipped or not. A set is not a registry: it is
whichever `<set>/<slot>` rows are live, so "which sets exist and what can each
write" is a listing, and "give me the two texts this run writes against" is
two lookups. Both live here so a caller never has to spell `<set>/<slot>`
itself; a set added purely as config is therefore selectable with no code
change anywhere.

The shipping half — `SET_NAME`, `SOURCES`, `read_rows` — is about the one set
that has source files, because an instance with an empty store has nothing to
generate against and a fresh deployment has to arrive with something.

A guideline set is what a documentation-generation run writes against: one
set-wide `guidance` row plus one template row per document type. Sets live in
`prompt_store` so an operator can edit or add one with a tool call.

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

import sqlite3
from pathlib import Path

#: The prompt-store `type` every row of every guideline set is stored under.
#: See `docs/GUIDELINE_SETS.md` for the naming convention this implements.
TYPE = "guideline-set"

#: The set-wide instruction slot. It is not a document type — no run can be
#: asked to produce a `guidance`, so every listing of what a set can write
#: subtracts it.
GUIDANCE_SLOT = "guidance"

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


def row_name(slot: str, set_name: str = SET_NAME) -> str:
    """The prompt-store name a slot is stored under: `<set>/<slot>`."""
    return f"{set_name}/{slot}"


def catalogue(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Every configured set mapped to the document types it can write.

    Derived from the live rows, never from a list in code: a set added with
    three `save_prompt_text` calls appears here, and one whose rows were
    retired disappears. `guidance` is excluded from every value — it is the
    set-wide instruction, not something a run can be asked to produce — so a
    set present with only a `guidance` row maps to an empty list, which reads
    as "configured but cannot write anything yet" rather than vanishing.
    """
    from .. import prompt_store

    sets: dict[str, set[str]] = {}
    for row in prompt_store.list_current(conn, TYPE):
        set_name, _, slot = row["name"].partition("/")
        sets.setdefault(set_name, set()).add(slot)
    return {
        name: sorted(slots - {GUIDANCE_SLOT}) for name, slots in sorted(sets.items())
    }


def texts(
    conn: sqlite3.Connection, set_name: str, document_type: str
) -> tuple[str | None, str | None]:
    """The two texts a run writes against: (`<set>/guidance`, `<set>/<type>`).

    Two lookups rather than one omnibus row, which is the whole reason a set
    is several rows (docs/GUIDELINE_SETS.md). Either may be None when the row
    is absent or retired; the caller decides whether it can proceed, because
    a missing template is fatal to a run while missing set-wide guidance only
    costs it context.
    """
    from .. import prompt_store

    return (
        prompt_store.latest_text(conn, TYPE, row_name(GUIDANCE_SLOT, set_name)),
        prompt_store.latest_text(conn, TYPE, row_name(document_type, set_name)),
    )


def read_rows() -> dict[str, str]:
    """Every shipped row as {name: text}, each its source file verbatim.

    All six or an exception — the caller that wants a per-row failure to cost
    only that row (startup) reads `SOURCES` itself and guards each read."""
    return {
        row_name(slot): path.read_text(encoding="utf-8")
        for slot, path in SOURCES.items()
    }
