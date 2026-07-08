"""Tests for the bounded research workspace reader."""

from __future__ import annotations

import pytest

from mycelium.ask.substrate import ToolSpec
from mycelium.research.workspace import WorkspaceError, WorkspaceReader


@pytest.fixture
def workspace_tree(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 'needle'",
                "class Beta:",
                "    needle = 'second'",
                "x = 'tail'",
            ]
        ),
        encoding="utf-8",
    )
    (root / "pkg" / "notes.txt").write_text(
        "\n".join(["short", "needle in notes", "l" * 40, "last"]),
        encoding="utf-8",
    )
    (root / "README.md").write_text("needle in readme\n", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"needle\x00hidden\n")
    (root / "large.txt").write_text("x" * 64, encoding="utf-8")

    outside = tmp_path / "outside.txt"
    outside.write_text("outside needle\n", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)
    return root


def test_list_files_sorted_relative_and_capped(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_files=3)

    result = reader.call("ws_list_files", {"glob": "**/*"})

    assert result == {
        "files": ["README.md", "binary.bin", "large.txt"],
        "total": 3,
        "truncated": True,
    }


def test_list_files_skips_symlink_escaping_root(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    result = reader.call("ws_list_files", {"glob": "**/*"})

    assert "escape.txt" not in result["files"]


def test_grep_matches_with_line_numbers_and_glob_filter(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    result = reader.call("ws_grep", {"pattern": "needle", "glob": "pkg/*.py"})

    assert result == {
        "matches": [
            {"path": "pkg/module.py", "line": 2, "text": "    return 'needle'"},
            {"path": "pkg/module.py", "line": 4, "text": "    needle = 'second'"},
        ],
        "truncated": False,
    }


def test_grep_invalid_regex_raises_workspace_error(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    with pytest.raises(WorkspaceError, match="invalid pattern:"):
        reader.call("ws_grep", {"pattern": "["})


def test_grep_caps_matches_and_skips_binary(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_matches=2)

    result = reader.call("ws_grep", {"pattern": "needle", "glob": "**/*"})

    assert result["matches"] == [
        {"path": "README.md", "line": 1, "text": "needle in readme"},
        {"path": "pkg/module.py", "line": 2, "text": "    return 'needle'"},
    ]
    assert result["truncated"] is True
    assert all(match["path"] != "binary.bin" for match in result["matches"])


def test_read_file_offset_limit_and_line_truncation(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_line_chars=10)

    result = reader.call(
        "ws_read_file", {"path": "pkg/notes.txt", "offset": 1, "limit": 2}
    )

    assert result == {
        "path": "pkg/notes.txt",
        "offset": 1,
        "lines": ["needle in ", "llllllllll"],
        "total_lines": 4,
        "truncated": True,
    }


def test_read_file_limit_clamped_to_max_read_lines(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_read_lines=2)

    result = reader.call("ws_read_file", {"path": "pkg/module.py", "limit": 99})

    assert result["lines"] == ["def alpha():", "    return 'needle'"]
    assert result["truncated"] is True


def test_read_file_rejects_dotdot_absolute_and_empty(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    for path in ("../x", "a/../../x", "/etc/passwd", ""):
        with pytest.raises(WorkspaceError, match="path outside workspace:"):
            reader.call("ws_read_file", {"path": path})


def test_read_file_rejects_symlink_escape(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    with pytest.raises(WorkspaceError, match="path outside workspace: escape.txt"):
        reader.call("ws_read_file", {"path": "escape.txt"})


def test_read_file_refuses_binary_and_oversize(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_file_bytes=10)

    with pytest.raises(WorkspaceError, match="binary file: binary.bin"):
        reader.call("ws_read_file", {"path": "binary.bin"})
    with pytest.raises(WorkspaceError, match="file too large: large.txt"):
        reader.call("ws_read_file", {"path": "large.txt"})


def test_tool_specs_and_dispatch(workspace_tree):
    reader = WorkspaceReader(workspace_tree)

    specs = reader.tool_specs()

    assert {spec.name for spec in specs} == {"ws_list_files", "ws_grep", "ws_read_file"}
    assert all(isinstance(spec, ToolSpec) for spec in specs)
    assert all(isinstance(spec.input_schema, dict) for spec in specs)
    assert reader.has("ws_list_files") is True
    assert reader.has("ws_grep") is True
    assert reader.has("ws_read_file") is True
    assert reader.has("nope") is False
    assert reader.call("ws_read_file", {"path": "README.md"})["lines"] == [
        "needle in readme"
    ]
    with pytest.raises(WorkspaceError, match="unknown workspace tool:"):
        reader.call("nope", {})


def test_results_size_capped(workspace_tree):
    reader = WorkspaceReader(workspace_tree, max_result_chars=20)

    grep_result = reader.call("ws_grep", {"pattern": "needle", "glob": "**/*"})
    read_result = reader.call("ws_read_file", {"path": "pkg/notes.txt"})

    assert grep_result["truncated"] is True
    assert read_result["truncated"] is True
    assert "".join(read_result["lines"]) == "shortneedle in notes"


def test_call_wraps_unexpected_errors_as_workspace_error(tmp_path):
    from mycelium.research.workspace import WorkspaceError, WorkspaceReader

    (tmp_path / "a.txt").write_text("hello\n")
    ws = WorkspaceReader(tmp_path)
    # non-int offset (model-supplied junk) must not escape as ValueError
    with pytest.raises(WorkspaceError):
        ws.call("ws_read_file", {"path": "a.txt", "offset": "NaN"})
    # a glob pathlib itself rejects must not escape either
    with pytest.raises(WorkspaceError):
        ws.call("ws_list_files", {"glob": "/absolute/**"})


def test_git_dir_is_refused_by_read_and_skipped_by_glob(tmp_path):
    """VCS internals are never enumerated or readable (defense in depth for the
    clone-credential path), even if a .git survived into the workspace."""
    from mycelium.research.workspace import WorkspaceError, WorkspaceReader

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("url = https://x-access-token:SECRET@github.com/o/r")
    (tmp_path / "app.py").write_text("print('hi')\n")
    ws = WorkspaceReader(tmp_path)

    listing = ws.call("ws_list_files", {"glob": "**/*"})
    assert not any(".git" in f for f in listing["files"])
    assert "app.py" in listing["files"]

    grep = ws.call("ws_grep", {"pattern": "SECRET"})
    assert grep["matches"] == []  # never reads .git/config

    with pytest.raises(WorkspaceError):
        ws.call("ws_read_file", {"path": ".git/config"})


def test_grep_bounds_regex_input_per_line(tmp_path):
    """A newline-free multi-KB line only feeds a bounded window to the regex."""
    from mycelium.research.workspace import WorkspaceReader

    long_line = "a" * 100_000 + "NEEDLE"
    (tmp_path / "big.txt").write_text(long_line)
    ws = WorkspaceReader(tmp_path, max_search_chars=50, max_file_bytes=10_000_000)
    # NEEDLE is past the 50-char search window → not matched (bounded input)
    assert ws.call("ws_grep", {"pattern": "NEEDLE"})["matches"] == []
    # but a pattern within the window matches
    assert ws.call("ws_grep", {"pattern": "a{10}"})["matches"]


def test_grep_stops_at_scan_byte_budget(tmp_path):
    from mycelium.research.workspace import WorkspaceReader

    for i in range(6):
        (tmp_path / f"f{i}.txt").write_text("x" * 1000 + "\n")
    ws = WorkspaceReader(tmp_path, max_grep_scan_bytes=2500)
    out = ws.call("ws_grep", {"pattern": "zzz"})  # no matches, but scans files
    assert out["truncated"] is True
