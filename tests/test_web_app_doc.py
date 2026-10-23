"""`docs/WEB_APP.md` lists the screens and settings sections the router has."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ROUTER = (_ROOT / "frontend" / "ui" / "router.tsx").read_text()
_DOC = (_ROOT / "docs" / "WEB_APP.md").read_text()


def _doc_section(heading: str) -> str:
    return _DOC.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_every_canonical_screen_address_is_documented():
    route_to_hash = _ROUTER.split("export function routeToHash", 1)[1]
    route_to_hash = route_to_hash.split("\n}\n", 1)[0]
    canonical = set(re.findall(r"['`]#/([a-z]*)", route_to_hash))
    documented = set(re.findall(r"`#/([a-z]*)", _doc_section("Where things are")))

    assert documented == canonical


def test_every_settings_section_is_documented():
    sections = _ROUTER.split("SETTINGS_SECTIONS = [", 1)[1].split("]", 1)[0]
    documented = re.findall(r"`#/settings/([a-z]+)`", _doc_section("Settings"))

    assert set(documented) == set(re.findall(r"'([a-z]+)'", sections))
