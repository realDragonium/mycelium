from __future__ import annotations

import os
from pathlib import Path

import pyinstrument
import pytest

from mycelium import tracing


def _trace_file(directory: Path, name: str, mtime: float) -> Path:
    path = directory / name
    path.write_text("trace")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_keeps_newest_traces_pairing_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", "2")
    _trace_file(tmp_path, "old.html", 1)
    _trace_file(tmp_path, "old.meta.json", 2)
    _trace_file(tmp_path, "latest.html", 3)
    _trace_file(tmp_path, "latest.meta.json", 5)
    _trace_file(tmp_path, "export.json", 4)
    (tmp_path / "nested").mkdir()

    tracing.prune_traces(tmp_path)

    assert {p.name for p in tmp_path.iterdir()} == {
        "latest.html",
        "latest.meta.json",
        "export.json",
        "nested",
    }

    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", "1")
    tracing.prune_traces(tmp_path)
    assert not (tmp_path / "export.json").exists()


@pytest.mark.parametrize("keep", ["0", "invalid", "-1"])
def test_prune_disabled_or_invalid_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep: str
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", keep)
    path = _trace_file(tmp_path, "ask.html", 1)
    tracing.prune_traces(tmp_path)
    assert path.exists()


def test_prune_continues_after_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", "1")
    blocked = _trace_file(tmp_path, "old.html", 1)
    _trace_file(tmp_path, "old.meta.json", 1)
    _trace_file(tmp_path, "new.html", 2)
    unlink = Path.unlink

    def sometimes_fail(self: Path, missing_ok: bool = False) -> None:
        if self == blocked:
            raise OSError("file unavailable")
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", sometimes_fail)
    tracing.prune_traces(tmp_path)
    assert blocked.exists()
    assert not (tmp_path / "old.meta.json").exists()
    assert (tmp_path / "new.html").exists()


def test_prune_unreadable_directory_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", "1")

    def fail_list(self: Path) -> None:
        raise OSError("directory unavailable")

    monkeypatch.setattr(Path, "iterdir", fail_list)
    tracing.prune_traces(tmp_path)


def test_profile_write_prunes_the_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_TRACE_KEEP", "1")
    monkeypatch.setattr(tracing, "_enabled", True)
    monkeypatch.setattr(tracing, "_enabled_until", None)
    _trace_file(tmp_path, "old.html", 1)
    _trace_file(tmp_path, "old.meta.json", 1)

    class FakeProfiler:
        def __init__(self, *, interval: float, async_mode: str) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def output_html(self) -> str:
            return "<html>Login trace</html>"

    monkeypatch.setattr(pyinstrument, "Profiler", FakeProfiler)
    with tracing.profile_to_html("ask", "How do I sign in?"):
        pass

    files = list(tmp_path.iterdir())
    assert len(files) == 2
    assert not (tmp_path / "old.html").exists()
    html = next(tmp_path.glob("*.html"))
    assert html.read_text() == "<html>Login trace</html>"
    assert html.with_suffix(tracing.META_SUFFIX).exists()
