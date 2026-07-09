"""Glossary seed data and CRUD for statement kinds and link types."""

from __future__ import annotations

import sqlite3

from . import kernel
from .kernel import _now

# --- glossary seed data ----------------------------------------------------
# Source-of-truth dicts used to populate the glossary tables on first
# run. After seeding, the DB is authoritative — UI edits write back to
# the tables, not to these dicts. `INSERT OR IGNORE` makes re-seeding a
# no-op for any row that already exists; deleted entries do not get
# resurrected.

_STATEMENT_KIND_SEED: dict[str, tuple[str, str]] = {
    "event": (
        "Something happening — an atomic occurrence in the product "
        "(creation, submission, rejection, dispatch).",
        "Discrete things that fire, succeed, or are rejected. Use "
        "action-as-subject phrasing ('an invite is submitted'), with "
        "the actor in `mentions` unless the actor's identity is itself "
        "the claim (in which case use `capability`).",
    ),
    "state": (
        "A genuinely persisting, observable condition of a named "
        "entity — enum values, configuration flags, or conditions at a "
        "decision point.",
        "Enum/status values ('Sent' on Participant Status), config "
        "flags ('Auto result sharing enabled' on Company), or "
        "observable missing-input conditions ('No name on the invite' "
        "on Invite). Often referenced as `when` leaves on conditional "
        "edges. Do NOT use for derived/computed conditions or "
        "internal-mechanism steps.",
    ),
    "capability": (
        "A modal claim about what is possible — 'X can do Y'. Warranted "
        "only when the actor's identity or permission boundary is itself "
        "the claim, or when it anchors a `governed-by` rule tree.",
        "Authoring an event already implies the action is possible. "
        "Reach for `capability` when the point of the statement is who "
        "is allowed, what is gated, or which rule decomposition this "
        "modal anchors. Otherwise prefer `event`.",
    ),
    "rule": (
        "A deterministic, non-contingent claim — formula, default, "
        "enumeration, or bound that holds the same way across all "
        "instances and moments.",
        "Definitional or computational claims ('match level is one "
        "of: Low, Medium, High, Extra High'; 'match score equals "
        "construct points plus intelligence contribution minus red "
        "flag penalties'). Apply the contingency test: if the same "
        "claim could be otherwise for a specific entity or at a "
        "specific time, it is a `state`, not a `rule`.",
    ),
    "property": (
        "A slot on an entity that holds a value — short noun-phrase "
        "label, not a sentence. 'Email', 'Vacancy ID', 'Match score'.",
        "When the meaningful question is *what value* rather than "
        "*does this hold*. User-supplied configuration values, "
        "user-supplied event inputs, or derived/computed values. "
        "Anchored to its entity via `mentions`. Reach for this "
        "instead of packing inputs into event text.",
    ),
    "procedure": (
        "The named root of a how-to guide. 'How to configure Recruitee "
        "automation for a vacancy.' Composes `action`s, `property` "
        "inputs, and optional `check`s into a runnable script.",
        "Authoring prescriptive content: a guide the user (or an "
        "agent) executes to accomplish something. Anchors to a "
        "`capability` via `teaches`. The body is composed via "
        "`contains` / `next` to actions, and `requires` / `accepts` "
        "to property inputs.",
    ),
    "action": (
        "A step the user performs that modifies the system. 'Click "
        "the Save button.' Anchors to a descriptive `event` via "
        "`performs`.",
        "Single UI interactions inside a procedure or diagnostic "
        "flow: clicks, navigations, entries, sends. Each action is "
        "its own statement; the procedure `contains` them or chains "
        "them via `next`.",
    ),
    "check": (
        "A verification step for a diagnostic agent — observing the "
        "system without changing it. 'Verify the user's authentication "
        "provider matches the login method.'",
        "Diagnostic flows where a step inspects rather than mutates. "
        "Anchors to a `state` via `verifies`. Branches with "
        "`on-success` / `on-failure` or links to a `cause` via "
        "`confirms` / `refutes`.",
    ),
    "cause": (
        "A named failure mode worth investigating. 'User is attempting "
        "password login on a social-only account.'",
        "Roots of a diagnostic tree. Optionally anchors to a `state` "
        "via `violates` when the failure mode is 'a required state "
        "isn't met'. Free-standing when the failure is environmental, "
        "historical, referential, or compound.",
    ),
}

_STATEMENT_LINK_TYPE_SEED: dict[str, str] = {
    "contains": (
        "Sub-step inside the same process. Target only makes sense as "
        "part of the parent (e.g. 'The write pipeline executes' contains "
        "'The extraction agent runs')."
    ),
    "triggers": (
        "A *separate* downstream process fires as a consequence. Target "
        "stands on its own clock (e.g. 'An invite is created' triggers "
        "'A notification email is sent')."
    ),
    "establishes": (
        "Source produces a resulting state. Multiple statements can each "
        "`establishes` the same state — the state becomes the convergence "
        "point. No intermediate events: if event A causes state S, link "
        "A → establishes → S directly; do not create an intermediate "
        "event whose only purpose is to establish S."
    ),
    "enables": (
        "Source unlocks target's capability without directly invoking it "
        "(e.g. 'Embeddings are generated' enables 'Vector search returns "
        "ranked results'). Do NOT use for condition states — a state "
        "referenced in a `when` expression on an edge must not also have "
        "an `enables` link to the same target."
    ),
    "requires": (
        "Two uses: (1) target must hold for source to fire, usually "
        "paired with a `when` clause when the prerequisite is itself a "
        "statement; (2) source consumes the target `property` as a "
        "mandatory input in this context."
    ),
    "accepts": (
        "Source consumes the target `property` as an *optional* input "
        "in this context. The same property record is referenced from a "
        "`requires` edge elsewhere — optionality is per-edge, not "
        "per-property."
    ),
    "varies-by": (
        "Source's behavior depends on target as a parameter — shapes "
        "*how* source plays out, not *whether* it fires."
    ),
    "configures": (
        "Source parameterises target before target fires. Use sparingly; "
        "`contains` is often cleaner."
    ),
    "replaces": (
        "Source supersedes target. Almost always with a `when` clause — "
        "'replaces under condition C'."
    ),
    "restricts": (
        "Source limits target's operation. Use when the limit is itself "
        "a *statement* (a kill-switch, a feature flag)."
    ),
    "proceeds": (
        "Sequential hand-off in the same flow. A proceeds to B means B "
        "is the immediate next step after A in a continuous sequence — "
        "neither a contained sub-step (`contains`) nor an independently-"
        "fired downstream process (`triggers`). Use when A's completion "
        "naturally flows into B without a causal gap."
    ),
    "fallback-to": (
        "Ordered priority chain. A fallback-to B means B applies only "
        "when A does not. Forms a linear chain; first applicable option "
        "wins. Distinct from `cases` (enumeration over a named value "
        "set) and `composes` (grouping without ordering)."
    ),
    "governed-by": (
        "The rule that determines how a capability works. Typically: "
        "capability → governed-by → top-level rule."
    ),
    "composes": (
        "Sub-formula or sub-rule; together the composed statements "
        "specify the parent. Carry `when`-conditions on these edges for "
        "conditional applicability. Not the same as `cases`."
    ),
    "cases": (
        "Enumerated branches over a named, finite value set only "
        "(match levels, construct types, etc.). Each edge points to one "
        "branch. Do NOT use for continuous predicates — use a "
        "`when`-condition on a `composes` edge instead."
    ),
    "valued-by": (
        "The source statement's value is derived by the target rule. "
        "Typically: state → valued-by → rule. Do NOT use when the value "
        "is configured or input directly."
    ),
    "supersedes": "Versioning: source replaces target.",
    "teaches": (
        "Procedure → capability. Anchors a how-to guide to the "
        "capability it teaches the user to exercise. Every `procedure` "
        "should `teaches` exactly one capability."
    ),
    "performs": (
        "Action → event. The user step models this product event — the "
        "descriptive thing that actually happens when the user "
        "performs the step. Anchors the prescriptive action to the "
        "descriptive layer."
    ),
    "verifies": (
        "Check → state. The diagnostic check inspects whether this "
        "state currently holds, without changing the system. Anchors "
        "the check to the descriptive condition being observed."
    ),
    "violates": (
        "Cause → state. The failure mode corresponds to a required "
        "state not holding. Optional anchor: a cause may also be "
        "free-standing (environmental, historical, referential, or "
        "compound) and need no `violates` link."
    ),
    "obtained-by": (
        "Property → action or procedure. How the user finds or "
        "produces this value. Empty for values the user types directly "
        "or for derived/computed values."
    ),
    "next": (
        "Linear sequence between prescriptive steps. A `next` B means "
        "B follows A. Use for action→action and check→check chains. "
        "Distinct from descriptive `proceeds` (which connects events)."
    ),
    "on-success": (
        "Branch after a check or action on its success path. Source's "
        "success outcome leads to target. Pair with `on-failure` for "
        "the complementary branch."
    ),
    "on-failure": (
        "Branch after a check or action on its failure path. Source's "
        "failure outcome leads to target. Pair with `on-success` for "
        "the complementary branch."
    ),
    "confirms": (
        "Check → cause. If this check passes, this cause is the issue. "
        "Used in diagnostic trees to link verification steps to the "
        "failure modes they identify."
    ),
    "refutes": (
        "Check → cause. If this check passes, this cause is *not* the "
        "issue. Used in diagnostic trees to rule causes out."
    ),
    "resolves": (
        "Action → cause. This action fixes the situation when the "
        "cause applies. Used to attach remediation steps to diagnosed "
        "failure modes."
    ),
}

_ENTITY_LINK_TYPE_SEED: dict[str, str] = {
    "contains": (
        "Parent → member. Structural composition between long-lived "
        "entities (e.g. parent corp → subsidiary, category → member). "
        "Same top-down direction as statement links: parent is the source."
    ),
    "replaces": (
        "Source entity supersedes target entity (e.g. one provider replacing another)."
    ),
    "sub-type": (
        "Source is a specialization of target. Reads 'source is a "
        "sub-type of target' (e.g. Ubeeo is a sub-type of ATS, "
        "hard_skill_german_language is a sub-type of Hard Skill). "
        "Parent / general category at the target end."
    ),
    "has": (
        "Source has the target as a component, attribute, or related "
        "object. Generic ownership/composition relation between long-"
        "lived entities when neither `contains` (strict structural "
        "membership) nor `sub-type` (specialization) fits."
    ),
    "uses": (
        "Source depends on or makes use of target. Behavioural "
        "dependency between long-lived entities — distinct from "
        "structural composition (`contains`) and specialization "
        "(`sub-type`)."
    ),
}


def seed_glossaries(conn: sqlite3.Connection) -> None:
    """Populate glossary tables from seed data. Idempotent — uses
    `INSERT OR IGNORE`, so existing rows are never overwritten and a
    re-seed cannot resurrect rows the user has deleted via the UI."""
    now = _now()
    for kind, (description, when_to_use) in _STATEMENT_KIND_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO statement_kind_glossary "
            "(kind, description, when_to_use, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, description, when_to_use, now, kernel.get_actor()),
        )
    for link_type, description in _STATEMENT_LINK_TYPE_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO statement_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, kernel.get_actor()),
        )
    for link_type, description in _ENTITY_LINK_TYPE_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO entity_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, kernel.get_actor()),
        )


# --- glossary CRUD ---------------------------------------------------------


def list_statement_kind_glossary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, description, when_to_use FROM statement_kind_glossary "
        "ORDER BY kind"
    ).fetchall()


def get_statement_kind_glossary(
    conn: sqlite3.Connection, kind: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT kind, description, when_to_use FROM statement_kind_glossary "
        "WHERE kind = ?",
        (kind,),
    ).fetchone()


def upsert_statement_kind_glossary(
    conn: sqlite3.Connection,
    kind: str,
    description: str,
    when_to_use: str | None,
) -> None:
    existing = get_statement_kind_glossary(conn, kind)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO statement_kind_glossary "
            "(kind, description, when_to_use, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, description, when_to_use, now, kernel.get_actor()),
        )
    else:
        conn.execute(
            "UPDATE statement_kind_glossary "
            "SET description = ?, when_to_use = ?, updated_at = ?, updated_by = ? "
            "WHERE kind = ?",
            (description, when_to_use, now, kernel.get_actor(), kind),
        )


def delete_statement_kind_glossary(conn: sqlite3.Connection, kind: str) -> None:
    conn.execute("DELETE FROM statement_kind_glossary WHERE kind = ?", (kind,))


def list_statement_link_type_glossary(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT link_type, description FROM statement_link_type_glossary "
        "ORDER BY link_type"
    ).fetchall()


def get_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT link_type, description FROM statement_link_type_glossary "
        "WHERE link_type = ?",
        (link_type,),
    ).fetchone()


def upsert_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str, description: str
) -> None:
    existing = get_statement_link_type_glossary(conn, link_type)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO statement_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, kernel.get_actor()),
        )
    else:
        conn.execute(
            "UPDATE statement_link_type_glossary "
            "SET description = ?, updated_at = ?, updated_by = ? "
            "WHERE link_type = ?",
            (description, now, kernel.get_actor(), link_type),
        )


def delete_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> None:
    conn.execute(
        "DELETE FROM statement_link_type_glossary WHERE link_type = ?",
        (link_type,),
    )


def list_entity_link_type_glossary(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT link_type, description FROM entity_link_type_glossary "
        "ORDER BY link_type"
    ).fetchall()


def get_entity_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT link_type, description FROM entity_link_type_glossary "
        "WHERE link_type = ?",
        (link_type,),
    ).fetchone()


def upsert_entity_link_type_glossary(
    conn: sqlite3.Connection, link_type: str, description: str
) -> None:
    existing = get_entity_link_type_glossary(conn, link_type)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO entity_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, kernel.get_actor()),
        )
    else:
        conn.execute(
            "UPDATE entity_link_type_glossary "
            "SET description = ?, updated_at = ?, updated_by = ? "
            "WHERE link_type = ?",
            (description, now, kernel.get_actor(), link_type),
        )


def delete_entity_link_type_glossary(conn: sqlite3.Connection, link_type: str) -> None:
    conn.execute(
        "DELETE FROM entity_link_type_glossary WHERE link_type = ?",
        (link_type,),
    )


def count_statements_by_kind(conn: sqlite3.Connection, kind: str) -> int:
    """Used by list_statement_kinds to compute `in_use`."""
    row = conn.execute(
        "SELECT COUNT(*) FROM statements WHERE kind = ?", (kind,)
    ).fetchone()
    return int(row[0]) if row else 0
