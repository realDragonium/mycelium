"""Admin browser connection flow. Temporary credentials stay in this process."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth, github_app, github_connections

router = APIRouter(prefix="/api/github")
TTL = 600


@dataclass(frozen=True)
class Flow:
    principal_id: str
    browser_id: str
    return_to: str
    expires: float
    phase: Literal["install", "authorize", "select"]
    verifier: str = field(repr=False)
    installation_id: int | None = None
    token: str | None = field(default=None, repr=False)


class Flows:
    def __init__(self) -> None:
        self._items: dict[str, Flow] = {}
        self._lock = threading.Lock()

    def put(self, flow: Flow) -> str:
        with self._lock:
            self._items = {
                key: value
                for key, value in self._items.items()
                if value.expires > time.monotonic()
            }
            if len(self._items) >= 1000:
                raise github_app.GitHubError(
                    "Too many GitHub connection attempts. Try again later."
                )
            key = secrets.token_urlsafe(32)
            self._items[key] = flow
            return key

    def get(
        self,
        key: str,
        principal_id: str,
        browser_id: str,
        phase: str,
        *,
        consume: bool = False,
    ) -> Flow:
        with self._lock:
            flow = self._items.get(key)
            if flow is None or flow.expires <= time.monotonic():
                self._items.pop(key, None)
                raise github_app.GitHubError(
                    "GitHub setup expired or the server restarted. Connect GitHub again."
                )
            if (
                flow.principal_id != principal_id
                or flow.browser_id != browser_id
                or flow.phase != phase
            ):
                raise github_app.GitHubError(
                    "GitHub setup does not belong to this browser session. Connect GitHub again."
                )
            if consume:
                del self._items[key]
            return flow


flows = Flows()


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    existing: bool = False
    surface: Literal["ui", "cockpit"] = "ui"


class SelectRepository(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    base_branch: str = Field(min_length=1, max_length=200)


class Disconnect(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str


class ConnectionView(BaseModel):
    name: str
    owner: str
    repo: str
    enabled: bool


class Status(BaseModel):
    configured: bool
    can_configure: bool
    selecting: bool
    connections: list[ConnectionView]
    message: str | None = None


class Connected(BaseModel):
    name: str
    owner: str
    repo: str
    base_branch: str


def _admin(request: Request) -> auth.Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, auth.Principal) or not principal.is_admin:
        raise HTTPException(403, "Administrator access is required to connect GitHub.")
    return principal


def _browser(request: Request) -> str:
    browser = request.session.get("github_browser")
    if not isinstance(browser, str):
        browser = secrets.token_urlsafe(32)
        request.session["github_browser"] = browser
    return browser


def _mutation(request: Request) -> auth.Principal:
    principal = _admin(request)
    expected = str(request.base_url).rstrip("/")
    if (
        request.headers.get("origin", expected) != expected
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(
            403, "GitHub setup must be started from this Mycelium instance."
        )
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "A JSON request is required.")
    return principal


def _flow(
    request: Request, phase: str, *, state: str | None = None, consume: bool = False
) -> Flow:
    principal = _admin(request)
    key = state if state is not None else request.session.get("github_selection", "")
    if not isinstance(key, str):
        raise github_app.GitHubError("Connect GitHub again.")
    return flows.get(key, principal.id, _browser(request), phase, consume=consume)


def _authorize(config: github_app.AppConfig, state: str, verifier: str) -> str:
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.callback_url,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


@router.get("")
def status(request: Request) -> Status:
    principal = getattr(request.state, "principal", None)
    can_configure = isinstance(principal, auth.Principal) and principal.is_admin
    message = None
    try:
        github_app.AppConfig.load()
    except github_app.GitHubError as exc:
        message = str(exc)
    selecting = False
    if can_configure and request.session.get("github_selection"):
        try:
            _flow(request, "select")
            selecting = True
        except github_app.GitHubError as exc:
            message = str(exc)
            request.session.pop("github_selection", None)
    return Status(
        configured=_configured(),
        can_configure=can_configure,
        selecting=selecting,
        connections=[
            ConnectionView(
                name=item.name, owner=item.owner, repo=item.repo, enabled=item.enabled
            )
            for item in github_connections.load().values()
        ],
        message=message,
    )


def _configured() -> bool:
    try:
        github_app.AppConfig.load()
        return True
    except github_app.GitHubError:
        return False


@router.post("/start")
def start(body: Start, request: Request) -> dict[str, str]:
    principal = _mutation(request)
    config = github_app.AppConfig.load()
    callback = urlsplit(config.callback_url)
    if f"{callback.scheme}://{callback.netloc}" != str(request.base_url).rstrip("/"):
        raise github_app.GitHubError(
            "The GitHub App callback URL must use this Mycelium instance's origin."
        )
    verifier = secrets.token_urlsafe(48)
    flow = Flow(
        principal.id,
        _browser(request),
        f"/{body.surface}/#/documentation?tab=settings",
        time.monotonic() + TTL,
        "authorize" if body.existing else "install",
        verifier,
    )
    state = flows.put(flow)
    url = (
        _authorize(config, state, verifier)
        if body.existing
        else f"https://github.com/apps/{config.slug}/installations/new?"
        + urlencode({"state": state})
    )
    return {"url": url}


@router.get("/setup")
def setup(
    request: Request, state: str = "", installation_id: int | None = None
) -> Response:
    if not state:
        return HTMLResponse("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finish connecting GitHub · Mycelium</title>
<style>
body{font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:48px auto;
padding:0 24px;color:#222;background:#faf9f6}a{color:#285b86}
</style>
</head>
<body>
<h1>Finish connecting GitHub</h1>
<p>If you installed the App directly on GitHub, a Mycelium administrator can
finish connecting it in <a href="/ui/#/documentation?tab=settings">Documentation
settings</a> by choosing <strong>Use existing GitHub installation</strong>.</p>
<p>If you installed it for someone else, let them know they can complete that step.
If GitHub connection is unavailable, the server administrator must finish the
GitHub App credentials setup first.</p>
</body>
</html>""")
    flow = _flow(request, "install", state=state, consume=True)
    if installation_id is None or installation_id <= 0:
        return RedirectResponse(flow.return_to + "&github=pending", status_code=303)
    next_flow = Flow(
        flow.principal_id,
        flow.browser_id,
        flow.return_to,
        flow.expires,
        "authorize",
        flow.verifier,
        installation_id,
    )
    next_state = flows.put(next_flow)
    return RedirectResponse(
        _authorize(github_app.AppConfig.load(), next_state, flow.verifier),
        status_code=303,
    )


@router.get("/callback")
def callback(
    request: Request, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    flow = _flow(request, "authorize", state=state, consume=True)
    if error or not code:
        return RedirectResponse(flow.return_to + "&github=cancelled", status_code=303)
    with github_app.client() as transport:
        api = github_app.GitHubClient(transport, github_app.AppConfig.load())
        token = api.exchange(code, flow.verifier)
        # A setup URL's installation ID is untrusted until checked through the user token.
        api.repositories(token, flow.installation_id)
    selected = Flow(
        flow.principal_id,
        flow.browser_id,
        flow.return_to,
        time.monotonic() + TTL,
        "select",
        "",
        flow.installation_id,
        token,
    )
    request.session["github_selection"] = flows.put(selected)
    return RedirectResponse(flow.return_to + "&github=ready", status_code=303)


def _selection(request: Request) -> tuple[Flow, str]:
    flow = _flow(request, "select")
    if flow.token is None:
        raise github_app.GitHubError("Connect GitHub again.")
    return flow, flow.token


@router.get("/repositories")
def repositories(request: Request) -> list[github_app.RepositoryChoice]:
    flow, token = _selection(request)
    with github_app.client() as transport:
        return github_app.GitHubClient(
            transport, github_app.AppConfig.load()
        ).repositories(token, flow.installation_id)


@router.post("/connections")
def connect_repository(body: SelectRepository, request: Request) -> Connected:
    _mutation(request)
    flow, token = _selection(request)
    config = github_app.AppConfig.load()
    with github_app.client() as transport:
        api = github_app.GitHubClient(transport, config)
        allowed = api.repositories(token, flow.installation_id)
        selected = next(
            (
                item
                for item in allowed
                if item.installation_id == body.installation_id
                and item.repository_id == body.repository_id
            ),
            None,
        )
        if selected is None:
            raise github_app.GitHubError(
                "You cannot connect this repository. Refresh the repository list and check GitHub access."
            )
        api.verify_repository(
            token, selected.repository_id, selected.owner, selected.repo
        )
        api.verify_branch(token, selected.owner, selected.repo, body.base_branch)
        app_token = api.installation_token(
            selected.installation_id, selected.repository_id
        )
        api.verify_repository(
            app_token, selected.repository_id, selected.owner, selected.repo
        )
    connection = github_connections.Connection(
        app_id=config.app_id,
        installation_id=selected.installation_id,
        repository_id=selected.repository_id,
        owner=selected.owner,
        repo=selected.repo,
    )
    github_connections.save(connection)
    return Connected(
        name=connection.name,
        owner=connection.owner,
        repo=connection.repo,
        base_branch=body.base_branch,
    )


@router.post("/disconnect")
def disconnect(body: Disconnect, request: Request) -> dict[str, bool]:
    _mutation(request)
    github_connections.disconnect(body.name)
    return {"disconnected": True}
