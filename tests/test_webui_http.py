"""/ui/ and /cockpit/ serve the committed frontend build.

Both apps load their bundles from /ui/assets/ (see frontend/vite.config.ts), so
the failure to guard is a page that is served while its bundles 404 — it loads
blank in the browser and nothing fails server-side.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from mycelium import auth
from mycelium.http import AuthMiddleware, app


def test_each_app_page_and_its_bundles_are_served(monkeypatch):
    async def resolve(*_):
        return auth.Principal(id="fixture", name="Fixture", role="reader", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    client = TestClient(app)
    for page_path in ("/ui/", "/cockpit/"):
        page = client.get(page_path)
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        bundles = re.findall(r'(?:src|href)="(/ui/assets/[^"]+)"', page.text)
        assert any(b.endswith(".js") for b in bundles)
        assert any(b.endswith(".css") for b in bundles)
        for bundle in bundles:
            assert client.get(bundle).status_code == 200, bundle
