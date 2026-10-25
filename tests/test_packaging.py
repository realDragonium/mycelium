"""The prompt sources and browser apps a deployment receives from the built wheel.

Startup seeds guidelines and doctrines before an operator has supplied any
data, so those sources have to travel with the installed package rather than
merely live beside its source code in a checkout. These tests build the same
artifact a deployment installs and pin both the paths the shipped readers use
and the complete text that reaches the artifact.

A layout assertion cannot stand in for this. `is_relative_to(package_dir)`
says where a file sits in the checkout, which is precisely the thing that
cannot tell you whether the file was packaged — it stays green while the wheel
ships nothing but `.py`, and a deployment then comes up with an empty prompt
store and no failing test anywhere.

`pyproject.toml` deliberately names none of these files. `uv_build` has no
positive wheel allowlist to name them in: it ships everything under the module
root and subtracts `wheel-exclude` / `source-exclude`, and an invented include
key is accepted and silently ignored — config that reads as protection and
is not. So the guard belongs here, where it is executed, and the build stays
declaration-free.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from mycelium.docgen.config import DocgenConfig
from mycelium.ingest.config import IngestConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def wheel(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    built_by = subprocess.run(
        ["uv", "build", "--wheel", "--project", str(_REPO_ROOT), "--out-dir", str(out)],
        capture_output=True,
        text=True,
    )
    assert built_by.returncode == 0, f"building the wheel failed:\n{built_by.stderr}"
    built = list(out.glob("*.whl"))
    assert len(built) == 1, f"expected one wheel, got {built}"
    return built[0]


def test_doctrines_ship_inside_the_wheel(wheel):
    """Each service's startup doctrine must be present and unaltered in the
    wheel, or a deployment with an empty data volume would lose that service's
    baseline prompt even though source-tree tests continued to pass."""
    doctrine_paths = [
        DocgenConfig().doctrine_path,
        IngestConfig().doctrine_path,
    ]

    with zipfile.ZipFile(wheel) as zf:
        members = set(zf.namelist())
        for source in doctrine_paths:
            path = Path(source)
            member = path.resolve().relative_to(_REPO_ROOT / "src").as_posix()
            assert member in members
            assert zf.read(member).decode("utf-8") == path.read_text(encoding="utf-8")


def test_layout_module_runs_from_wheel_outside_checkout(wheel, tmp_path):
    extracted = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(extracted)

    db_path = tmp_path / "mycelium.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY);
        CREATE TABLE names (entity_id TEXT, text TEXT);
        CREATE TABLE entity_links (from_entity_id TEXT, to_entity_id TEXT);
        INSERT INTO entities VALUES ('login'), ('sso');
        INSERT INTO names VALUES ('login', 'Login'), ('sso', 'SSO');
        INSERT INTO entity_links VALUES ('login', 'sso');
    """)
    conn.close()
    output_path = tmp_path / "entity-positions.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mycelium.entity_layout",
            "--db",
            str(db_path),
            "--output",
            str(output_path),
            "--iters",
            "2",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(extracted)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text())
    assert {node["name"] for node in payload["nodes"]} == {"Login", "SSO"}
    assert all(node["degree"] == 1 for node in payload["nodes"])


_WEBUI = _REPO_ROOT / "src" / "mycelium" / "webui"


def test_browser_app_ships_inside_the_wheel(wheel):
    """`uv run mycelium-http` must serve /ui/ without Node, so the committed
    build output — the app's page, every bundle it references and the
    self-hosted fonts — has to reach the wheel unaltered. A page whose
    script or stylesheet is missing loads blank, with nothing failing
    server-side."""
    with zipfile.ZipFile(wheel) as zf:
        members = set(zf.namelist())
        page = _WEBUI / "ui" / "index.html"
        html = page.read_text(encoding="utf-8")
        assets = re.findall(r'(?:src|href)="/ui/([^"]+)"', html)
        assert any(a.endswith(".js") for a in assets), "the page loads no script"
        fonts = _WEBUI / "ui" / "fonts" / "fonts.css"
        assert "fonts/fonts.css" in assets
        font_files = re.findall(r"url\(\./([^)]+)\)", fonts.read_text(encoding="utf-8"))
        assert font_files, "the font stylesheet loads no fonts"
        for path in [
            page,
            *(_WEBUI / "ui" / a for a in assets),
            *(fonts.parent / f for f in font_files),
        ]:
            member = path.relative_to(_REPO_ROOT / "src").as_posix()
            assert member in members
            assert zf.read(member) == path.read_bytes()
