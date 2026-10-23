"""/ui/ serves the committed frontend build, and the retired /cockpit redirects.

The app loads its bundles from /ui/assets/ (see frontend/vite.config.ts), so
the failure to guard is a page that is served while its bundles 404 — it loads
blank in the browser and nothing fails server-side.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from mycelium import auth
from mycelium.http import create_app
from mycelium.http.authentication import AuthMiddleware


def _reader(monkeypatch):
    async def resolve(*_):
        return auth.Principal(id="fixture", name="Fixture", role="reader", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    return TestClient(create_app())


def test_the_app_page_and_its_bundles_are_served(monkeypatch):
    client = _reader(monkeypatch)
    page = client.get("/ui/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    bundles = re.findall(r'(?:src|href)="(/ui/assets/[^"]+)"', page.text)
    assert any(b.endswith(".js") for b in bundles)
    assert any(b.endswith(".css") for b in bundles)
    for bundle in bundles:
        assert client.get(bundle).status_code == 200, bundle


def test_cockpit_links_redirect_permanently_to_the_app(monkeypatch):
    client = _reader(monkeypatch)
    for path in ("/cockpit", "/cockpit/", "/cockpit/index.html"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 301, path
        assert response.headers["location"] == "/ui/"
