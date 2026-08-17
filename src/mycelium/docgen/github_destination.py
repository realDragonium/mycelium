"""GitHub delivery through the Git Data and pull request APIs."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote, urlsplit

import httpx

from .destinations import (
    Delivery,
    DeliveryDocument,
    DestinationConfig,
    DestinationError,
    _scrub,
    render_path,
)

_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_BASE_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]+)?\Z")
_TOKEN_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
_BRANCH_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_OBJECT_ID_RE = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})\Z")
_CONFIG_FIELDS = frozenset({"owner", "repo", "token_env", "host", "base_branch"})
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True)
class GitHubConfig:
    destination: DestinationConfig
    owner: str
    repo: str
    token_env: str
    base_branch: str
    host: str = "github.com"

    @classmethod
    def parse(cls, destination: DestinationConfig) -> GitHubConfig:
        entry = destination.settings
        if not isinstance(entry, dict):
            raise DestinationError(
                f"destination {destination.name!r} config must be a JSON object"
            )
        if set(entry) - _CONFIG_FIELDS:
            raise DestinationError(
                f"destination {destination.name!r} config contains an unknown field"
            )

        owner = _required_string(destination.name, entry, "owner")
        repo = _required_string(destination.name, entry, "repo")
        token_env = _required_string(destination.name, entry, "token_env")
        base_branch = _required_string(destination.name, entry, "base_branch")
        host = _optional_string(destination.name, entry, "host", "github.com")
        return cls(
            destination=destination,
            owner=_validate(destination.name, "owner", owner, _OWNER_REPO_RE),
            repo=_validate(destination.name, "repo", repo, _OWNER_REPO_RE),
            token_env=_validate(
                destination.name, "token_env", token_env, _TOKEN_ENV_RE
            ),
            base_branch=_validate(
                destination.name, "base_branch", base_branch, _BASE_BRANCH_RE
            ),
            host=_validate(destination.name, "host", host, _HOST_RE),
        )


def parse_config(destination: DestinationConfig) -> GitHubConfig:
    return GitHubConfig.parse(destination)


@dataclass(frozen=True)
class GitHubDestination:
    config: DestinationConfig
    env: Mapping[str, str] | None = None

    def deliver(self, document: DeliveryDocument) -> Delivery:
        return deliver(self.config, document, self.env)


def deliver(
    destination: DestinationConfig,
    document: DeliveryDocument,
    env: Mapping[str, str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> Delivery:
    config = GitHubConfig.parse(destination)
    e = os.environ if env is None else env
    token = e.get(config.token_env)
    if not token:
        raise DestinationError(f"missing token env var {config.token_env}")

    try:
        if client is not None:
            return _deliver(client, config, document, token)
        with _client(config, token) as owned_client:
            return _deliver(owned_client, config, document, token)
    except DestinationError as exc:
        raise DestinationError(_scrub(str(exc), [token])) from None
    except Exception as exc:
        raise DestinationError(
            _scrub(f"destination {destination.name!r} delivery failed: {exc}", [token])
        ) from None


def _client(config: GitHubConfig, token: str) -> httpx.Client:
    return httpx.Client(
        headers=_headers(token),
        follow_redirects=False,
        timeout=30.0,
    )


def _deliver(
    client: httpx.Client,
    config: GitHubConfig,
    document: DeliveryDocument,
    token: str,
) -> Delivery:
    path = render_path(config.destination, document)
    branch = _branch_name(config, document)
    parent_sha, base_tree_sha, branch_exists = _delivery_base(
        config, branch, client, token
    )
    content_sha = _blob(config, document, client, token)
    tree_sha = _tree(config, path, base_tree_sha, content_sha, client, token)
    delivery_sha = _commit(config, document, parent_sha, tree_sha, client, token)
    _set_branch(config, branch, delivery_sha, branch_exists, client, token)
    reference = _review(config, document, branch, client, token)
    return Delivery(
        destination=config.destination.name,
        path=path,
        reference=reference,
        content_revision=content_sha,
    )


def _delivery_base(
    config: GitHubConfig,
    branch: str,
    client: httpx.Client,
    token: str,
) -> tuple[str, str, bool]:
    ref = f"heads/{branch}"
    existing = _request_json(
        client,
        config,
        token,
        "GET",
        f"/git/ref/{quote(ref, safe='/')}",
        allow_not_found=True,
    )
    if existing is None:
        parent_sha, tree_sha = _base(config, client, token)
        return parent_sha, tree_sha, False
    try:
        parent_sha = _object_id(config, existing["object"]["sha"], "branch")
    except (KeyError, TypeError):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid branch "
            "response"
        ) from None
    payload = _request_json(
        client,
        config,
        token,
        "GET",
        f"/git/commits/{quote(parent_sha, safe='')}",
    )
    try:
        tree_sha = payload["tree"]["sha"]
    except (KeyError, TypeError):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid branch "
            "commit response"
        ) from None
    return parent_sha, _object_id(config, tree_sha, "branch tree"), True


def _base(config: GitHubConfig, client: httpx.Client, token: str) -> tuple[str, str]:
    payload = _request_json(
        client,
        config,
        token,
        "GET",
        f"/branches/{quote(config.base_branch, safe='')}",
    )
    try:
        parent_sha = payload["commit"]["sha"]
        tree_sha = payload["commit"]["commit"]["tree"]["sha"]
    except (KeyError, TypeError):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid base "
            "branch response"
        ) from None
    return (
        _object_id(config, parent_sha, "base commit"),
        _object_id(config, tree_sha, "base tree"),
    )


def _blob(
    config: GitHubConfig,
    document: DeliveryDocument,
    client: httpx.Client,
    token: str,
) -> str:
    expected_sha = _git_blob_id(document.body)
    payload = _request_json(
        client,
        config,
        token,
        "POST",
        "/git/blobs",
        json={"content": document.body, "encoding": "utf-8"},
    )
    content_sha = _sha(config, payload, "blob")
    if content_sha != expected_sha:
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid blob response"
        )
    return content_sha


def _tree(
    config: GitHubConfig,
    path: str,
    base_tree_sha: str,
    content_sha: str,
    client: httpx.Client,
    token: str,
) -> str:
    payload = _request_json(
        client,
        config,
        token,
        "POST",
        "/git/trees",
        json={
            "base_tree": base_tree_sha,
            "tree": [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": content_sha,
                }
            ],
        },
    )
    return _sha(config, payload, "tree")


def _commit(
    config: GitHubConfig,
    document: DeliveryDocument,
    parent_sha: str,
    tree_sha: str,
    client: httpx.Client,
    token: str,
) -> str:
    payload = _request_json(
        client,
        config,
        token,
        "POST",
        "/git/commits",
        json={
            "message": f"Deliver {document.title}",
            "tree": tree_sha,
            "parents": [parent_sha],
        },
    )
    return _sha(config, payload, "commit")


def _set_branch(
    config: GitHubConfig,
    branch: str,
    commit_sha: str,
    branch_exists: bool,
    client: httpx.Client,
    token: str,
) -> None:
    ref = f"heads/{branch}"
    if not branch_exists:
        _request_json(
            client,
            config,
            token,
            "POST",
            "/git/refs",
            json={"ref": f"refs/{ref}", "sha": commit_sha},
            branch_moved_on_conflict=True,
        )
        return
    _request_json(
        client,
        config,
        token,
        "PATCH",
        f"/git/refs/{quote(ref, safe='/')}",
        json={"sha": commit_sha},
        branch_moved_on_conflict=True,
    )


def _review(
    config: GitHubConfig,
    document: DeliveryDocument,
    branch: str,
    client: httpx.Client,
    token: str,
) -> str:
    existing = _request_json(
        client,
        config,
        token,
        "GET",
        "/pulls",
        expect_list=True,
        params={"state": "open", "head": f"{config.owner}:{branch}"},
    )
    if existing:
        first = existing[0]
        if not isinstance(first, dict):
            raise DestinationError(
                f"destination {config.destination.name!r} returned an invalid "
                "review response"
            )
        return _review_reference(config, first)

    provenance = "\n".join(
        f"- `{statement_id}`" for statement_id in document.statement_ids
    )
    payload = _request_json(
        client,
        config,
        token,
        "POST",
        "/pulls",
        json={
            "title": f"Deliver {document.title}",
            "head": branch,
            "base": config.base_branch,
            "body": "Generated from substrate statements:\n\n" + provenance,
        },
    )
    return _review_reference(config, payload)


def _review_reference(config: GitHubConfig, payload: dict) -> str:
    reference = payload.get("html_url")
    if not _valid_reference(config, reference):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid review "
            "response"
        )
    return reference


def _valid_reference(config: GitHubConfig, reference: object) -> bool:
    if not isinstance(reference, str):
        return False
    if any(
        character.isspace() or unicodedata.category(character) == "Cc"
        for character in reference
    ):
        return False
    try:
        parsed = urlsplit(reference)
        authority = _normalized_authority(parsed.hostname or "", parsed.port)
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or authority != _normalized_host(config.host)
    ):
        return False
    parts = parsed.path.split("/")
    return (
        len(parts) == 5
        and _ascii_lower(parts[1]) == _ascii_lower(config.owner)
        and _ascii_lower(parts[2]) == _ascii_lower(config.repo)
        and parts[3] == "pull"
        and parts[4].isascii()
        and parts[4].isdigit()
    )


def _request_json(
    client: httpx.Client,
    config: GitHubConfig,
    token: str,
    method: str,
    path: str,
    *,
    allow_not_found: bool = False,
    branch_moved_on_conflict: bool = False,
    expect_list: bool = False,
    **kwargs,
) -> dict | list | None:
    url = _api_base(config) + f"/repos/{config.owner}/{config.repo}" + path
    try:
        response = client.request(method, url, headers=_headers(token), **kwargs)
    except httpx.HTTPError as exc:
        raise DestinationError(
            _scrub(
                f"destination {config.destination.name!r} request failed: {exc}",
                [token],
            )
        ) from None
    if allow_not_found and response.status_code == 404:
        return None
    if branch_moved_on_conflict and response.status_code in {409, 422}:
        raise DestinationError(
            f"destination {config.destination.name!r} branch moved during delivery"
        )
    if not response.is_success:
        detail = response.text[:500]
        raise DestinationError(
            _scrub(
                f"destination {config.destination.name!r} request failed with HTTP "
                f"{response.status_code}: {detail}",
                [token],
            )
        ) from None
    try:
        payload = response.json()
    except ValueError:
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid JSON response"
        ) from None
    expected_type = list if expect_list else dict
    if not isinstance(payload, expected_type):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid response"
        )
    return payload


def _api_base(config: GitHubConfig) -> str:
    host = _normalized_host(config.host)
    if host == "github.com":
        return "https://api.github.com"
    return f"https://{host}/api/v3"


def _normalized_host(host: str) -> str:
    hostname, separator, port = host.partition(":")
    return _normalized_authority(hostname, int(port) if separator else None)


def _normalized_authority(hostname: str, port: int | None) -> str:
    normalized = hostname.rstrip(".").lower()
    if port is None or port == 443:
        return normalized
    return f"{normalized}:{port}"


def _ascii_lower(value: str) -> str:
    return value.translate(_ASCII_LOWER)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _branch_name(config: GitHubConfig, document: DeliveryDocument) -> str:
    parts = (document.slug, document.id)
    if any(not _BRANCH_PART_RE.match(part) or ".." in part for part in parts):
        raise DestinationError(
            f"destination {config.destination.name!r} cannot derive a branch from "
            "the document"
        )
    return f"mycelium/docs/{document.slug}-{document.id}"


def _sha(config: GitHubConfig, payload: dict, object_name: str) -> str:
    return _object_id(config, payload.get("sha"), object_name)


def _object_id(config: GitHubConfig, value: object, object_name: str) -> str:
    if not isinstance(value, str) or not _OBJECT_ID_RE.fullmatch(value):
        raise DestinationError(
            f"destination {config.destination.name!r} returned an invalid "
            f"{object_name} response"
        )
    return value


def _git_blob_id(body: str) -> str:
    content = body.encode("utf-8")
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _validate(name: str, field: str, value: str, pattern: re.Pattern[str]) -> str:
    if not pattern.match(value) or ".." in value:
        raise DestinationError(
            f"destination {name!r} has an invalid {field!r} value "
            "(must match the destination's own naming, with no leading '-', "
            "'..', or URL control characters)"
        )
    return value


def _required_string(name: str, entry: dict, field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DestinationError(
            f"destination {name!r} is missing required config field {field!r}"
        )
    return value


def _optional_string(name: str, entry: dict, field: str, default: str) -> str:
    value = entry.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise DestinationError(f"destination {name!r} has an invalid {field!r} value")
    return value
