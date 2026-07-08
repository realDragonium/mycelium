"""Configured code sources for research runs.

A source is a codebase this Mycelium instance derives knowledge from. Sources
are configured through `MYCELIUM_SOURCES`, a JSON object keyed by source name:

    {"acme-api": {"owner": "acme", "repo": "api", "ref": "main",
                  "token_env": "ACME_GH_TOKEN"}}

`token_env` is the name of the environment variable holding the GitHub PAT,
not the PAT itself. Production can inject that secret through Secrets Manager
without ever placing it in the JSON config.

Deployments must provide `MYCELIUM_SOURCES`, each token env var named by
configured sources, and may provide `MYCELIUM_RESEARCH_CLONE_TIMEOUT_S` to
override the default clone timeout.

All git/GitHub mechanics live in this module only. The rest of the research
package sees a directory, and credentials never appear in logs, traces, or
error messages.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping


class SourceError(RuntimeError):
    """Raised for config or fetch failures. Messages are ALWAYS pre-scrubbed."""


@dataclass(frozen=True)
class Source:
    name: str
    owner: str
    repo: str
    ref: str | None = None
    token_env: str | None = None
    host: str = "github.com"


def load_sources(env: Mapping[str, str] | None = None) -> dict[str, Source]:
    e = env or os.environ
    raw = e.get("MYCELIUM_SOURCES")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"MYCELIUM_SOURCES is not valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise SourceError("MYCELIUM_SOURCES must be a JSON object keyed by source name")

    sources: dict[str, Source] = {}
    for name, entry in parsed.items():
        if not isinstance(entry, dict):
            raise SourceError(f"source {name!r} must be a JSON object")

        owner = entry.get("owner")
        repo = entry.get("repo")
        if not owner:
            raise SourceError(f"source {name!r} is missing required field 'owner'")
        if not repo:
            raise SourceError(f"source {name!r} is missing required field 'repo'")

        sources[str(name)] = Source(
            name=str(name),
            owner=str(owner),
            repo=str(repo),
            ref=_optional_str(entry.get("ref")),
            token_env=_optional_str(entry.get("token_env")),
            host=str(entry.get("host") or "github.com"),
        )
    return sources


def get_source(name: str, env: Mapping[str, str] | None = None) -> Source:
    sources = load_sources(env)
    try:
        return sources[name]
    except KeyError as exc:
        configured = ", ".join(sorted(sources)) or "(none)"
        raise SourceError(f"unknown source {name!r}; configured sources: {configured}") from exc


@contextmanager
def fetch(source: Source, env: Mapping[str, str] | None = None) -> Iterator[Path]:
    e = env or os.environ
    token = None
    if source.token_env:
        token = e.get(source.token_env)
        if not token:
            raise SourceError(f"missing token env var {source.token_env}")

    tmp = Path(tempfile.mkdtemp(prefix="mycelium-research-"))
    dest = tmp / "repo"
    url = _clone_url(source, token)
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        *(["--branch", source.ref] if source.ref else []),
        url,
        str(dest),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_clone_timeout_s(),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        message = f"git clone timed out after {exc.timeout} seconds: {exc}"
        # `from None`: the chained TimeoutExpired carries the token-bearing
        # clone command; a logged traceback must not resurrect it.
        raise SourceError(_scrub(message, [token or ""])) from None
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SourceError(_scrub(f"git clone failed: {exc}", [token or ""])) from exc

    if result.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        message = (
            f"git clone failed with exit code {result.returncode}: "
            f"{result.stderr or result.stdout}"
        )
        raise SourceError(_scrub(message, [token or ""]))

    # Git persists the token-bearing remote URL in .git/config; deleting .git
    # ensures the yielded workspace no longer contains clone credentials.
    shutil.rmtree(dest / ".git", ignore_errors=True)

    try:
        yield dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _scrub(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def _clone_timeout_s() -> float:
    v = os.environ.get("MYCELIUM_RESEARCH_CLONE_TIMEOUT_S")
    return float(v) if v else 120.0


def _clone_url(source: Source, token: str | None) -> str:
    if token:
        return (
            f"https://x-access-token:{token}@"
            f"{source.host}/{source.owner}/{source.repo}.git"
        )
    return f"https://{source.host}/{source.owner}/{source.repo}.git"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
