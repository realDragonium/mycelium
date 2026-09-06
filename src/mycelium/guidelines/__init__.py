"""Documentation profiles use the existing guideline-set/profile-slot convention.

Packaged files supply the initial examples. Once any guideline history exists,
startup leaves it alone, including retired rows. Readers share the immutable
profile snapshot adapter used by generation runs.
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

#: The set-wide disclosure-boundary slot. It is not a document type — no run
#: can be asked to produce an `exposure`, so every listing of what a set can
#: write subtracts it.
EXPOSURE_SLOT = "exposure"

#: Slots that steer every document in a set rather than naming something the
#: set can write. Keeping the subtraction here makes another set-wide slot a
#: one-line addition rather than another catalogue special case.
NON_TYPE_SLOTS = frozenset({GUIDANCE_SLOT, EXPOSURE_SLOT})

#: The one set that ships. A second set is data — added through the tools,
#: with no source files and no entry here (see `internal-doc` in the doc).
SET_NAME = "kb-authoring"

_SET_DIR = Path(__file__).resolve().parent / SET_NAME

#: Row slot -> the file whose contents that row holds verbatim. `guidance` and
#: `exposure` steer the whole set; the rest are named for the document type
#: they produce, so a run fetches exactly the template it is writing.
#:
#: Explicit starter contents; subsequent deployments do not add or restore slots.
SOURCES: dict[str, Path] = {
    "guidance": _SET_DIR / "guidance.md",
    "exposure": _SET_DIR / "exposure.md",
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
    """Live, well-formed profiles mapped to their available document types."""
    from ..documentation_profiles import capture

    return capture(conn).catalogue()


def texts(
    conn: sqlite3.Connection, set_name: str, document_type: str
) -> tuple[str | None, str | None, str | None]:
    """Read guidance, exposure and template from one consistent snapshot."""
    from ..documentation_profiles import capture

    return capture(conn).texts(set_name, document_type)


def read_rows() -> dict[str, str]:
    """Every shipped row as {name: text}, each its source file verbatim.

    All seven or an exception — the caller that wants a per-row failure to cost
    only that row (startup) reads `SOURCES` itself and guards each read."""
    return {
        row_name(slot): path.read_text(encoding="utf-8")
        for slot, path in SOURCES.items()
    }
