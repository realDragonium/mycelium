"""Admin settings: product settings, AI model choices and the draft-review setup.

Anyone authenticated may read them; only an admin may save. A conflicting save
answers 409, and unavailable settings 503.
"""

from __future__ import annotations

import anyio.from_thread
from fastapi import APIRouter, HTTPException, Request

from .. import draft_review_settings as review_settings
from .. import model_settings, product_settings, server
from .access import _require_admin, _require_principal

router = APIRouter()


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
    except model_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


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
    except model_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


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
    except review_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
