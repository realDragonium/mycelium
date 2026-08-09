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

#: Per-operation budget (connect, read, write). httpx resets this on every
#: operation, so it bounds a stall but not a slow drip.
FETCH_TIMEOUT_SECONDS = 5.0

#: Budget for the whole fetch, which is what actually bounds how long a
#: hostile endpoint can occupy a worker while a user waits on the consent
#: page. Enforced by us, because httpx has no equivalent.
TOTAL_FETCH_SECONDS = 10.0

#: How many documents to keep. The cache is fed by unauthenticated callers,
#: so it needs a ceiling: distinct URLs are free to mint and each entry costs
#: memory for as long as it lives.
MAX_CACHED_DOCUMENTS = 256

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


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether `ip` is an ordinary address on the public internet.

    Written as an allowlist because the blocklist version of this is wrong
    in ways that do not announce themselves: `is_private` alone misses
    carrier-grade NAT (100.64.0.0/10), and deprecated IPv6 site-local
    (fec0::/10) reports `is_global` as True while being anything but. Only
    `is_global` says yes for the addresses we actually want, and the two
    exclusions cover where it says yes too readily.
    """
    if getattr(ip, "is_site_local", False):
        return False
    if ip.is_multicast:
        return False
    return ip.is_global


def _assert_fetchable(
    url: str, resolve: Callable[[str, int], list[str]] = _resolve_addresses
) -> None:
    """Reject a URL that names anything but a public internet host.

    Every address the hostname resolves to is checked, not just the first:
    a name returning one public and one internal address would otherwise be
    a way through, since nothing pins which one is connected to.

    That last part is also the limit of this check. It runs before the
    request, so a name that answers differently the second time — DNS
    rebinding — defeats it, and the internal GET still happens. Closing
    that needs the socket pinned to a vetted address while keeping the
    hostname for SNI, which the HTTP client does not expose. What is here
    instead: no redirects, no proxy, port 443 only so this cannot be used
    to sweep internal ports, and a hard cap on what a response can cost.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise CimdError("client id must use https")
    host = parts.hostname
    if not host:
        raise CimdError("client id has no host")
    if parts.username or parts.password:
        raise CimdError("client id must not carry userinfo")
    try:
        port = parts.port
    except ValueError as exc:
        raise CimdError("client id has an invalid port") from exc
    if port not in (None, 443):
        raise CimdError("client id must use the default https port")

    for address in resolve(host, 443):
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise CimdError(f"unparseable address for {host}: {address}") from exc
        if not _is_public(ip):
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

    for uri in uris:
        # `https://login.trusted.example@evil.example/cb` sends the code to
        # evil.example while reading as the trusted host to anyone skimming
        # the consent page. Nothing legitimate needs userinfo in a redirect,
        # so the document is rejected rather than the display patched.
        try:
            parsed = urlsplit(uri)
        except ValueError as exc:
            raise CimdError(f"redirect_uris contains an unparseable URI: {uri}") from exc
        if parsed.username or parsed.password:
            raise CimdError("redirect_uris must not carry userinfo")

    return ClientMetadata(
        client_id=url, client_name=name.strip(), redirect_uris=tuple(uris)
    )


def _cache_seconds(cache_control: str | None) -> int:
    """How long to reuse a document, from its `Cache-Control`.

    Zero means do not store it. That case is the one that matters: a client
    that has just revoked a compromised redirect URI publishes `no-store`
    precisely so the old document stops being honoured, and clamping that
    up to a minimum would keep serving the revoked list for a window the
    client explicitly asked us not to take.

    A positive `max-age` is clamped instead, since there the directive is
    asking for reuse and the bounds only limit how much we grant.
    """
    if not cache_control:
        return DEFAULT_CACHE_SECONDS
    directives = [d.strip().lower() for d in cache_control.split(",")]
    if "no-store" in directives or "no-cache" in directives:
        return 0
    for directive in directives:
        if directive.startswith("max-age="):
            try:
                age = int(directive.split("=", 1)[1])
            except ValueError:
                break
            if age <= 0:
                return 0
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

    Every argument here is load-bearing against a hostile endpoint:

    - `follow_redirects=False`, because a redirect moves the document away
      from the URL whose equality with `client_id` is the whole validation,
      and is the usual way an SSRF pre-check gets walked around.
    - `trust_env=False`, so an ambient `HTTPS_PROXY` cannot re-resolve the
      hostname and reach somewhere the address check already refused.
    - `Accept-Encoding: identity` and a cap on the *raw* bytes, because a
      decoded stream is the compressed size the peer chose times whatever
      ratio it likes — capping after decompression caps nothing.
    - a deadline around the whole read, since httpx's timeout applies per
      operation: a peer dripping one byte every four seconds satisfies it
      indefinitely.
    """
    import httpx

    deadline = time.monotonic() + TOTAL_FETCH_SECONDS
    try:
        with httpx.Client(
            follow_redirects=False,
            trust_env=False,
            timeout=FETCH_TIMEOUT_SECONDS,
        ) as http:
            with http.stream(
                "GET",
                url,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as resp:
                body = bytearray()
                for chunk in resp.iter_raw():
                    if time.monotonic() > deadline:
                        raise CimdError("client metadata document took too long")
                    body.extend(chunk)
                    if len(body) > MAX_DOCUMENT_BYTES:
                        raise CimdError("client metadata document is too large")
                return (
                    resp.status_code,
                    body.decode("utf-8", errors="replace"),
                    resp.headers.get("cache-control"),
                )
    except CimdError:
        raise
    except Exception as exc:
        # TLS failures, connection resets, timeouts — all of them mean the
        # same thing here (this is not a usable client) and none of them
        # should surface as a server fault.
        raise CimdError(f"could not fetch client metadata document: {exc}") from exc


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
    _store(url, metadata, _cache_seconds(cache_control))
    return metadata


def _store(url: str, metadata: ClientMetadata, lifetime: int) -> None:
    """Cache `metadata`, keeping the cache bounded.

    Expired entries go first, so an idle cache drains rather than pinning
    whatever happened to arrive earliest. Once that is not enough, the
    oldest-expiring entry is dropped — insertion order is not a useful
    proxy here, because a document with a long `max-age` should outlive one
    that is about to expire anyway.
    """
    if lifetime <= 0:
        _CACHE.pop(url, None)
        return

    now = time.monotonic()
    if len(_CACHE) >= MAX_CACHED_DOCUMENTS:
        for key in [k for k, (_, exp) in _CACHE.items() if exp <= now]:
            del _CACHE[key]
    while len(_CACHE) >= MAX_CACHED_DOCUMENTS:
        del _CACHE[min(_CACHE, key=lambda k: _CACHE[k][1])]

    _CACHE[url] = (metadata, now + lifetime)
