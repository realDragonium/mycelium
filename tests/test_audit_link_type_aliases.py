"""Test the automatic-alias audit's filtering, ordering, and summary."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

from mycelium import store

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_link_type_aliases.py"


def _audit_script():
    """Load the audit script by path because scripts is not a package."""
    spec = importlib.util.spec_from_file_location("audit_link_type_aliases", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read an audit CSV into dictionaries."""
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_audit_filters_and_orders_aliases(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = store.connect(data_dir / "mycelium.db")
    store.migrate(conn)
    with store.transaction(conn):
        store.upsert_link_type_alias(
            conn,
            "audit",
            "automatic high",
            provenance="auto",
            score=0.8,
        )
        store.upsert_link_type_alias(
            conn,
            "audit",
            "automatic low",
            provenance="auto",
            score=0.2,
        )
        store.upsert_link_type_alias(
            conn,
            "audit",
            "needs review",
            provenance="auto:low-confidence",
            score=0.9,
        )
        store.upsert_link_type_alias(
            conn,
            "audit",
            "curated phrase",
            provenance="curator",
        )
        store.upsert_link_type_alias(
            conn,
            "audit",
            "seeded phrase",
            provenance="seed",
        )
    total = len(store.list_link_type_aliases(conn))
    conn.close()
    script = _audit_script()

    automatic_path = tmp_path / "reports" / "automatic.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--out",
            str(automatic_path),
        ],
    )
    assert script.main() == 0

    automatic = _read_csv(automatic_path)
    assert list(automatic[0]) == [
        "link_type",
        "alias",
        "provenance",
        "score",
        "created_at",
        "created_by",
    ]
    assert [row["alias"] for row in automatic] == [
        "needs review",
        "automatic low",
        "automatic high",
    ]
    assert [row["provenance"] for row in automatic] == [
        "auto:low-confidence",
        "auto",
        "auto",
    ]
    stdout = capsys.readouterr().out
    assert f"Scanned {total} aliases; 3 automatic (1 low-confidence)" in stdout
    assert f"Report: {automatic_path}" in stdout

    all_path = tmp_path / "all.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--out",
            str(all_path),
            "--all",
        ],
    )
    assert script.main() == 0

    all_rows = _read_csv(all_path)
    assert len(all_rows) == total
    assert [row["alias"] for row in all_rows[:3]] == [
        "needs review",
        "automatic low",
        "automatic high",
    ]
    assert all(row["score"] == "" for row in all_rows[3:])
    assert {row["provenance"] for row in all_rows} >= {"curator", "seed"}
    stdout = capsys.readouterr().out
    assert f"Scanned {total} aliases; 3 automatic (1 low-confidence)" in stdout
