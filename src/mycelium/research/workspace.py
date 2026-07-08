"""A bounded, escape-proof read seam over a checked-out codebase directory. The inner model of a research run gets these as tools; repo content is untrusted, so path escapes must be impossible and every result size-capped."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from ..ask.substrate import ToolSpec


class WorkspaceError(RuntimeError):
    """Raised for any refused workspace read (bad path, binary, bad pattern).
    The loop renders it as an error tool_result; it never aborts the run."""


class WorkspaceReader:
    def __init__(
        self,
        root: Path | str,
        *,
        max_files: int = 500,
        max_matches: int = 200,
        max_line_chars: int = 500,
        default_read_lines: int = 200,
        max_read_lines: int = 500,
        max_file_bytes: int = 2_000_000,
        max_result_chars: int = 20_000,
    ) -> None:
        self._root = Path(root).resolve(strict=True)
        self._max_files = max_files
        self._max_matches = max_matches
        self._max_line_chars = max_line_chars
        self._default_read_lines = default_read_lines
        self._max_read_lines = max_read_lines
        self._max_file_bytes = max_file_bytes
        self._max_result_chars = max_result_chars
        self._specs = [
            ToolSpec(
                name="ws_list_files",
                description=(
                    "List files under the workspace using a workspace-relative glob. "
                    "Results are bounded, sorted, and returned as workspace-relative paths."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "glob": {"type": "string", "default": "**/*"},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="ws_grep",
                description=(
                    "Search workspace files with a Python regular expression. "
                    "Results are bounded and paths are workspace-relative."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "glob": {"type": ["string", "null"], "default": None},
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="ws_read_file",
                description=(
                    "Read a workspace-relative text file by 0-based line offset. "
                    "Results are bounded and paths are workspace-relative."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "default": 0, "minimum": 0},
                        "limit": {"type": ["integer", "null"], "default": None},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ]
        self._tools = {spec.name for spec in self._specs}

    def tool_specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        # The model supplies the arguments, so any failure here — a malformed
        # glob pathlib rejects, a non-int offset, a file racing away mid-read —
        # must surface as a WorkspaceError (an error tool_result), never abort
        # the run.
        try:
            if name == "ws_list_files":
                return self._list_files(arguments)
            if name == "ws_grep":
                return self._grep(arguments)
            if name == "ws_read_file":
                return self._read_file(arguments)
        except WorkspaceError:
            raise
        except Exception as exc:  # noqa: BLE001 — untrusted input at this seam
            raise WorkspaceError(f"workspace read failed: {exc}") from exc
        raise WorkspaceError(f"unknown workspace tool: {name}")

    def _list_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pattern = arguments.get("glob", "**/*")
        files: list[str] = []
        truncated = False

        for candidate in self._iter_glob(pattern):  # already sorted
            if len(files) >= self._max_files:
                truncated = True
                break
            files.append(candidate)

        return {"files": files, "total": len(files), "truncated": truncated}

    def _grep(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pattern = arguments.get("pattern")
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"invalid pattern: {exc}") from exc

        glob = arguments.get("glob") or "**/*"
        matches: list[dict[str, Any]] = []
        truncated = False
        size = 0  # running serialized size — O(1) per match, not a re-dump

        for rel in self._iter_glob(glob):
            path = self._root / rel
            if self._skip_search_file(path):
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if regex.search(line):
                        text = line.rstrip("\r\n")[: self._max_line_chars]
                        match = {"path": rel, "line": line_number, "text": text}
                        matches.append(match)
                        size += len(json.dumps(match, ensure_ascii=False))
                        if (
                            len(matches) >= self._max_matches
                            or size > self._max_result_chars
                        ):
                            truncated = True
                            return {"matches": matches, "truncated": truncated}

        return {"matches": matches, "truncated": truncated}

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rel = arguments.get("path")
        path = self._resolve(rel)
        if not path.is_file():
            raise WorkspaceError(f"file not found: {rel}")
        if self._is_binary(path):
            raise WorkspaceError(f"binary file: {rel}")
        if path.stat().st_size > self._max_file_bytes:
            raise WorkspaceError(f"file too large: {rel}")

        offset = max(0, int(arguments.get("offset", 0)))
        limit_arg = arguments.get("limit")
        limit = self._default_read_lines if limit_arg is None else int(limit_arg)
        limit = max(0, min(limit, self._max_read_lines))

        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(raw_lines)
        requested = raw_lines[offset : offset + limit]
        lines = [line[: self._max_line_chars] for line in requested]
        truncated = (
            offset + limit < total_lines
            or any(len(line) > self._max_line_chars for line in requested)
        )
        lines, size_truncated = self._cap_lines(lines)
        truncated = truncated or size_truncated

        return {
            "path": rel,
            "offset": offset,
            "lines": lines,
            "total_lines": total_lines,
            "truncated": truncated,
        }

    def _resolve(self, rel: str) -> Path:
        if not rel:
            raise WorkspaceError(f"path outside workspace: {rel}")
        posix = PurePosixPath(rel)
        if (
            posix.is_absolute()
            or rel.startswith("\\")
            or re.match(r"^[A-Za-z]:[/\\]", rel)
            or ".." in posix.parts
        ):
            raise WorkspaceError(f"path outside workspace: {rel}")

        path = (self._root / rel).resolve()
        if not path.is_relative_to(self._root):
            raise WorkspaceError(f"path outside workspace: {rel}")
        if not path.exists():
            raise WorkspaceError(f"file not found: {rel}")
        return path

    #: Hard cap on glob candidates examined per call, so one `**/*` over a
    #: huge checkout bounds work and memory, not just the returned rows.
    _MAX_GLOB_SCAN = 50_000

    def _iter_glob(self, pattern: str) -> list[str]:
        rels: list[str] = []
        scanned = 0
        for candidate in self._root.glob(pattern):
            scanned += 1
            if scanned > self._MAX_GLOB_SCAN:
                break
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(self._root) or not resolved.is_file():
                continue
            try:
                rels.append(candidate.relative_to(self._root).as_posix())
            except ValueError:
                continue
        return sorted(rels)

    def _skip_search_file(self, path: Path) -> bool:
        try:
            return path.stat().st_size > self._max_file_bytes or self._is_binary(path)
        except OSError:
            return True

    def _is_binary(self, p: Path) -> bool:
        with p.open("rb") as fh:
            return b"\x00" in fh.read(8192)

    def _cap_lines(self, lines: list[str]) -> tuple[list[str], bool]:
        capped: list[str] = []
        size = 0
        for line in lines:
            if size + len(line) > self._max_result_chars:
                remaining = self._max_result_chars - size
                if remaining > 0:
                    capped.append(line[:remaining])
                return capped, True
            capped.append(line)
            size += len(line)
        return capped, False

    def _serialized_size(self, matches: list[dict[str, Any]]) -> int:
        return len(json.dumps(matches, ensure_ascii=False))
