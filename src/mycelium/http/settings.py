"""Admin settings: product settings, AI model choices, the draft-review setup,
AI usage and the setup checklist.

Anyone authenticated may read them; only an admin may save. A conflicting save
answers 409 through the shared conflict handler, and unavailable settings 503.
"""

from __future__ import annotations

from typing import Annotated

import anyio.from_thread
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .. import (
    ai_usage,
    drafts_store,
    model_settings,
    product_settings,
    server,
    setup_checklist,
)
from .. import draft_review_settings as review_settings
from ..request_timing import TimedRoute
from .access import _require_admin, _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/product-settings")
def read_product_settings(request: Request) -> product_settings.SettingsView:
    principal = _require_principal(request)
    try:
        return product_settings.view(principal)
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.patch("/api/product-settings")
def save_product_settings(
    body: product_settings.SaveSettings, request: Request
) -> product_settings.Snapshot:
    principal = _require_admin(request)
    try:
        saved = product_settings.save(body, principal)
        if isinstance(body.settings, product_settings.ConcurrencySettings):
            anyio.from_thread.run_sync(lambda: server.limiter_for("ask"))
        return saved
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/api/model-settings")
def ai_model_settings(request: Request) -> model_settings.SettingsView:
    principal = _require_principal(request)
    try:
        return model_settings.view(principal)
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.patch("/api/model-settings/{action}")
def save_ai_model_settings(
    action: model_settings.Action, body: model_settings.SaveSelection, request: Request
) -> model_settings.ActionView:
    principal = _require_admin(request)
    try:
        model_settings.save(action, body, principal)
        return model_settings.action_view(action)
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/api/draft-review/settings")
def draft_review_settings(request: Request) -> review_settings.SettingsView:
    principal = _require_principal(request)
    try:
        return review_settings.view(principal)
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.patch("/api/draft-review/settings")
def save_draft_review_settings(
    body: review_settings.SaveSettings, request: Request
) -> review_settings.SettingsView:
    principal = _require_admin(request)
    try:
        review_settings.save(body, principal)
        return review_settings.view(principal)
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/api/ai-usage")
def ai_usage_report(
    request: Request, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> ai_usage.UsageView:
    _require_admin(request)
    return ai_usage.view(drafts_store.connection(), days)


@router.get("/api/setup")
def setup_view(request: Request) -> setup_checklist.SetupView:
    _require_admin(request)
    try:
        return setup_checklist.view(server._db())
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


class DismissStep(BaseModel):
    dismissed: bool


@router.put("/api/setup/steps/{step}")
def dismiss_setup_step(
    step: product_settings.SetupStep, body: DismissStep, request: Request
) -> setup_checklist.SetupView:
    principal = _require_admin(request)
    try:
        setup_checklist.dismiss(step, body.dismissed, principal)
        return setup_checklist.view(server._db())
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
