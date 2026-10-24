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

#: The set-wide audience slot: its text is the id of the documentation
#: audience the set writes for (see `mycelium.audiences`). A set without one
#: writes for the default internal audience.
AUDIENCE_SLOT = "audience"

#: The set-wide maintenance slot: its text is the policy for documents that
#: went out of date (see `mycelium.document_maintenance`). A set without one
#: is maintained by hand.
MAINTENANCE_SLOT = "maintenance"

#: The set-wide planning slot: its text is the policy for statements its
#: audience may see that no document of the set cites (see
#: `mycelium.document_maintenance`). A set without one is planned by hand.
PLANNING_SLOT = "planning"

#: The set-wide plan review slot: who decides the set's proposed plan items,
#: a person or an AI reviewer (see `mycelium.documentation_plan_review`). A
#: set without one leaves them to a person.
PLAN_REVIEW_SLOT = "plan_review"

#: The set-wide delivery slot: whether agents may deliver the set's
#: documents over MCP (`deliver_document`). A set without one is delivered
#: by people only.
DELIVERY_SLOT = "delivery"

#: The set-wide destinations slot: the names of the documentation
#: destinations the set's documents may be published to, one per line. A set
#: without one may publish to any configured destination.
DESTINATIONS_SLOT = "destinations"

#: Slots that steer every document in a set rather than naming something the
#: set can write. Keeping the subtraction here makes another set-wide slot a
#: one-line addition rather than another catalogue special case.
NON_TYPE_SLOTS = frozenset(
    {
        GUIDANCE_SLOT,
        EXPOSURE_SLOT,
        AUDIENCE_SLOT,
        MAINTENANCE_SLOT,
        PLANNING_SLOT,
        PLAN_REVIEW_SLOT,
        DELIVERY_SLOT,
        DESTINATIONS_SLOT,
    }
)

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
