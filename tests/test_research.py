"""Tests for the `research` write-harness loop.

The loop is exercised with a fake Anthropic client (scripts the model's
tool-use turns), a fake substrate (canned read results), a fake workspace
(canned file reads), and a fake draft emitter — no server, no DB, no network,
no git. Mirrors tests/test_ingest.py; workspace/sources/store units live in
their own test modules.

The keystone invariant — there is provably no live-write path — is exercised
structurally: the model is only ever handed read tools + emit_draft, and the
only thing that creates a draft is the injected emitter.
"""

from __future__ import annotations

import json
import types

from mycelium.ask.substrate import SubstrateError, ToolSpec
from mycelium.ingest.tools import EMIT_TOOL
from mycelium.research import NothingFound, ResearchConfig, ResearchDraftCreated
from mycelium.research.loop import run_research
from mycelium.research.sources import Source, SourceError
from mycelium.research.workspace import WorkspaceError

# --------------------------------------------------------------------------- #
# Fakes (mirror test_ingest.py)
# --------------------------------------------------------------------------- #


def _usage(i: int = 10, o: int = 5):
    return types.SimpleNamespace(
        input_tokens=i,
        output_tokens=o,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _text(t: str):
    return types.SimpleNamespace(type="text", text=t)


def _tool_use(name: str, inp: dict, id: str = "tu"):
    return types.SimpleNamespace(type="tool_use", id=id, name=name, input=inp)


def _message(blocks, stop="tool_use"):
    return types.SimpleNamespace(content=list(blocks), stop_reason=stop, usage=_usage())


class FakeAnthropic:
    """Scripts a sequence of model responses; records each request's kwargs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def with_options(self, **_kw):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._responses.pop(0)


_MIN_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}

_READ_NAMES = (
    "list_statement_kinds",
    "list_link_types",
    "list_entity_link_types",
    "search_statements",
    "survey_statements",
    "grep_statements",
    "discover_facts",
    "find_duplicates",
    "get_statements",
)

_WS_NAMES = ("ws_list_files", "ws_grep", "ws_read_file")


class FakeSubstrate:
    """Canned read-primitive results; records calls."""

    def __init__(self, results: dict | None = None):
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self._specs = [ToolSpec(n, n, _MIN_SCHEMA) for n in _READ_NAMES]

    def tool_specs(self):
        return list(self._specs)

    def has(self, name):
        return name in {s.name for s in self._specs}

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        value = self._results.get(name, [])
        if isinstance(value, Exception):
            raise SubstrateError(str(value))
        if callable(value):
            return value(arguments)
        return value


class FakeWorkspace:
    """Canned workspace-read results; records calls. Mirrors WorkspaceReader's
    tool_specs()/has()/call() shape without touching a filesystem."""

    def __init__(self, results: dict | None = None):
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self._specs = [ToolSpec(n, n, _MIN_SCHEMA) for n in _WS_NAMES]

    def tool_specs(self):
        return list(self._specs)

    def has(self, name):
        return name in _WS_NAMES

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        value = self._results.get(name, {"ok": True})
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(arguments)
        return value


class FakeEmitter:
    """Records the created draft + queued ops in memory."""

    def __init__(self, valid_kinds: set[str] | None = None):
        self._valid = valid_kinds if valid_kinds is not None else set(_DEFAULT_KINDS)
        self.created: list[str | None] = []
        self.queued: list[tuple[str, str, dict]] = []
        self._n = 0

    def valid_kinds(self) -> set[str]:
        return set(self._valid)

    def allowed_keys(self, kind: str) -> set[str]:
        from mycelium import server

        sigs = getattr(server, "_ORIG_SIGNATURES", None)
        if not sigs or kind not in sigs:
            return set()
        return set(sigs[kind].parameters)

    def create(self, *, title: str | None = None) -> str:
        self._n += 1
        self.created.append(title)
        return f"drf_{self._n}"

    def add_op(self, draft_id: str, kind: str, payload: dict) -> int:
        clean = {k: v for k, v in payload.items() if v is not None}
        self.queued.append((draft_id, kind, clean))
        return len(self.queued)


_DEFAULT_KINDS = {
    "upsert_statement",
    "upsert_statements",
    "upsert_entity",
    "add_links",
    "add_entity_links",
    "patch_statement",
    "replace_text",
    "merge_statements",
}


# --------------------------------------------------------------------------- #
# emit_draft input builders + scripted turn sequences
# --------------------------------------------------------------------------- #


def _op(
    op: str, payload: dict, rationale: str = "per src/app.py", targets=None
) -> dict:
    return {
        "op": op,
        "payload_json": json.dumps(payload),
        "rationale": rationale,
        "targets_existing": list(targets or []),
    }


def _ledger_row(
    candidate, classification, matched=None, considered=None, note=""
) -> dict:
    return {
        "candidate": candidate,
        "classification": classification,
        "matched_against": list(matched or []),
        "link_candidates_considered": list(considered or []),
        "note": note,
    }


def _emit_input(ops=None, ledger=None, flagged=None, skipped=None) -> dict:
    return {
        "ops": list(ops or []),
        "ledger": list(ledger or []),
        "flagged": list(flagged or []),
        "skipped_duplicates": list(skipped or []),
    }


def _good_new_op_emit():
    return _emit_input(
        ops=[
            _op(
                "upsert_statement",
                {"kind": "event", "text": "an invite is submitted", "links": []},
                targets=["stm_99"],
            )
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_99"],
                considered=["stm_99"],
                note="links to invite flow",
            )
        ],
    )


def _explore_turns():
    """Three workspace reads (incl. a file read) — the exploration floor."""
    return [
        _message([_tool_use("ws_list_files", {"glob": "**/*.py"})]),
        _message([_tool_use("ws_grep", {"pattern": "invite"})]),
        _message([_tool_use("ws_read_file", {"path": "src/app.py"})]),
    ]


def _reconcile_turns():
    """Reconcile + non-first adjacency — ingest's substrate floor."""
    return [
        _message([_tool_use("discover_facts", {"texts": ["an invite is submitted"]})]),
        _message([_tool_use("search_statements", {"query": "invite"})]),
    ]


def _full_run_turns(emit_input=None):
    return [
        *_explore_turns(),
        *_reconcile_turns(),
        _message([_tool_use(EMIT_TOOL, emit_input or _good_new_op_emit())]),
    ]


def _run(responses, results=None, ws_results=None, emitter=None, **config_over):
    client = FakeAnthropic(responses)
    substrate = FakeSubstrate(results)
    workspace = FakeWorkspace(ws_results)
    emitter = emitter or FakeEmitter()
    cfg = ResearchConfig(thinking=True, trace_log_path=None, **config_over)
    result = run_research(
        "how invites work",
        Source(name="acme", owner="acme", repo="api"),
        client=client,
        substrate=substrate,
        workspace=workspace,
        emitter=emitter,
        config=cfg,
    )
    return result, client, substrate, workspace, emitter


# --------------------------------------------------------------------------- #
# Tool surface
# --------------------------------------------------------------------------- #


def test_tool_list_is_workspace_plus_substrate_reads_plus_emit_only():
    result, client, *_ = _run(_full_run_turns())
    names = [t["name"] for t in client.calls[0]["tools"]]
    assert set(_WS_NAMES) <= set(names)
    assert set(_READ_NAMES) <= set(names)
    assert names.count(EMIT_TOOL) == 1
    # nothing else — no write tool ever offered
    assert set(names) == set(_WS_NAMES) | set(_READ_NAMES) | {EMIT_TOOL}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_happy_path_explore_reconcile_emit_creates_draft():
    result, client, substrate, workspace, emitter = _run(_full_run_turns())
    assert isinstance(result, ResearchDraftCreated)
    assert result.draft_id == "drf_1"
    assert result.source == "acme"
    assert result.topic == "how invites work"
    assert [k for _, k, _ in emitter.queued] == ["upsert_statement"]
    # exploration actually happened against the workspace fake
    assert [n for n, _ in workspace.calls] == list(_WS_NAMES)
    # trace carries research-specific fields
    assert result.trace["source"] == "acme"
    assert result.trace["files_read"] == ["src/app.py"]
    assert result.trace["floor"]["explored"] is True
    assert result.trace["floor"]["reconciled"] is True
    assert result.trace["outcome"] == "draft_created"


def test_draft_title_names_source_and_topic():
    result, *_, emitter = _run(_full_run_turns())
    assert emitter.created == ["research: acme: how invites work"]


# --------------------------------------------------------------------------- #
# The research floor
# --------------------------------------------------------------------------- #


def test_floor_blocks_emit_without_file_read():
    """List+grep alone is not exploration: the premature emit is blocked, the
    model then reads a file and reconciles, and the retry emit lands."""
    responses = [
        _message([_tool_use("ws_list_files", {"glob": "**/*"})]),
        _message([_tool_use("ws_grep", {"pattern": "invite"})]),
        *_reconcile_turns(),
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit(), id="early")]),  # blocked
        _message([_tool_use("ws_read_file", {"path": "src/app.py"})]),
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())]),
    ]
    result, client, *_ = _run(responses)
    assert isinstance(result, ResearchDraftCreated)
    # the block came back as an error tool_result mentioning the floor
    blocked = [
        b
        for call in client.calls
        for m in call["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict)
        and b.get("type") == "tool_result"
        and b.get("tool_use_id") == "early"
        and b.get("is_error")
    ]
    assert blocked and "floor" in blocked[0]["content"].lower()
    assert result.trace["degraded"] is False


def test_floor_blocks_emit_without_substrate_reconcile():
    """Exploring without reconciling is blocked; a stubborn model degrades via
    forced finalize instead of landing a floorless emit."""
    premature = _message([_tool_use(EMIT_TOOL, _good_new_op_emit())])
    responses = [
        *_explore_turns(),
        premature,
        premature,
        premature,
        premature,  # 3 blocks + the stuck one
        _message([_text("cannot")], stop="end_turn"),  # forced turn: no emit
    ]
    result, *_ = _run(responses)
    assert isinstance(result, NothingFound)
    assert result.trace["forced_finalize"] == "floor_stuck"
    assert result.trace["degraded"] is True


# --------------------------------------------------------------------------- #
# Ceilings — degrade gracefully, never raise
# --------------------------------------------------------------------------- #


def test_op_cap_forces_finalize_with_emit():
    """op_cap=3 is consumed by the vocab fetch alone; the very first model turn
    is the forced emit (tool_choice forced, thinking stripped)."""
    responses = [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    result, client, *_ = _run(responses, op_cap=3)
    assert isinstance(result, ResearchDraftCreated)
    assert result.trace["forced_finalize"] == "op_cap"
    assert result.trace["degraded"] is True
    forced = client.calls[0]
    assert forced["tool_choice"] == {
        "type": "tool",
        "name": EMIT_TOOL,
        "disable_parallel_tool_use": True,
    }
    assert "thinking" not in forced


def test_op_cap_with_unresponsive_model_returns_nothing_found():
    responses = [_message([_text("hmm")], stop="end_turn")]
    result, *_ = _run(responses, op_cap=3)
    assert isinstance(result, NothingFound)
    assert result.trace["degraded"] is True
    assert result.source == "acme"


def test_wall_clock_forces_finalize():
    responses = [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    result, *_ = _run(responses, wall_clock_s=0.0)
    assert isinstance(result, ResearchDraftCreated)
    assert result.trace["forced_finalize"] == "wall_clock"


def test_api_error_degrades_never_raises():
    class ExplodingClient(FakeAnthropic):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("api down")
            return _message([_text("still down")], stop="end_turn")

    client = ExplodingClient([])
    result = run_research(
        "topic",
        Source(name="s", owner="o", repo="r"),
        client=client,
        substrate=FakeSubstrate(),
        workspace=FakeWorkspace(),
        emitter=FakeEmitter(),
        config=ResearchConfig(),
    )
    assert isinstance(result, NothingFound)
    assert result.trace["forced_finalize"] == "api_error"


def test_malformed_emit_retried_once_then_degrades():
    bad = {"ops": "not-a-list"}
    responses = [
        _message([_tool_use(EMIT_TOOL, bad)]),
        _message([_tool_use(EMIT_TOOL, bad)]),
    ]
    result, *_ = _run(responses)
    assert isinstance(result, NothingFound)
    assert "malformed twice" in result.reason


# --------------------------------------------------------------------------- #
# Read dispatch
# --------------------------------------------------------------------------- #


def test_workspace_error_is_error_tool_result_not_raised():
    """A failing workspace read (e.g. a path escape) comes back to the model as
    an error tool_result; the run continues and terminates normally."""
    responses = [
        _message([_tool_use("ws_read_file", {"path": "../etc/passwd"}, id="esc")]),
        _message([_text("blocked, giving up")], stop="end_turn"),
        _message([_text("still nothing")], stop="end_turn"),  # after nudge
        _message([_text("forced: nothing")], stop="end_turn"),  # forced turn
    ]
    client = FakeAnthropic(responses)
    ws = FakeWorkspace({"ws_read_file": WorkspaceError("path outside workspace")})
    result = run_research(
        "t",
        Source(name="s", owner="o", repo="r"),
        client=client,
        substrate=FakeSubstrate(),
        workspace=ws,
        emitter=FakeEmitter(),
        config=ResearchConfig(),
    )
    errs = [
        b
        for call in client.calls
        for m in call["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict)
        and b.get("type") == "tool_result"
        and b.get("tool_use_id") == "esc"
    ]
    assert errs and errs[0]["is_error"]
    assert "path outside workspace" in str(errs[0]["content"])
    assert isinstance(result, NothingFound)


def test_substrate_error_is_reported_not_fabricated():
    results = {"discover_facts": SubstrateError("substrate down")}
    responses = [
        *_explore_turns(),
        _message([_tool_use("discover_facts", {"texts": ["x"]}, id="df")]),
        _message([_tool_use("find_duplicates", {"query": "x"})]),
        _message([_tool_use("search_statements", {"query": "x"})]),
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())]),
    ]
    result, client, *_ = _run(responses, results=results)
    assert isinstance(result, ResearchDraftCreated)
    errs = [
        b
        for call in client.calls
        for m in call["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict)
        and b.get("type") == "tool_result"
        and b.get("tool_use_id") == "df"
    ]
    assert errs and errs[0]["is_error"]


# --------------------------------------------------------------------------- #
# Ops: corrections + validation (via ingest's imported machinery)
# --------------------------------------------------------------------------- #


def test_correction_op_patch_statement_validated_and_queued():
    emit = _emit_input(
        ops=[
            _op(
                "patch_statement",
                {
                    "id": "stm_7",
                    "text": "an invite is rejected when its signature is invalid",
                },
                rationale="old -> new per src/webhooks.py",
                targets=["stm_7"],
            )
        ],
        ledger=[
            _ledger_row(
                "an invite is rejected when its signature is invalid",
                "refinement",
                matched=["stm_7"],
                considered=["stm_7"],
            )
        ],
    )
    result, *_, emitter = _run(_full_run_turns(emit))
    assert isinstance(result, ResearchDraftCreated)
    assert [k for _, k, _ in emitter.queued] == ["patch_statement"]


def test_invalid_op_kind_flagged_not_queued():
    emit = _emit_input(
        ops=[
            _op("drop_table", {"id": "x"}),
            _op(
                "upsert_statement",
                {"kind": "event", "text": "an invite is submitted", "links": []},
            ),
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted", "new", matched=["stm_1"], considered=["stm_1"]
            )
        ],
    )
    result, *_, emitter = _run(_full_run_turns(emit))
    assert isinstance(result, ResearchDraftCreated)
    assert [k for _, k, _ in emitter.queued] == ["upsert_statement"]
    assert any("drop_table" in f for f in result.flagged)


def test_all_duplicates_returns_nothing_found():
    emit = _emit_input(
        ledger=[_ledger_row("an invite is submitted", "duplicate", matched=["stm_1"])],
        skipped=["an invite is submitted :: stm_1"],
    )
    result, *_ = _run(_full_run_turns(emit))
    assert isinstance(result, NothingFound)
    assert "duplicates" in result.reason


# --------------------------------------------------------------------------- #
# Sources at the run_research seam
# --------------------------------------------------------------------------- #


def test_unknown_source_name_returns_nothing_found(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SOURCES", raising=False)
    result = run_research(
        "topic",
        "nope",
        client=FakeAnthropic([]),
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=ResearchConfig(),
    )
    assert isinstance(result, NothingFound)
    assert "source error" in result.reason


def test_source_fetch_failure_returns_nothing_found(monkeypatch):
    from contextlib import contextmanager

    from mycelium.research import loop as rloop

    @contextmanager
    def boom(source, env=None):
        raise SourceError("clone failed: ***")
        yield  # pragma: no cover

    monkeypatch.setattr(rloop.sources, "fetch", boom)
    client = FakeAnthropic([])
    result = run_research(
        "topic",
        Source(name="s", owner="o", repo="r"),
        client=client,
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=ResearchConfig(),
    )
    assert isinstance(result, NothingFound)
    assert "source fetch failed" in result.reason
    assert client.calls == []  # never reached the model


def test_no_source_and_no_workspace_returns_nothing_found():
    result = run_research(
        "topic",
        client=FakeAnthropic([]),
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=ResearchConfig(),
    )
    assert isinstance(result, NothingFound)
    assert "no source" in result.reason


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_config_from_env_reads_research_vars(monkeypatch):
    monkeypatch.setenv("MYCELIUM_RESEARCH_MODEL", "claude-test-1")
    monkeypatch.setenv("MYCELIUM_RESEARCH_OP_CAP", "42")
    monkeypatch.setenv("MYCELIUM_RESEARCH_WALL_CLOCK_S", "99.5")
    cfg = ResearchConfig.from_env()
    assert cfg.model == "claude-test-1"
    assert cfg.op_cap == 42
    assert cfg.wall_clock_s == 99.5


def test_config_model_falls_back_to_ingest_default(monkeypatch):
    from mycelium.ingest.config import DEFAULT_MODEL

    monkeypatch.delenv("MYCELIUM_RESEARCH_MODEL", raising=False)
    monkeypatch.delenv("MYCELIUM_INGEST_MODEL", raising=False)
    assert ResearchConfig.from_env().model == DEFAULT_MODEL
    monkeypatch.setenv("MYCELIUM_INGEST_MODEL", "claude-ingest-x")
    assert ResearchConfig.from_env().model == "claude-ingest-x"


# --------------------------------------------------------------------------- #
# Structural no-live-write
# --------------------------------------------------------------------------- #


def test_loop_module_imports_no_write_tool():
    """Structural: the research loop references the read seams + ingest's draft
    emitter, and no live substrate-write call. The only write path is
    drafts_store via the emitter, in ingest/draft.py."""
    import inspect

    from mycelium.research import loop

    src = inspect.getsource(loop)
    assert "from ..ask.substrate import" in src  # substrate read seam
    assert "from ..ingest.draft import" in src  # the (only) write path
    assert "store.upsert_statement" not in src
    assert "submit_draft" not in src
    assert "apply_draft" not in src
    assert "from .. import store" not in src
    assert "import store" not in src


def test_research_package_never_touches_server_conn():
    import ast
    import inspect

    from mycelium.research import loop, workspace

    for mod in (loop, workspace):
        tree = ast.parse(inspect.getsource(mod))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "_conn" not in attrs
        assert "_drafts_conn" not in attrs  # even the drafts conn only via emitter


def test_real_server_inner_tool_set_excludes_writes():
    """Wiring the REAL server InProcessSubstrate: the tool set offered to the
    research model is read primitives only."""
    from mycelium import server
    from mycelium.ask.substrate import InProcessSubstrate
    from mycelium.ingest.tools import build_tools

    sub = InProcessSubstrate(server)
    ws = FakeWorkspace()
    names = {t["name"] for t in build_tools([*ws.tool_specs(), *sub.tool_specs()])}
    assert "upsert_statement" not in names
    assert "add_links" not in names
    assert "start_research" not in names
    assert EMIT_TOOL in names
