"""The prompt sources that a deployment receives from the built wheel.

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
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from mycelium import guidelines
from mycelium.docgen.config import DocgenConfig
from mycelium.ingest.config import IngestConfig
from mycelium.research.config import ResearchConfig

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


def test_guideline_rows_are_readable_from_the_wheel(wheel, tmp_path):
    """A fresh deployment must read every seeded guideline through the paths
    computed by the code in its wheel; a missing, misplaced, or altered source
    would otherwise leave its prompt store incomplete on first startup."""
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(extracted)

    script = f"""
import json
import sys

sys.path.insert(0, {str(extracted)!r})
import mycelium
import mycelium.guidelines as g

print(json.dumps({{"file": mycelium.__file__, "rows": g.read_rows()}}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    # The child's traceback is the whole diagnosis when this fires — it names
    # the source the wheel is missing. Swallowing it behind a CalledProcessError
    # would leave the one test that catches a silent packaging regression
    # reporting only "exit status 1".
    assert result.returncode == 0, (
        f"the wheel's own guideline reader failed:\n{result.stderr}"
    )
    payload = json.loads(result.stdout)

    assert payload["file"].startswith(str(extracted))
    expected = {
        guidelines.row_name(slot): path.read_text(encoding="utf-8")
        for slot, path in guidelines.SOURCES.items()
    }
    assert set(payload["rows"]) == set(expected)
    for name, text in expected.items():
        assert payload["rows"][name] == text


def test_doctrines_ship_inside_the_wheel(wheel):
    """Each service's startup doctrine must be present and unaltered in the
    wheel, or a deployment with an empty data volume would lose that service's
    baseline prompt even though source-tree tests continued to pass."""
    doctrine_paths = [
        DocgenConfig().doctrine_path,
        IngestConfig().doctrine_path,
        ResearchConfig().doctrine_path,
    ]

    with zipfile.ZipFile(wheel) as zf:
        members = set(zf.namelist())
        for source in doctrine_paths:
            path = Path(source)
            member = path.resolve().relative_to(_REPO_ROOT / "src").as_posix()
            assert member in members
            assert zf.read(member).decode("utf-8") == path.read_text(encoding="utf-8")
