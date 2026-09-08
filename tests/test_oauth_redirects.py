import pytest

from mycelium.oauth_server import _Client


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
@pytest.mark.parametrize("registered_port", ["", ":6274"])
def test_loopback_callback_accepts_session_port(host: str, registered_port: str):
    client = _Client("test", "Test", (f"http://{host}{registered_port}/callback",))

    assert client.allows(f"http://{host}:3118/callback")


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://127.0.0.1:3118/callback",
        "http://localhost.evil.example:3118/callback",
        "http://localhost@evil.example:3118/callback",
        "http://user@localhost:3118/callback",
        "https://localhost:3118/callback",
        "http://localhost:3118/other",
        "http://localhost:3118/callback/",
        "http://localhost:3118/callback?extra=1",
        "http://localhost:3118/callback?",
        "http://localhost:3118/callback#fragment",
        "http://localhost:65536/callback",
        "http://localhost:0/callback",
        "http://localhost:invalid/callback",
        "http://localhost:/callback",
        "http://local\nhost:3118/callback",
    ],
)
def test_loopback_exception_only_changes_port(redirect_uri: str):
    client = _Client("test", "Test", ("http://localhost/callback",))

    assert not client.allows(redirect_uri)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_remote_callbacks_require_exact_match(scheme: str):
    registered = f"{scheme}://app.example.com/callback"
    client = _Client("test", "Test", (registered,))

    assert client.allows(registered)
    assert not client.allows(f"{scheme}://app.example.com:3118/callback")


def test_loopback_callback_preserves_registered_query():
    client = _Client("test", "Test", ("http://localhost/callback?app=one",))

    assert client.allows("http://localhost:3118/callback?app=one")
    assert not client.allows("http://localhost:3118/callback?app=two")
