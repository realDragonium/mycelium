"""What an admin still has to set up, and which background AI work is blocked.

Every status is read from saved settings and a few counts, so the checklist
costs no model call and no request to a provider: credentials are checked
for presence only (see `model_settings.provider_availability`).
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel

from . import (
    audiences,
    auth,
    documentation_profiles,
    draft_review_settings,
    model_settings,
    product_settings,
    prompt_store,
    quarantine,
)
from .ai import Provider
from .product_settings import SetupStep

Status = Literal["done", "todo", "dismissed"]
#: The settings screen each step is completed on.
Section = Literal["models", "audiences", "documentation", "review"]

ACTION_NAMES = model_settings.ACTION_NAMES
PROVIDER_NAMES: dict[Provider, str] = {"claude": "Claude", "openai": "OpenAI"}
MODES: dict[str, str] = {
    "off": "Off",
    "review-only": "Review only",
    "review-and-apply": "Review and apply",
}


class Step(BaseModel):
    id: SetupStep
    title: str
    status: Status
    detail: str
    section: Section
    optional: bool = False


class Blocked(BaseModel):
    """Background AI work that is switched on but cannot reach its provider."""

    worker: str
    reason: str


class SetupView(BaseModel):
    steps: list[Step]
    #: Every step is done or dismissed.
    complete: bool
    blocked: list[Blocked]
    quarantine: bool


def _actions_in_use(review_mode: str) -> list[model_settings.Action]:
    return [
        action
        for action in model_settings.ACTIONS
        if action != "draft_review" or review_mode != "off"
    ]


def _credentials(
    actions: list[model_settings.Action],
) -> tuple[Status, str]:
    users: dict[Provider, list[str]] = {}
    for action in actions:
        try:
            users.setdefault(model_settings.get(action).provider, []).append(
                ACTION_NAMES[action]
            )
        except model_settings.Unavailable:
            continue
    missing = [
        f"{PROVIDER_NAMES[provider]}, used by {', '.join(names)}: {reason}"
        for provider, names in users.items()
        if (reason := model_settings.provider_availability(provider).reason)
    ]
    if missing:
        return "todo", " ".join(missing)
    used = " and ".join(PROVIDER_NAMES[provider] for provider in users)
    return "done", f"{used} credentials are configured on the server."


def _models(actions: list[model_settings.Action]) -> tuple[Status, str]:
    unset = []
    for action in actions:
        try:
            if not model_settings.get(action).model:
                unset.append(ACTION_NAMES[action])
        except model_settings.Unavailable:
            unset.append(ACTION_NAMES[action])
    if unset:
        return "todo", f"Choose a model for {', '.join(unset)}."
    return "done", "Every AI action has a model."


def _audiences(
    prompts: sqlite3.Connection, substrate: sqlite3.Connection
) -> tuple[Status, str]:
    reviewed = (
        prompts.execute(
            "SELECT 1 FROM prompt_texts WHERE type = ? "
            "AND COALESCE(created_by, '') != 'seed' LIMIT 1",
            (audiences.TYPE,),
        ).fetchone()
        is not None
    )
    counts = substrate.execute(
        "SELECT (SELECT COUNT(*) FROM statements) AS total, "
        "(SELECT COUNT(*) FROM statement_audience_labels) AS labelled"
    ).fetchone()
    total, labelled = int(counts["total"]), int(counts["labelled"])
    parts = [
        "The starter audiences have not been edited yet."
        if not reviewed
        else f"{len(audiences.live(prompts))} audiences.",
        f"{labelled} of {total} statements labelled.",
    ]
    return ("done" if reviewed and labelled >= total else "todo"), " ".join(parts)


def _profile(prompts: sqlite3.Connection) -> tuple[Status, str]:
    snapshot = documentation_profiles.capture(prompts)
    chosen = [
        profile.name
        for profile in snapshot.profiles
        if profile.audience is not None and snapshot.audience(profile.name) is not None
    ]
    if chosen:
        return "done", f"Writing for a chosen audience: {', '.join(chosen)}."
    return "todo", "Choose an audience for a writing profile."


def _github(prompts: sqlite3.Connection) -> tuple[Status, str]:
    destinations = product_settings.get(
        product_settings.DocumentationSettings, conn=prompts
    ).destinations
    names = ", ".join(d.name for d in destinations)
    if destinations and quarantine.active():
        return "todo", f"Quarantine refuses GitHub delivery, so {names} gets nothing."
    if destinations:
        return "done", f"Publishing to {names}."
    return (
        "todo",
        "Connect a GitHub repository and add a destination to publish documents "
        "as pull requests.",
    )


def _review(controls: draft_review_settings.ControlSnapshot) -> tuple[Status, str]:
    # Startup saves the defaults as revision 1, so only a later save, or a mode
    # carried over from the environment, shows that someone chose.
    if controls.revision > 1 or controls.mode != "off":
        return "done", f"Draft review: {MODES[controls.mode]}."
    return "todo", "Choose whether submitted drafts get an automatic AI review."


def blocked(review_mode: str, prompts: sqlite3.Connection) -> list[Blocked]:
    """Background workers that are on but lack provider credentials. In
    quarantine none of them runs, so none is blocked."""
    if quarantine.active():
        return []
    found = []
    if review_mode != "off" and (
        reason := model_settings.credentials_error("draft_review")
    ):
        found.append(
            Blocked(
                worker="Draft review",
                reason=f"{reason} Submitted drafts wait unreviewed.",
            )
        )
    labelling = product_settings.get(
        product_settings.AudienceLabellingSettings, conn=prompts
    )
    if labelling.automatic and (
        reason := model_settings.credentials_error("audience_labelling")
    ):
        found.append(
            Blocked(
                worker="Audience labelling",
                reason=f"{reason} New statements stay unlabelled.",
            )
        )
    revising = any(
        profile.maintenance == "auto-revise"
        for profile in documentation_profiles.capture(prompts).profiles
    )
    if revising and (reason := model_settings.credentials_error("docgen")):
        found.append(
            Blocked(
                worker="Document maintenance",
                reason=f"{reason} Out-of-date documents are not revised.",
            )
        )
    return found


def view(substrate: sqlite3.Connection) -> SetupView:
    prompts = prompt_store.connection()
    controls, _ = draft_review_settings.editable_controls(prompts)
    actions = _actions_in_use(controls.mode)
    dismissed = set(
        product_settings.get(product_settings.SetupSettings, conn=prompts).dismissed
    )
    rows: list[tuple[SetupStep, str, tuple[Status, str], Section, bool]] = [
        (
            "credentials",
            "AI provider credentials",
            _credentials(actions),
            "models",
            False,
        ),
        ("models", "Models for each AI action", _models(actions), "models", False),
        (
            "audiences",
            "Audiences reviewed and statements labelled",
            _audiences(prompts, substrate),
            "audiences",
            False,
        ),
        (
            "profile",
            "A writing profile with an audience",
            _profile(prompts),
            "documentation",
            False,
        ),
        (
            "github",
            "GitHub connection and destination",
            _github(prompts),
            "documentation",
            True,
        ),
        ("review", "Draft review mode", _review(controls), "review", False),
    ]
    steps = [
        Step(
            id=step,
            title=title,
            status="dismissed" if status == "todo" and step in dismissed else status,
            detail=detail,
            section=section,
            optional=optional,
        )
        for step, title, (status, detail), section, optional in rows
    ]
    return SetupView(
        steps=steps,
        complete=all(step.status != "todo" for step in steps),
        blocked=blocked(controls.mode, prompts),
        quarantine=quarantine.active(),
    )


def dismiss(step: SetupStep, dismissed: bool, principal: auth.Principal) -> None:
    prompts = prompt_store.connection()
    revision = product_settings.editable(
        product_settings.SetupSettings(), prompts
    ).revision
    steps = set(
        product_settings.get(product_settings.SetupSettings, conn=prompts).dismissed
    )
    steps = steps | {step} if dismissed else steps - {step}
    product_settings.save(
        product_settings.SaveSettings(
            revision=revision,
            settings=product_settings.SetupSettings(dismissed=tuple(sorted(steps))),
        ),
        principal,
    )
