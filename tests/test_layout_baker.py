"""Tests for `mycelium.layout_baker._bake_argv`.

Pure unit test of the subprocess argv construction shared by the initial
synchronous bake (`ensure_initial`) and the debounced background rebake
(`_fire`). No subprocess is spawned here — just the argv shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mycelium import layout_baker


def test_bake_argv_shape() -> None:
    db_path = Path("/data/mycelium.db")
    output_path = Path("/data/entity-positions.json")

    argv = layout_baker._bake_argv(db_path, output_path)

    assert argv == [
        sys.executable,
        str(layout_baker._SCRIPT),
        "--db",
        str(db_path),
        "--output",
        str(output_path),
    ]


def test_bake_argv_uses_current_interpreter() -> None:
    argv = layout_baker._bake_argv(Path("db"), Path("out"))
    assert argv[0] == sys.executable


def test_bake_argv_flags_precede_their_values() -> None:
    db_path = Path("some/db.sqlite")
    output_path = Path("some/out.json")

    argv = layout_baker._bake_argv(db_path, output_path)

    assert argv[2] == "--db"
    assert argv[3] == str(db_path)
    assert argv[4] == "--output"
    assert argv[5] == str(output_path)
