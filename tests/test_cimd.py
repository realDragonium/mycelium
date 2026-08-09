"""Client ID Metadata Document resolution.

An unauthenticated caller chooses the URL we fetch here, so most of these
are about what we refuse rather than what we accept.
"""

import json

import pytest

from mycelium import cimd

DOC_URL = "https://app.example.com/oauth/client.json"

#: A stand-in resolver. The address rules get their own tests below with
#: chosen addresses; document validation should not depend on DNS.
PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731


def _doc(**overrides):
    doc = {
        "client_id": DOC_URL,
        "client_name": "Example MCP Client",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
    }
    doc.update(overrides)
    return doc


def _serving(doc, *, status: int = 200, cache_control: str | None = None):
    """A stand-in for the HTTP fetch that records how often it was called."""
    calls = []

    def get(url, address=None):
        calls.append((url, address))
        body = doc if isinstance(doc, str) else json.dumps(doc)
        return status, body, cache_control

    get.calls = calls
    return get


@pytest.fixture(autouse=True)
def _clear_cache():
    cimd.reset_cache()
    yield
    cimd.reset_cache()


# --- what counts as a metadata document id --------------------------------


def test_only_https_urls_with_a_path_are_metadata_documents():
    assert cimd.looks_like_client_id_url(DOC_URL)
    assert cimd.looks_like_client_id_url("https://example.com/c")

    # Our own registration ids must never be mistaken for one.
    assert not cimd.looks_like_client_id_url("mcp_AbC123")
    # http is not fetched: the document is a trust anchor, so its transport
    # has to be authenticated.
    assert not cimd.looks_like_client_id_url("http://app.example.com/c.json")
    # No path means the origin itself, which the spec does not allow.
    assert not cimd.looks_like_client_id_url("https://app.example.com")
    assert not cimd.looks_like_client_id_url("https://app.example.com/")
    assert not cimd.looks_like_client_id_url("")


# --- document validation ---------------------------------------------------


def test_valid_document_resolves():
    meta = cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving(_doc()))
    assert meta.client_id == DOC_URL
    assert meta.client_name == "Example MCP Client"
    assert meta.redirect_uris == ("http://127.0.0.1:3000/callback",)


def test_document_claiming_a_different_client_id_is_rejected():
    """The load-bearing check. Without it, anyone who can host a document
    could claim to be a client identified by someone else's URL."""
    doc = _doc(client_id="https://other.example.com/client.json")
    with pytest.raises(cimd.CimdError, match="client_id does not match"):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving(doc))


@pytest.mark.parametrize(
    "doc, expected",
    [
        (_doc(client_name=""), "client_name"),
        (_doc(client_name=None), "client_name"),
        ({"client_id": DOC_URL, "client_name": "X"}, "redirect_uris"),
        (_doc(redirect_uris=[]), "redirect_uris"),
        (_doc(redirect_uris="http://x/cb"), "redirect_uris"),
        (_doc(redirect_uris=[1, 2]), "redirect_uris"),
    ],
)
def test_documents_missing_required_fields_are_rejected(doc, expected):
    with pytest.raises(cimd.CimdError, match=expected):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving(doc))


def test_non_json_and_non_200_are_rejected():
    with pytest.raises(cimd.CimdError, match="not valid JSON"):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving("<html>nope</html>"))
    with pytest.raises(cimd.CimdError, match="JSON object"):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving("[]"))
    with pytest.raises(cimd.CimdError, match="HTTP 404"):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving(_doc(), status=404))


# --- SSRF fencing ----------------------------------------------------------


def test_urls_naming_non_public_hosts_are_never_fetched():
    """The fetch is a server-side request to a caller-chosen URL. A document
    is not worth reaching an address the caller could not reach themselves —
    that is the whole SSRF primitive."""
    get = _serving(_doc())

    for url in (
        "https://localhost/client.json",
        "https://127.0.0.1/client.json",
        "https://[::1]/client.json",
    ):
        with pytest.raises(cimd.CimdError, match="non-public address|does not resolve"):
            cimd.fetch(url, get=get)

    assert get.calls == [], "a rejected URL must not be requested at all"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud instance metadata
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata address
        "fd00::1",
        "0.0.0.0",
    ],
)
def test_every_non_public_address_form_is_refused(address):
    """A public name is checked by where it *resolves*, not by how it is
    spelled — including the IPv4-mapped IPv6 forms, which are easy to
    assume are covered and easy to leave uncovered."""
    get = _serving(_doc())
    with pytest.raises(cimd.CimdError, match="non-public address"):
        cimd.fetch(DOC_URL, resolve=lambda h, p: [address], get=get)
    assert get.calls == []


def test_a_host_resolving_to_both_public_and_private_is_refused():
    """Checking only the first answer would let a name that returns one of
    each through, since nothing pins which address is connected to."""
    get = _serving(_doc())
    with pytest.raises(cimd.CimdError, match="non-public address"):
        cimd.fetch(
            DOC_URL, resolve=lambda h, p: ["93.184.216.34", "127.0.0.1"], get=get
        )
    assert get.calls == []


def test_malformed_and_non_https_urls_are_rejected_before_any_request():
    get = _serving(_doc())
    for url in (
        "http://app.example.com/client.json",
        "https://app.example.com",
        "not-a-url",
        "",
    ):
        with pytest.raises(cimd.CimdError):
            cimd.fetch(url, get=get)
    assert get.calls == []


# --- caching ---------------------------------------------------------------


def test_a_resolved_document_is_reused_rather_than_refetched():
    get = _serving(_doc(), cache_control="max-age=600")
    first = cimd.fetch(DOC_URL, resolve=PUBLIC, get=get)
    second = cimd.fetch(DOC_URL, resolve=PUBLIC, get=get)
    assert first == second
    assert len(get.calls) == 1


def test_a_request_not_to_store_is_obeyed_rather_than_clamped():
    """A client that has just revoked a compromised redirect publishes
    `no-store` precisely so the old document stops counting. Clamping that
    up to a minimum would keep honouring the revoked list for a window the
    client explicitly asked us not to take."""
    assert cimd._cache_seconds("no-store") == 0
    assert cimd._cache_seconds("no-cache") == 0
    assert cimd._cache_seconds("max-age=0") == 0
    assert cimd._cache_seconds("private, no-store") == 0


def test_a_request_to_reuse_is_clamped():
    """Where the directive asks for reuse, the bounds only limit how much of
    it we grant."""
    assert cimd._cache_seconds("max-age=1") == cimd.MIN_CACHE_SECONDS
    assert cimd._cache_seconds("max-age=99999999") == cimd.MAX_CACHE_SECONDS
    assert cimd._cache_seconds("max-age=600") == 600
    assert cimd._cache_seconds(None) == cimd.DEFAULT_CACHE_SECONDS
    assert cimd._cache_seconds("max-age=abc") == cimd.DEFAULT_CACHE_SECONDS


def test_a_no_store_document_is_refetched_every_time():
    get = _serving(_doc(), cache_control="no-store")
    cimd.fetch(DOC_URL, resolve=PUBLIC, get=get)
    cimd.fetch(DOC_URL, resolve=PUBLIC, get=get)
    assert len(get.calls) == 2


def test_the_cache_is_bounded():
    """Distinct URLs are free for an anonymous caller to mint, so an
    unbounded cache is a way to grow a worker's memory until it dies."""
    for i in range(cimd.MAX_CACHED_DOCUMENTS + 40):
        url = f"https://app.example.com/c/{i}.json"
        cimd.fetch(
            url,
            resolve=PUBLIC,
            get=_serving({**_doc(), "client_id": url}, cache_control="max-age=600"),
        )
    assert len(cimd._CACHE) <= cimd.MAX_CACHED_DOCUMENTS


def test_a_rejected_document_is_not_cached():
    """Otherwise a client that fixed its document would stay broken for the
    cache lifetime."""
    bad = _serving(_doc(client_name=""))
    with pytest.raises(cimd.CimdError):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=bad)

    good = _serving(_doc())
    assert cimd.fetch(DOC_URL, resolve=PUBLIC, get=good).client_name == "Example MCP Client"


def test_documents_with_userinfo_redirects_are_rejected():
    """`https://login.trusted.example@evil.example/cb` reads as the trusted
    host on a consent page while sending the code to evil.example."""
    doc = _doc(redirect_uris=["https://login.trusted.example@evil.example/cb"])
    with pytest.raises(cimd.CimdError, match="userinfo"):
        cimd.fetch(DOC_URL, resolve=PUBLIC, get=_serving(doc))


@pytest.mark.parametrize(
    "url",
    [
        "https://app.example.com:8443/client.json",  # port sweeping
        "https://app.example.com:99999/client.json",  # unparseable port
        "https://user@app.example.com/client.json",  # userinfo
    ],
)
def test_urls_that_would_widen_the_fetch_are_rejected(url):
    """Each of these turns the fetch into something other than 'GET a
    document from a public web server on 443'."""
    get = _serving(_doc())
    with pytest.raises(cimd.CimdError):
        cimd.fetch(url, resolve=PUBLIC, get=get)
    assert get.calls == []


def test_the_connection_targets_the_address_that_was_vetted():
    """The check is only worth anything if its answer is what gets connected
    to. Re-resolving the hostname to open the socket would let a name answer
    differently the second time and reach whatever it liked."""
    get = _serving(_doc())
    cimd.fetch(DOC_URL, resolve=lambda h, p: ["93.184.216.34"], get=get)
    (url, address), = get.calls
    assert url == DOC_URL
    assert address == "93.184.216.34"


def test_the_pinned_url_keeps_the_path_and_brackets_ipv6():
    """The request goes to the address, so the rest of the URL has to survive
    the substitution — and an IPv6 literal needs brackets to be a valid host."""
    assert (
        cimd._pinned_url("https://app.example.com/oauth/client.json", "93.184.216.34")
        == "https://93.184.216.34/oauth/client.json"
    )
    assert (
        cimd._pinned_url("https://app.example.com/c.json?v=2", "2606:2800:220:1::1")
        == "https://[2606:2800:220:1::1]/c.json?v=2"
    )
