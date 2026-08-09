"""Client ID Metadata Documents — resolving an HTTPS URL used as a client_id.

The 2026-07-28 MCP revision deprecates Dynamic Client Registration in favour
of this: a client identifies itself with an HTTPS URL, and the authorization
server fetches that URL to learn the client's name and redirect URIs. Nothing
is stored on our side and no registration call happens, which is what makes a
client id portable across authorization servers.

The security shape is unusual and worth stating plainly: an unauthenticated
caller hands us a URL and we make a server-side request to it. That is a
Server-Side Request Forgery primitive unless it is fenced in, so this module
is deliberately strict — public HTTPS only, no redirects, a byte cap, a
timeout, and a check that every address the hostname resolves to is on the
public internet. A document that fails any check is not a client.

`fetch` is pure apart from the HTTP call itself, which is injectable, so the
validation rules can be tested without a network or a server.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

#: Ceiling on the document body. Client metadata is a handful of fields; a
#: response larger than this is not one, and reading it would let an attacker
#: choose how much memory the fetch costs us.
MAX_DOCUMENT_BYTES = 64 * 1024

#: Wall-clock budget for the whole fetch. A slow endpoint must not be able to
#: park a request thread: this runs while a user waits on the consent page.
FETCH_TIMEOUT_SECONDS = 5.0

#: Bounds on how long a document is reused. The spec asks us to respect HTTP
#: cache headers; these keep a hostile or misconfigured `max-age` from either
#: defeating the cache or pinning stale metadata indefinitely.
MIN_CACHE_SECONDS = 60
MAX_CACHE_SECONDS = 3600
DEFAULT_CACHE_SECONDS = 300


class CimdError(Exception):
    """A client id URL did not resolve to a usable metadata document."""


@dataclass(frozen=True)
class ClientMetadata:
    """The subset of a client's metadata document that we act on."""

    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]


def looks_like_client_id_url(value: str) -> bool:
    """Whether `value` is a client id to resolve rather than one to look up.

    The spec requires an HTTPS URL carrying a path, which is also what keeps
    this unambiguous against our own registration-issued ids: those are
    `mcp_`-prefixed opaque strings and can never parse as an https URL.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(parts.scheme == "https" and parts.netloc and parts.path.strip("/"))


def _resolve_addresses(host: str, port: int) -> list[str]:
    """Every IP `host` resolves to. Split out so the address rules can be
    tested against chosen addresses rather than whatever DNS says today."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise CimdError(f"client id host does not resolve: {host}") from exc
    return [info[4][0] for info in infos]


def _assert_fetchable(
    url: str, resolve: Callable[[str, int], list[str]] = _resolve_addresses
) -> None:
    """Reject a URL that names anything but a public internet host.

    Every address the hostname resolves to is checked, not just the first:
    a name that returns one public and one loopback address would otherwise
    be a way through, since we do not control which one the client library
    connects to.

    This is a pre-flight check, so a name that changes its answer between
    here and the request (DNS rebinding) is not covered. Closing that needs
    the connection pinned to a vetted address, which the HTTP client does
    not expose; the byte cap and the no-redirect rule are what limit the
    damage in the meantime.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise CimdError("client id must use https")
    host = parts.hostname
    if not host:
        raise CimdError("client id has no host")
    if parts.username or parts.password:
        raise CimdError("client id must not carry userinfo")

    for address in resolve(host, parts.port or 443):
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise CimdError(f"client id host resolves to a non-public address: {ip}")


def _parse(url: str, body: str) -> ClientMetadata:
    """Validate a fetched body into metadata, or raise.

    The `client_id` equality check is the load-bearing one: it is what ties
    the document to the URL the client asked us to trust, so a document
    hosted at one URL cannot claim to be a client identified by another.
    """
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise CimdError("client metadata document is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise CimdError("client metadata document must be a JSON object")

    if doc.get("client_id") != url:
        raise CimdError("client metadata document's client_id does not match its URL")

    name = doc.get("client_name")
    if not isinstance(name, str) or not name.strip():
        raise CimdError("client metadata document is missing client_name")

    uris = doc.get("redirect_uris")
    if (
        not isinstance(uris, list)
        or not uris
        or not all(isinstance(u, str) and u for u in uris)
    ):
        raise CimdError("client metadata document is missing redirect_uris")

    return ClientMetadata(
        client_id=url, client_name=name.strip(), redirect_uris=tuple(uris)
    )


def _cache_seconds(cache_control: str | None) -> int:
    """How long to reuse a document, from its `Cache-Control`, within bounds."""
    if not cache_control:
        return DEFAULT_CACHE_SECONDS
    for directive in cache_control.split(","):
        directive = directive.strip().lower()
        if directive.startswith("max-age="):
            try:
                age = int(directive.split("=", 1)[1])
            except ValueError:
                break
            return max(MIN_CACHE_SECONDS, min(MAX_CACHE_SECONDS, age))
    return DEFAULT_CACHE_SECONDS


#: url -> (metadata, monotonic expiry). Process-local: a second worker simply
#: fetches its own copy, which costs one request and keeps this free of any
#: shared-state coordination.
_CACHE: dict[str, tuple[ClientMetadata, float]] = {}


def reset_cache() -> None:
    """Drop every cached document. For tests and for an operator who has just
    changed a client's metadata and does not want to wait out its TTL."""
    _CACHE.clear()


def _default_get(url: str) -> tuple[int, str, str | None]:
    """Fetch `url`, returning (status, body, cache-control).

    Redirects are not followed. A redirect would move the document away from
    the URL whose equality with `client_id` is the whole validation, and
    following one is also the usual way an SSRF check gets walked around.
    """
    import httpx

    with httpx.Client(
        follow_redirects=False, timeout=FETCH_TIMEOUT_SECONDS
    ) as http:
        with http.stream("GET", url, headers={"Accept": "application/json"}) as resp:
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_DOCUMENT_BYTES:
                    raise CimdError("client metadata document is too large")
            return (
                resp.status_code,
                body.decode("utf-8", errors="replace"),
                resp.headers.get("cache-control"),
            )


def fetch(
    url: str,
    *,
    get: Callable[[str], tuple[int, str, Any]] | None = None,
    resolve: Callable[[str, int], list[str]] | None = None,
) -> ClientMetadata:
    """Resolve a client id URL to its metadata, honouring the cache.

    Raises `CimdError` for anything that is not a valid document from a
    fetchable URL; callers turn that into `invalid_client`.
    """
    cached = _CACHE.get(url)
    if cached is not None and cached[1] > time.monotonic():
        return cached[0]

    if not looks_like_client_id_url(url):
        raise CimdError("client id must be an https URL with a path")
    _assert_fetchable(url, resolve or _resolve_addresses)

    status, body, cache_control = (get or _default_get)(url)
    if status != 200:
        raise CimdError(f"client metadata document returned HTTP {status}")

    metadata = _parse(url, body)
    _CACHE[url] = (
        metadata,
        time.monotonic() + _cache_seconds(cache_control),
    )
    return metadata
