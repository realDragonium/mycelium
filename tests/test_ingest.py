"""Tests for the `ingest` write-harness loop.

The loop is exercised with a fake Anthropic client (scripts the model's
tool-use turns), a fake substrate (canned read results), and a fake draft
emitter (records queued ops in memory) — no server, no DB, no network, no real
API. Each test maps to a harness invariant.

The keystone invariant — there is provably no live-write path — is exercised
structurally: the model is only ever handed read tools + emit_draft, and the
only thing that creates a draft is the injected emitter.
"""

from __future__ import annotations

import json
import types

from mycelium.ask.substrate import SubstrateError, ToolSpec
from mycelium.ingest import (
    DraftCreated,
    IngestConfig,
    NothingToIngest,
    run_ingest,
)
from mycelium.ingest.tools import EMIT_TOOL, build_tools, parse_emit_input

# --------------------------------------------------------------------------- #
# Fakes
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
        self.messages = self  # so `client.messages.create(...)` lands here

    def with_options(self, **_kw):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._responses.pop(0)


_MIN_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}

#: The read surface the loop expects: vocab tools + reconcile/adjacency reads.
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


class FakeEmitter:
    """Records the created draft + queued ops in memory. Mirrors
    InProcessDraftEmitter's contract without a DB."""

    def __init__(self, valid_kinds: set[str] | None = None):
        self._valid = valid_kinds if valid_kinds is not None else set(_DEFAULT_KINDS)
        self.created: list[str | None] = []
        self.queued: list[tuple[str, str, dict]] = []  # (draft_id, kind, payload)
        self._n = 0

    def valid_kinds(self) -> set[str]:
        return set(self._valid)

    def allowed_keys(self, kind: str) -> set[str]:
        # Pull the REAL accepted-kwarg set from server._ORIG_SIGNATURES (the
        # tool's pre-draft-splice signature, draft_id already excluded), with
        # the same empty-set fallback as InProcessDraftEmitter — so the
        # unexpected-key filter is genuinely exercised against real signatures.
        from mycelium import server

        sigs = getattr(server, "_ORIG_SIGNATURES", None)
        if not sigs or kind not in sigs:
            return set()
        return set(sigs[kind].parameters)

    def create(self, *, title: str | None = None) -> str:
        self._n += 1
        draft_id = f"drf_{self._n}"
        self.created.append(title)
        return draft_id

    def add_op(self, draft_id: str, kind: str, payload: dict) -> int:
        # mirror InProcessDraftEmitter: drop None-valued keys at queue time
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
    "search_statements",  # also a registered tool name
}


# --------------------------------------------------------------------------- #
# emit_draft input builders
# --------------------------------------------------------------------------- #


def _op(op: str, payload: dict, rationale: str = "because", targets=None) -> dict:
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
    """A well-formed emit: one NEW upsert_statement with a complete ledger."""
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


def _reconcile_then_adjacency():
    """Two read turns that satisfy the floor (reconcile + adjacency)."""
    return [
        _message([_tool_use("discover_facts", {"texts": ["an invite is submitted"]})]),
        _message([_tool_use("search_statements", {"query": "invite"})]),
    ]


def _run(responses, results=None, emitter=None, **config_over):
    client = FakeAnthropic(responses)
    substrate = FakeSubstrate(results)
    emitter = emitter or FakeEmitter()
    cfg = IngestConfig(thinking=True, trace_log_path=None, **config_over)
    result = run_ingest(
        "An invite is submitted.",
        client=client,
        substrate=substrate,
        emitter=emitter,
        config=cfg,
    )
    return result, client, substrate, emitter


# --------------------------------------------------------------------------- #
# Tools / schema
# --------------------------------------------------------------------------- #


def test_build_tools_exposes_reads_plus_emit_only_no_write_tool():
    """The inner model's tool set = discovered reads + emit_draft, never a write."""
    specs = [ToolSpec(n, n, _MIN_SCHEMA) for n in _READ_NAMES]
    tools = build_tools(specs)
    names = {t["name"] for t in tools}
    assert EMIT_TOOL in names
    assert {"discover_facts", "search_statements"} <= names
    # no substrate write tool ever appears
    for w in (
        "upsert_statement",
        "add_links",
        "patch_statement",
        "merge_statements",
        "submit_draft",
        "apply_draft",
        "report_knowledge_gap",
    ):
        assert w not in names
    emit = next(t for t in tools if t["name"] == EMIT_TOOL)
    assert emit["strict"] is True
    # payload is a STRING, not a nested object (heterogeneous payloads)
    op_props = emit["input_schema"]["properties"]["ops"]["items"]["properties"]
    assert op_props["payload_json"]["type"] == "string"
    assert set(op_props["op"]["enum"]) == set(_DEFAULT_KINDS) - {"search_statements"}


def test_parse_emit_input_parses_payload_json_string():
    data = _emit_input(
        ops=[_op("upsert_entity", {"name": "Acme", "description": "co"})]
    )
    ops, ledger, flagged, skipped = parse_emit_input(data)
    assert ops[0]["op"] == "upsert_entity"
    assert ops[0]["payload"] == {"name": "Acme", "description": "co"}


def test_parse_emit_input_raises_on_unparseable_payload():
    bad = _emit_input(
        ops=[
            {
                "op": "upsert_entity",
                "payload_json": "{not json",
                "rationale": "x",
                "targets_existing": [],
            }
        ]
    )
    try:
        parse_emit_input(bad)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# Happy path + floor
# --------------------------------------------------------------------------- #


def test_well_formed_text_creates_draft_with_queued_op():
    """A reconciled NEW fact -> a draft is created and the op queued via emitter."""
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())])
    ]
    result, client, substrate, emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    assert result.outcome == "draft_created"
    assert result.draft_id == "drf_1"
    assert len(result.ops) == 1
    assert result.ops[0].op == "upsert_statement"
    # the op was queued through the (only) write path: the emitter
    assert emitter.queued == [
        (
            "drf_1",
            "upsert_statement",
            {"kind": "event", "text": "an invite is submitted", "links": []},
        )
    ]
    assert result.trace["floor"]["satisfied"] is True
    # vocab was fetched deterministically first (3 calls), counts toward ops
    vocab_names = [c[0] for c in substrate.calls[:3]]
    assert vocab_names == [
        "list_statement_kinds",
        "list_link_types",
        "list_entity_link_types",
    ]


def test_floor_blocks_premature_emit_then_proceeds():
    """An emit before any reconcile/adjacency read is blocked; the loop continues."""
    responses = [
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit(), id="early")]),
        _message([_tool_use("discover_facts", {"texts": ["x"]})]),
        _message([_tool_use("search_statements", {"query": "x"})]),
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit(), id="real")]),
    ]
    result, client, substrate, _emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    assert ("discover_facts", {"texts": ["x"]}) in substrate.calls
    assert result.trace["floor"]["satisfied"] is True
    assert len(client.calls) == 4  # the premature emit did not terminate


def test_floor_blocks_new_ledger_row_missing_matched_against():
    """A NEW ledger row with no matched_against fails ledger validation."""
    incomplete = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is submitted"})
        ],
        ledger=[
            _ledger_row("an invite is submitted", "new", matched=[], considered=[])
        ],
    )
    good = _good_new_op_emit()
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, incomplete, id="bad")]),
        _message([_tool_use(EMIT_TOOL, good, id="good")]),
    ]
    result, client, _sub, _emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    # 2 reconcile turns + 1 blocked emit + 1 accepted emit = 4 model calls
    assert len(client.calls) == 4


# --------------------------------------------------------------------------- #
# NothingToIngest paths
# --------------------------------------------------------------------------- #


def test_all_duplicates_returns_nothing_to_ingest():
    emit = _emit_input(
        ledger=[_ledger_row("an invite is submitted", "duplicate", matched=["stm_5"])],
        skipped=["an invite is submitted :: stm_5"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, NothingToIngest)
    assert result.reason == "all candidates were duplicates"
    assert emitter.created == []  # no draft created
    assert result.trace["skipped_duplicates"] == ["an invite is submitted :: stm_5"]


def test_empty_emit_returns_nothing_extractable():
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, _emit_input())])
    ]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, NothingToIngest)
    assert result.reason == "nothing extractable"
    assert emitter.created == []


# --------------------------------------------------------------------------- #
# Validation: bad ops are flagged, never queued, never thrown
# --------------------------------------------------------------------------- #


def test_unknown_op_kind_is_flagged_not_queued():
    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement", {"kind": "event", "text": "an invite is submitted"}
            ),
            _op("delete_everything", {"target": "all"}),  # not an OpKind
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted", "new", matched=["stm_1"], considered=["stm_1"]
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert len(result.ops) == 1  # only the valid op queued
    assert any("delete_everything" in f for f in result.flagged)
    queued_kinds = [k for (_d, k, _p) in emitter.queued]
    assert queued_kinds == ["upsert_statement"]


def test_op_with_kind_not_in_valid_kinds_is_flagged():
    """An OpKind that isn't a registered substrate tool is rejected (curator
    replay could never run it)."""
    # emitter whose registry lacks merge_statements
    emitter = FakeEmitter(valid_kinds=_DEFAULT_KINDS - {"merge_statements"})
    emit = _emit_input(
        ops=[_op("merge_statements", {"from_id": "stm_1", "into_id": "stm_2"})],
        ledger=[
            _ledger_row("merge", "refinement", matched=["stm_1"], considered=["stm_2"])
        ],
        flagged=["a real contradiction between stm_1 and stm_2"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, _e = _run(responses, emitter=emitter)
    # model raised a real flag, so a draft is still created; the op is flagged out
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert any("not a registered substrate tool" in f for f in result.flagged)


def test_missing_required_key_is_flagged():
    emit = _emit_input(
        ops=[_op("replace_text", {"id": "stm_1"})],  # missing required "text"
        ledger=[
            _ledger_row("reword", "refinement", matched=["stm_1"], considered=["stm_1"])
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, _e = _run(responses)
    # only invalid op, no model flag -> degrades to NothingToIngest (see flagged trace)
    assert isinstance(result, NothingToIngest)
    assert any("missing required key" in f for f in result.trace["flagged"])


# --------------------------------------------------------------------------- #
# Phrasing pre-validation
# --------------------------------------------------------------------------- #


def test_phrasing_violation_sets_allow_flag_not_dropped(monkeypatch):
    """A statement that fails phrasing.check keeps the op but sets
    allow_phrasing_violations and records it — never silently dropped."""
    import mycelium.phrasing as phrasing

    def fake_check(text, kind="event"):
        return [
            {
                "category": "rule_shaped",
                "matched_text": "must",
                "position": 0,
                "rule": "no modal",
                "recommendation": "rephrase",
            }
        ]

    monkeypatch.setattr(phrasing, "check", fake_check)

    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement",
                {"kind": "event", "text": "the system must send an invite"},
            )
        ],
        ledger=[
            _ledger_row(
                "system sends invite", "new", matched=["stm_1"], considered=["stm_1"]
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    queued_payload = emitter.queued[0][2]
    assert queued_payload["allow_phrasing_violations"] is True
    assert any("phrasing" in f for f in result.flagged)
    assert "phrasing" in result.ops[0].rationale.lower()


# --------------------------------------------------------------------------- #
# Budget caps + degradation (never throws, never partial live-write)
# --------------------------------------------------------------------------- #


def test_op_cap_forces_finalize_with_forced_tool_choice():
    """Hitting the op cap forces a final emit_draft with forced tool_choice and
    thinking dropped."""
    # op_cap=3: 3 vocab calls hit the cap; the next iteration forces finalize.
    responses = [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    result, client, _sub, _e = _run(responses, op_cap=3)
    assert isinstance(result, DraftCreated)
    assert result.trace["forced_finalize"] == "op_cap"
    assert result.trace["degraded"] is True
    forced_call = client.calls[-1]
    assert forced_call["tool_choice"]["type"] == "tool"
    assert forced_call["tool_choice"]["name"] == EMIT_TOOL
    assert "thinking" not in forced_call


def test_op_cap_with_unresponsive_model_returns_nothing_never_raises():
    """Cap hit AND the forced finalize fails -> graceful NothingToIngest."""
    result, _client, _sub, emitter = _run([], op_cap=3)
    assert isinstance(result, NothingToIngest)
    assert result.trace["degraded"] is True
    assert "could not assemble a draft" in result.reason
    assert emitter.created == []  # never a partial draft


def test_api_error_degrades_to_forced_finalize():
    class Boom(FakeAnthropic):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("api down")
            # forced finalize turn succeeds
            return _message([_tool_use(EMIT_TOOL, _good_new_op_emit())])

    client = Boom([])
    substrate = FakeSubstrate()
    emitter = FakeEmitter()
    cfg = IngestConfig(trace_log_path=None)
    result = run_ingest(
        "x", client=client, substrate=substrate, emitter=emitter, config=cfg
    )
    assert isinstance(result, DraftCreated)
    assert result.trace["forced_finalize"] == "api_error"


def test_malformed_emit_reprompted_then_degrades():
    bad = {
        "ops": [
            {
                "op": "upsert_entity",
                "payload_json": "{not json",
                "rationale": "x",
                "targets_existing": [],
            }
        ],
        "ledger": [],
        "flagged": [],
        "skipped_duplicates": [],
    }
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, bad)]),
        _message([_tool_use(EMIT_TOOL, bad)]),  # still bad after re-prompt
    ]
    result, _client, _sub, _e = _run(responses)
    assert isinstance(result, NothingToIngest)
    assert "malformed twice" in result.reason


def test_no_terminal_tool_is_nudged_then_forced():
    responses = [
        _message([_text("let me think about the candidates")], stop="end_turn"),
        _message([_text("still thinking")], stop="end_turn"),
        # forced finalize turn produces the emit
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())]),
    ]
    result, _client, _sub, _e = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.trace["forced_finalize"] == "no_terminal"


# --------------------------------------------------------------------------- #
# Input guard + trace
# --------------------------------------------------------------------------- #


def test_oversized_input_is_truncated_and_noted():
    big = "x" * 100
    client = FakeAnthropic(
        _reconcile_then_adjacency()
        + [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    )
    substrate = FakeSubstrate()
    emitter = FakeEmitter()
    cfg = IngestConfig(max_input_chars=10, trace_log_path=None)
    result = run_ingest(
        big, client=client, substrate=substrate, emitter=emitter, config=cfg
    )
    assert isinstance(result, DraftCreated)
    assert result.trace["input_chars"] == 10
    assert any("truncated" in n for n in result.trace["notes"])


def test_trace_record_is_complete_and_serialisable():
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())])
    ]
    result, _client, _sub, _e = _run(responses)
    trace = result.trace
    for key in (
        "model",
        "outcome",
        "input_chars",
        "op_count",
        "op_cap",
        "wall_clock_s_limit",
        "latency_ms",
        "model_turns",
        "tool_calls",
        "candidate_ledger",
        "proposed_ops",
        "flagged",
        "skipped_duplicates",
        "gaps",
        "floor",
        "tokens",
        "cost_usd",
        "forced_finalize",
        "degraded",
        "notes",
    ):
        assert key in trace, f"trace missing {key}"
    assert trace["tool_calls"][0]["name"] == "list_statement_kinds"
    assert trace["op_count"] >= 5  # 3 vocab + reconcile + adjacency
    assert trace["candidate_ledger"]  # captured from the emit
    assert trace["proposed_ops"]
    json.dumps(trace)


def test_trace_written_to_jsonl_file(tmp_path):
    log = tmp_path / "ingest_trace.jsonl"
    client = FakeAnthropic(
        _reconcile_then_adjacency()
        + [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    )
    substrate = FakeSubstrate()
    emitter = FakeEmitter()
    cfg = IngestConfig(trace_log_path=str(log))
    run_ingest(
        "An invite is submitted.",
        client=client,
        substrate=substrate,
        emitter=emitter,
        config=cfg,
    )
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "draft_created"


def test_substrate_read_failure_is_surfaced_not_fabricated():
    results = {
        "discover_facts": [{"text": "x", "status": "new", "matches": []}],
        "search_statements": SubstrateError("index timeout"),
        "survey_statements": [{"id": "stm_1", "text": "y"}],
    }
    responses = [
        _message([_tool_use("discover_facts", {"texts": ["x"]})]),
        _message([_tool_use("search_statements", {"query": "x"})]),  # fails twice
        _message([_tool_use("survey_statements", {"query": "x adj"})]),  # adjacency ok
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())]),
    ]
    result, _client, _sub, _e = _run(responses, results=results)
    assert isinstance(result, DraftCreated)
    failed = [
        tc for tc in result.trace["tool_calls"] if tc["name"] == "search_statements"
    ]
    assert failed and failed[0]["ok"] is False and failed[0]["error"]


def test_unprocessed_ledger_rows_become_gaps():
    emit = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is submitted"})
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted", "new", matched=["stm_1"], considered=["stm_1"]
            ),
            _ledger_row(
                "a notification is sent",
                "unprocessed",
                note="cap hit before reconciling",
            ),
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, _e = _run(responses)
    assert isinstance(result, DraftCreated)
    assert any("a notification is sent" in g for g in result.trace["gaps"])


# --------------------------------------------------------------------------- #
# Acceptance criteria (Stage 3): the spec's (a)-(i) mapped one-to-one.
# --------------------------------------------------------------------------- #


# (a) genuinely-new text -> DraftCreated with upsert_statement/upsert_entity/
#     add_links ops + non-empty rationales.
def test_a_genuinely_new_text_creates_draft_with_entity_statement_and_links():
    emit = _emit_input(
        ops=[
            _op(
                "upsert_entity",
                {"name": "Reviewer", "description": "a person who reviews invites"},
                rationale="genuinely new named entity; no name matched",
            ),
            _op(
                "upsert_statement",
                {
                    "kind": "event",
                    "text": "an invite is reopened",
                    "mentions": [],
                    "links": [],
                },
                rationale="new event; discover_facts returned status=new",
            ),
            _op(
                "add_links",
                {
                    "links": [
                        {"from_id": "stm_new", "to_id": "stm_1", "link_type": "method"}
                    ]
                },
                rationale="wire the new event beside the adjacent lifecycle statement",
                targets=["stm_1"],
            ),
        ],
        ledger=[
            _ledger_row(
                "Reviewer entity", "new", matched=["ent_0"], note="no entity matched"
            ),
            _ledger_row(
                "invite reopened", "new", matched=["stm_1"], considered=["stm_1"]
            ),
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    kinds = {p.op for p in result.ops}
    assert {"upsert_entity", "upsert_statement", "add_links"} <= kinds
    assert all(p.rationale.strip() for p in result.ops)  # non-empty rationales
    queued_kinds = {k for (_d, k, _p) in emitter.queued}
    assert {"upsert_entity", "upsert_statement", "add_links"} <= queued_kinds


# (b) restating existing knowledge -> dupes in skipped_duplicates, NOT re-added.
def test_b_partial_duplicates_recorded_as_skipped_not_readded():
    emit = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is reopened"})
        ],
        ledger=[
            _ledger_row("an invite is submitted", "duplicate", matched=["stm_1"]),
            _ledger_row(
                "invite reopened",
                "new",
                matched=["stm_1"],
                note="no adjacent statement",
            ),
        ],
        skipped=["an invite is submitted :: stm_1"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    assert result.skipped_duplicates == ["an invite is submitted :: stm_1"]
    # only the new op queued; the duplicate is not re-added
    assert [k for (_d, k, _p) in emitter.queued] == ["upsert_statement"]


# (c) refinement -> a patch_statement/replace_text/upsert_statement(id=) op with
#     old->new in the rationale.
def test_c_refinement_proposes_patch_with_old_to_new_in_rationale():
    emit = _emit_input(
        ops=[
            _op(
                "patch_statement",
                {"id": "stm_1", "text": "an invite is reopened by a reviewer"},
                rationale=(
                    "OLD: 'an invite is reopened' -> NEW: 'an invite is reopened "
                    "by a reviewer' (text adds the actor)"
                ),
            )
        ],
        ledger=[
            _ledger_row(
                "invite reopened by reviewer",
                "refinement",
                matched=["stm_1"],
                note="existing statement is less specific; refine it",
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)

    assert isinstance(result, DraftCreated)
    (op,) = result.ops
    assert op.op == "patch_statement"
    assert "OLD" in op.rationale and "NEW" in op.rationale
    assert op.payload.get("id") == "stm_1"
    assert (
        "drf_1",
        "patch_statement",
        {"id": "stm_1", "text": "an invite is reopened by a reviewer"},
    ) in emitter.queued


# (d) contradiction -> appears in flagged, with NO resolution op proposed.
def test_d_contradiction_is_flagged_with_no_resolution_op():
    emit = _emit_input(
        ops=[],  # the model proposes NO resolution
        ledger=[
            _ledger_row(
                "invites cannot be reopened",
                "contradiction",
                matched=["stm_1"],
                note="text says cannot; stm_1 says an invite is reopened",
            )
        ],
        flagged=[
            "CONTRADICTION: text 'invites cannot be reopened' vs stm_1 "
            "'an invite is reopened' — both sides named, no resolution proposed"
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)

    assert isinstance(result, DraftCreated)  # the flag itself is a reviewable artifact
    assert any("CONTRADICTION" in f for f in result.flagged)
    assert result.ops == []  # no resolution op proposed
    assert emitter.queued == []  # nothing queued for the contradiction


# (e) NO LIVE WRITE — read substrate never sees a write primitive; the only
#     persistence is the emitter; the outcome is always draft/nothing.
_WRITE_PRIMITIVES = frozenset(
    {
        "upsert_statement",
        "upsert_statements",
        "upsert_entity",
        "add_links",
        "add_entity_links",
        "add_mentions",
        "patch_statement",
        "replace_text",
        "merge_statements",
        "move_name",
        "rename_name",
        "upsert_name",
        "merge_entities",
        "delete_statement",
        "delete_entity",
        "submit_draft",
        "apply_draft",
        "report_knowledge_gap",
    }
)


def test_e_no_write_primitive_dispatched_through_substrate_only_emitter_persists():
    emit = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is reopened"}),
            _op(
                "add_links",
                {
                    "links": [
                        {"from_id": "stm_a", "to_id": "stm_b", "link_type": "method"}
                    ]
                },
            ),
        ],
        ledger=[
            _ledger_row("invite reopened", "new", matched=["stm_1"], note="no adjacent")
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, substrate, emitter = _run(responses)

    dispatched = {name for (name, _args) in substrate.calls}
    assert not (dispatched & _WRITE_PRIMITIVES), (
        f"a write tool reached the read substrate: {dispatched & _WRITE_PRIMITIVES}"
    )
    # the only place ops landed is the emitter
    assert [k for (_d, k, _p) in emitter.queued] == ["upsert_statement", "add_links"]
    # discriminated outcome: a draft id, never a committed statement id
    assert isinstance(result, DraftCreated)
    assert result.draft_id.startswith("drf_")
    assert not result.draft_id.startswith("stm_")


def test_e_real_server_inner_tool_set_excludes_writes_and_report_knowledge_gap():
    """Wiring the REAL server InProcessSubstrate: the inner tool set offered to
    the model is read primitives only — no write tool, no report_knowledge_gap,
    not the harness itself."""
    from mycelium import server
    from mycelium.ask.substrate import InProcessSubstrate

    sub = InProcessSubstrate(server)
    inner = {s.name for s in sub.tool_specs()}
    assert {"search_statements", "survey_statements", "discover_facts"} <= inner
    assert "upsert_statement" not in inner
    assert "add_links" not in inner
    assert "report_knowledge_gap" not in inner
    assert "ingest" not in inner


def test_e_loop_module_imports_no_write_tool():
    """Structural: the loop's source references the read seam + draft emitter,
    and no live substrate-write call. The only write path is drafts_store via
    the emitter, in draft.py."""
    import inspect

    from mycelium.ingest import loop

    src = inspect.getsource(loop)
    assert "from ..ask.substrate import" in src  # read seam
    assert "from .draft import" in src  # the (only) write path
    assert "store.upsert_statement" not in src
    assert "submit_draft" not in src
    assert "apply_draft" not in src
    # the loop never imports the server's live store module
    assert "from .. import store" not in src
    assert "import store" not in src


def test_e_draft_emitter_is_the_only_write_path_and_uses_drafts_store():
    """Structural: the InProcessDraftEmitter writes via drafts_store only and
    never imports a substrate write tool nor touches server._conn."""
    import ast
    import inspect

    from mycelium.ingest import draft

    src = inspect.getsource(draft)
    assert "from .. import drafts_store" in src
    assert "drafts_store.create_draft" in src
    assert "drafts_store.add_op" in src

    # Scan the CODE only (drop docstrings/comments, which legitimately mention
    # `server._conn` to state it is never touched). The emitter must write to
    # the drafts DB connection, never the live substrate connection.
    tree = ast.parse(src)
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "_drafts_conn" in attrs  # the drafts DB connection is used
    assert "_conn" not in attrs  # the live substrate connection is not
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for w in ("upsert_statement", "add_links", "submit_draft", "apply_draft"):
        assert w not in attrs and w not in names


# (f) linking: a NEW statement links to a PRE-EXISTING statement id surfaced by a
#     scripted adjacency search.
def test_f_new_statement_links_to_preexisting_id_from_adjacency_search():
    results = {
        "discover_facts": [{"text": "invite reopened", "status": "new", "matches": []}],
        # the adjacency search surfaces a pre-existing statement to link to
        "search_statements": [{"id": "stm_existing", "text": "an invite is submitted"}],
    }
    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement",
                {
                    "kind": "event",
                    "text": "an invite is reopened",
                    "links": [{"to_id": "stm_existing", "link_type": "method"}],
                },
                rationale="link the new event to the adjacent submit event from search",
                targets=["stm_existing"],
            )
        ],
        ledger=[
            _ledger_row(
                "invite reopened",
                "new",
                matched=["stm_existing"],
                considered=["stm_existing"],
                note="adjacent submit event surfaced by search_statements",
            )
        ],
    )
    responses = [
        _message([_tool_use("discover_facts", {"texts": ["invite reopened"]})]),
        _message([_tool_use("search_statements", {"query": "invite"})]),  # adjacency
        _message([_tool_use(EMIT_TOOL, emit)]),
    ]
    result, _client, substrate, _emitter = _run(responses, results=results)

    assert isinstance(result, DraftCreated)
    # the adjacency search actually ran and returned the pre-existing id
    assert ("search_statements", {"query": "invite"}) in substrate.calls
    (op,) = result.ops
    links = op.payload.get("links") or []
    assert any(link.get("to_id") == "stm_existing" for link in links)
    assert "stm_existing" in op.targets_existing


# (g) doctrine loaded from FILE: system prompt contains doctrine.md content;
#     config.doctrine_path points at the bundled file; env override works.
def test_g_doctrine_loaded_from_bundled_file_into_system_prompt():
    import os

    from mycelium.ingest.config import _DEFAULT_DOCTRINE_PATH

    cfg = IngestConfig()
    assert cfg.doctrine_path == _DEFAULT_DOCTRINE_PATH
    assert cfg.doctrine_path.endswith("doctrine.md")
    assert os.path.exists(cfg.doctrine_path)

    with open(cfg.doctrine_path, encoding="utf-8") as fh:
        doctrine_text = fh.read()
    marker = "walkable story"  # a distinctive phrase from the bundled doctrine
    assert marker in doctrine_text

    emit = _emit_input(
        ledger=[_ledger_row("x", "duplicate", matched=["stm_1"])],
        skipped=["x :: stm_1"],
    )
    client = FakeAnthropic(
        _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    )
    run_ingest(
        "x",
        client=client,
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=IngestConfig(trace_log_path=None),
    )
    system_prompt = client.calls[0]["system"]
    assert marker in system_prompt  # the FILE content reached the model


def test_g_doctrine_path_override_via_env(tmp_path, monkeypatch):
    custom = tmp_path / "custom_doctrine.md"
    custom.write_text("CUSTOM DOCTRINE MARKER 12345", encoding="utf-8")
    monkeypatch.setenv("MYCELIUM_INGEST_DOCTRINE_PATH", str(custom))

    cfg = IngestConfig.from_env()
    assert cfg.doctrine_path == str(custom)

    emit = _emit_input(
        ledger=[_ledger_row("x", "duplicate", matched=["stm_1"])],
        skipped=["x :: stm_1"],
    )
    client = FakeAnthropic(
        _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    )
    run_ingest(
        "x", client=client, substrate=FakeSubstrate(), emitter=FakeEmitter(), config=cfg
    )
    assert "CUSTOM DOCTRINE MARKER 12345" in client.calls[0]["system"]


def test_g_unreadable_doctrine_falls_back_to_base_prompt_with_note():
    cfg = IngestConfig(
        doctrine_path="/nonexistent/path/doctrine.md", trace_log_path=None
    )
    emit = _emit_input(
        ledger=[_ledger_row("x", "duplicate", matched=["stm_1"])],
        skipped=["x :: stm_1"],
    )
    client = FakeAnthropic(
        _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    )
    result = run_ingest(
        "x", client=client, substrate=FakeSubstrate(), emitter=FakeEmitter(), config=cfg
    )
    assert any("doctrine unreadable" in n for n in result.trace["notes"])
    # base protocol still present in the system prompt
    assert "reviewable DRAFT" in client.calls[0]["system"]


# (h) vocabulary fetched at runtime — the three list_* calls happen first.
def test_h_vocabulary_fetched_at_session_start():
    responses = _reconcile_then_adjacency() + [
        _message([_tool_use(EMIT_TOOL, _good_new_op_emit())])
    ]
    _result, _client, substrate, _emitter = _run(responses)
    assert [name for (name, _a) in substrate.calls[:3]] == [
        "list_statement_kinds",
        "list_link_types",
        "list_entity_link_types",
    ]


# (i) trace + graceful cap — tiny op_cap degrades, records the gap, still emits a
#     draft (or NothingToIngest), never an exception.
def test_i_tiny_op_cap_degrades_records_gap_and_still_emits_draft():
    emit = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is reopened"})
        ],
        ledger=[
            _ledger_row(
                "invite reopened",
                "new",
                matched=["stm_1"],
                note="reconciled before cap",
            ),
            _ledger_row(
                "invite archived", "unprocessed", note="cap hit before reconcile"
            ),
        ],
    )
    # op_cap=3: the 3 vocab fetches alone hit the cap, forcing finalize on the
    # very first loop iteration.
    responses = [_message([_tool_use(EMIT_TOOL, emit)])]
    result, client, _sub, _emitter = _run(responses, op_cap=3)

    assert isinstance(result, (DraftCreated, NothingToIngest))  # never an exception
    assert result.trace["degraded"] is True
    assert result.trace["forced_finalize"] == "op_cap"
    assert any("invite archived" in g for g in result.trace["gaps"])
    forced_call = client.calls[-1]
    assert forced_call["tool_choice"] == {
        "type": "tool",
        "name": EMIT_TOOL,
        "disable_parallel_tool_use": True,
    }
    assert "thinking" not in forced_call


# --------------------------------------------------------------------------- #
# T-9: the REAL InProcessDraftEmitter against an in-memory drafts DB.
# Every behavioral test above uses FakeEmitter; this drives the real write path
# end-to-end (drafts_store on a :memory: connection) to close that gap.
# --------------------------------------------------------------------------- #


def _real_emitter_against_memory_db():
    """A real InProcessDraftEmitter wired to a stub server_module that exposes a
    live in-memory `_drafts_conn` and a `TOOLS` list whose function names cover
    the op kinds."""
    from mycelium import drafts_store
    from mycelium.ingest.draft import InProcessDraftEmitter

    conn = drafts_store.connect(":memory:")
    drafts_store.migrate(conn)

    def _named(name):
        f = lambda **kw: None  # noqa: E731 — a stand-in whose __name__ is the op kind
        f.__name__ = name
        return f

    tools = [_named(n) for n in sorted(_DEFAULT_KINDS)]
    server_module = types.SimpleNamespace(_drafts_conn=conn, TOOLS=tools)
    return InProcessDraftEmitter(server_module=server_module), conn, drafts_store


def test_t9_real_emitter_persists_draft_and_ops_via_drafts_store_and_drops_none():
    """Drive the REAL InProcessDraftEmitter through one run_ingest call against an
    in-memory drafts DB: a draft row + op rows land via drafts_store, and a
    None-valued payload key is dropped at queue time."""
    emitter, conn, drafts_store = _real_emitter_against_memory_db()

    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement",
                # id is explicitly null — must be dropped by add_op, not queued
                {
                    "kind": "event",
                    "text": "an invite is submitted",
                    "links": [],
                    "id": None,
                },
                targets=["stm_99"],
            )
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_99"],
                considered=["stm_99"],
                note="adjacent",
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    client = FakeAnthropic(responses)
    cfg = IngestConfig(thinking=True, trace_log_path=None)
    result = run_ingest(
        "An invite is submitted.",
        client=client,
        substrate=FakeSubstrate(),
        emitter=emitter,
        config=cfg,
    )

    assert isinstance(result, DraftCreated)
    # the draft row really landed in the drafts DB
    draft_row = drafts_store.get_draft(conn, result.draft_id)
    assert draft_row is not None
    assert drafts_store.status_for(draft_row) == "open"
    # the op row landed too, and the None-valued `id` key was dropped at queue
    op_rows = drafts_store.list_ops(conn, result.draft_id)
    assert len(op_rows) == 1
    queued = drafts_store.serialize_op(op_rows[0])
    assert queued["kind"] == "upsert_statement"
    assert queued["payload"] == {
        "kind": "event",
        "text": "an invite is submitted",
        "links": [],
    }
    assert "id" not in queued["payload"]  # None-valued key dropped
    assert "mentions" not in queued["payload"]  # derived from text, dropped


# --------------------------------------------------------------------------- #
# T-10: the untested forced-finalize reasons — wall_clock and floor_stuck.
# --------------------------------------------------------------------------- #


def test_t10_wall_clock_forces_finalize():
    """A ~zero wall clock forces finalize on the first loop iteration with the
    'wall_clock' reason."""
    responses = [_message([_tool_use(EMIT_TOOL, _good_new_op_emit())])]
    # op_cap stays generous so the op_cap gate doesn't fire first; the wall clock
    # (checked after the op_cap gate) is what trips.
    result, client, _sub, _e = _run(responses, wall_clock_s=0.0)
    assert isinstance(result, DraftCreated)
    assert result.trace["forced_finalize"] == "wall_clock"
    assert result.trace["degraded"] is True
    # LOW-7: a forced finalize always records a harness-side gap
    assert any("forced finalize (wall_clock)" in g for g in result.trace["gaps"])


def test_t10_floor_stuck_forces_finalize_no_floorless_emit_accepted():
    """A model that keeps emitting prematurely with no reads exhausts the floor
    blocks and is forced-finalized; no floorless emit is ever accepted as a
    normal DraftCreated."""
    # 4 consecutive premature emits with zero reads: _MAX_FLOOR_BLOCKS (3) blocks
    # then the 4th attempt trips floor_stuck. The forced finalize then emits.
    emit = _good_new_op_emit()
    responses = [
        _message([_tool_use(EMIT_TOOL, emit, id=f"early{i}")]) for i in range(4)
    ] + [
        # the forced-finalize turn (tool_choice forced) succeeds
        _message([_tool_use(EMIT_TOOL, emit, id="forced")]),
    ]
    result, client, substrate, _e = _run(responses)
    assert result.trace["forced_finalize"] == "floor_stuck"
    assert result.trace["degraded"] is True
    # the floor was never satisfied (no reconcile/adjacency reads happened)
    assert result.trace["floor"]["satisfied"] is False
    # only vocab reads ran — no reconcile/adjacency read was ever dispatched
    non_vocab = [
        c
        for c in substrate.calls
        if c[0]
        not in ("list_statement_kinds", "list_link_types", "list_entity_link_types")
    ]
    assert non_vocab == []


# --------------------------------------------------------------------------- #
# T-11: the new validation behavior (HIGH-1, HIGH-2, MED-3, MED-4).
# --------------------------------------------------------------------------- #


def test_t11_new_upsert_statement_normalizes_missing_links_and_drops_mentions():
    """A NEW upsert_statement with only {kind, text} is queued replay-safe with
    links=[] (the real tool requires it, no default). Any `mentions` the model
    proposes is dropped — mentions are derived from text, not asserted."""
    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement",
                {
                    "kind": "event",
                    "text": "an invite is submitted",
                    "mentions": ["ent_x"],
                },
            )
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_1"],
                considered=["stm_1"],
                note="adj",
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    (_d, kind, payload) = emitter.queued[0]
    assert kind == "upsert_statement"
    assert "mentions" not in payload  # derived from text, dropped from the op
    assert payload["links"] == []


def test_t11_upsert_entity_missing_description_is_flagged_not_queued():
    """upsert_entity requires description (no sensible default) -> reject + flag,
    never queue."""
    emit = _emit_input(
        ops=[_op("upsert_entity", {"name": "Acme"})],  # missing description
        ledger=[_ledger_row("Acme entity", "new", matched=["ent_0"], note="new")],
        flagged=["a real contradiction so a draft is still created"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)  # the model's flag keeps the draft
    assert result.ops == []  # the entity op was rejected
    assert any(
        "missing required key" in f and "upsert_entity" in f for f in result.flagged
    )
    assert emitter.queued == []


def test_t11_add_entity_links_with_wrong_edge_keys_is_flagged():
    """An add_entity_links op using add_links key names (from_id/to_id) is
    flagged, not queued — the real tool needs from_entity_id/to_entity_id."""
    emit = _emit_input(
        ops=[
            _op(
                "add_entity_links",
                {
                    "links": [
                        {"from_id": "ent_1", "to_id": "ent_2", "link_type": "owns"}
                    ]
                },
            )
        ],
        ledger=[
            _ledger_row(
                "entity link", "refinement", matched=["ent_1"], considered=["ent_2"]
            )
        ],
        flagged=["a real contradiction keeping the draft alive"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert any("add_entity_links" in f for f in result.flagged)
    assert emitter.queued == []


def test_t11_partial_add_op_failure_still_returns_draft_with_real_id():
    """MED-4: if one add_op fails after the draft was created, the draft id is
    NEVER discarded — DraftCreated returns with the real id, the good op queued,
    and the failed op moved to flagged."""

    class FlakyEmitter(FakeEmitter):
        def add_op(self, draft_id, kind, payload):
            if kind == "add_links":
                raise RuntimeError("simulated draft store write error")
            return super().add_op(draft_id, kind, payload)

    emitter = FlakyEmitter()
    emit = _emit_input(
        ops=[
            _op("upsert_statement", {"kind": "event", "text": "an invite is reopened"}),
            _op(
                "add_links",
                {
                    "links": [
                        {"from_id": "stm_a", "to_id": "stm_b", "link_type": "method"}
                    ]
                },
            ),
        ],
        ledger=[_ledger_row("invite reopened", "new", matched=["stm_1"], note="adj")],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, _e = _run(responses, emitter=emitter)

    assert isinstance(result, DraftCreated)
    assert result.draft_id == "drf_1"  # the real, created draft id — not discarded
    assert [p.op for p in result.ops] == ["upsert_statement"]  # only the good op
    assert [k for (_d, k, _p) in emitter.queued] == ["upsert_statement"]
    assert any("add_links" in f and "draft store error" in f for f in result.flagged)


# --------------------------------------------------------------------------- #
# T-12: the unexpected-key whitelist (FIX 1) + None-required-key (FIX 2).
#
# The curator replays each op as wrapper(**payload) with ZERO key filtering and
# is ALL-OR-NOTHING: one op raising TypeError aborts the whole draft. So a
# plausible-but-wrong key on a scalar-signature tool must be rejected by the
# validator, not queued. The bind-proof test closes the loop: every op the
# validator accepts must bind cleanly against the real tool signature.
# --------------------------------------------------------------------------- #


def test_t12_patch_statement_with_unexpected_links_key_is_flagged_not_queued():
    """patch_statement accepts {id, kind, text, mentions, ...} but NOT 'links';
    a bogus 'links' key would TypeError at replay -> flag-and-skip the whole op."""
    emit = _emit_input(
        ops=[
            _op(
                "patch_statement",
                {
                    "id": "stm_1",
                    "text": "an invite is reopened",
                    "links": [{"to_id": "stm_2", "link_type": "method"}],
                },
            )
        ],
        ledger=[
            _ledger_row(
                "invite reopened", "refinement", matched=["stm_1"], considered=["stm_1"]
            )
        ],
        flagged=["a real contradiction so the draft is still created"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)  # the model flag keeps the draft alive
    assert result.ops == []
    assert emitter.queued == []
    assert any(
        "patch_statement" in f and "unexpected key" in f and "links" in f
        for f in result.flagged
    )


def test_t12_merge_statements_with_unexpected_reason_key_is_flagged():
    """merge_statements accepts only {from_id, into_id}; an extra 'reason' key
    would TypeError at replay -> flagged, not queued."""
    emit = _emit_input(
        ops=[
            _op(
                "merge_statements",
                {
                    "from_id": "stm_1",
                    "into_id": "stm_2",
                    "reason": "they are the same fact",
                },
            )
        ],
        ledger=[
            _ledger_row("merge", "refinement", matched=["stm_1"], considered=["stm_2"])
        ],
        flagged=["a real contradiction keeping the draft alive"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert emitter.queued == []
    assert any(
        "merge_statements" in f and "unexpected key" in f and "reason" in f
        for f in result.flagged
    )


def test_t12_replace_text_with_unexpected_links_key_is_flagged():
    """replace_text accepts {id, text, allow_phrasing_violations}; an extra
    'links' key would TypeError at replay -> flagged, not queued."""
    emit = _emit_input(
        ops=[
            _op(
                "replace_text",
                {
                    "id": "stm_1",
                    "text": "an invite is reopened",
                    "links": [{"to_id": "stm_2", "link_type": "method"}],
                },
            )
        ],
        ledger=[
            _ledger_row("reword", "refinement", matched=["stm_1"], considered=["stm_1"])
        ],
        flagged=["a real contradiction keeping the draft alive"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert emitter.queued == []
    assert any(
        "replace_text" in f and "unexpected key" in f and "links" in f
        for f in result.flagged
    )


def test_t12_upsert_entity_with_none_description_is_flagged_not_queued():
    """FIX 2: a required key present-but-None (upsert_entity description=None) is
    treated as missing — the emitter would drop the None key and the real tool
    would raise 'missing a required argument' at replay."""
    emit = _emit_input(
        ops=[_op("upsert_entity", {"name": "Acme", "description": None})],
        ledger=[_ledger_row("Acme entity", "new", matched=["ent_0"], note="new")],
        flagged=["a real contradiction so the draft is still created"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert emitter.queued == []
    assert any(
        "missing required key" in f and "upsert_entity" in f for f in result.flagged
    )


def test_t12_upsert_statement_with_none_kind_and_text_is_flagged():
    """FIX 2: upsert_statement {kind: None, text: None} is rejected — both
    required keys are present-but-None. The mentions/links normalization runs
    AFTER this gate, so it never masks a None-valued kind/text."""
    emit = _emit_input(
        ops=[_op("upsert_statement", {"kind": None, "text": None})],
        ledger=[_ledger_row("x", "new", matched=["stm_1"], considered=["stm_1"])],
        flagged=["a real contradiction so the draft is still created"],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert result.ops == []
    assert emitter.queued == []
    assert any(
        "missing required key" in f and "upsert_statement" in f for f in result.flagged
    )


def test_t12_legitimate_optional_keys_are_not_flagged():
    """Optional params that ARE in the real signature (incoming_links, id,
    allow_phrasing_violations) must pass the unexpected-key filter — only keys
    the tool does NOT accept are rejected."""
    emit = _emit_input(
        ops=[
            _op(
                "upsert_statement",
                {
                    "kind": "event",
                    "text": "an invite is submitted",
                    "mentions": [],
                    "links": [],
                    "id": "stm_1",
                    "incoming_links": [],
                    "allow_phrasing_violations": True,
                },
            )
        ],
        ledger=[
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_1"],
                considered=["stm_1"],
                note="adj",
            )
        ],
    )
    responses = _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emit)])]
    result, _client, _sub, emitter = _run(responses)
    assert isinstance(result, DraftCreated)
    assert [p.op for p in result.ops] == ["upsert_statement"]
    assert not any("unexpected key" in f for f in result.flagged)
    (_d, _k, payload) = emitter.queued[0]
    assert payload.get("id") == "stm_1"
    assert payload.get("incoming_links") == []
    assert payload.get("allow_phrasing_violations") is True


#: A representative VALID payload + a backing ledger row for each of the 9
#: emittable op kinds. Each must pass _validate_op and then bind cleanly against
#: the real tool's signature (proving no validator-accepted op can TypeError at
#: replay). Run one op per draft so each is isolated and coverage is satisfied
#: per-run.
_BIND_PROOF_CASES = {
    "upsert_statement": (
        {
            "kind": "event",
            "text": "an invite is submitted",
            "mentions": [],
            "links": [],
        },
        [
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_1"],
                considered=["stm_1"],
                note="adj",
            )
        ],
    ),
    "upsert_statements": (
        {
            "statements": [
                {
                    "kind": "event",
                    "text": "an invite is submitted",
                    "mentions": [],
                    "links": [],
                }
            ]
        },
        [
            _ledger_row(
                "an invite is submitted",
                "new",
                matched=["stm_1"],
                considered=["stm_1"],
                note="adj",
            )
        ],
    ),
    "upsert_entity": (
        {"name": "Acme", "description": "a company"},
        [_ledger_row("Acme entity", "new", matched=["ent_0"], note="new entity")],
    ),
    "add_links": (
        {"links": [{"from_id": "stm_1", "to_id": "stm_2", "link_type": "method"}]},
        [_ledger_row("link", "refinement", matched=["stm_1"], considered=["stm_2"])],
    ),
    "add_entity_links": (
        {
            "links": [
                {
                    "from_entity_id": "ent_1",
                    "to_entity_id": "ent_2",
                    "link_type": "owns",
                }
            ]
        },
        [
            _ledger_row(
                "entity link", "refinement", matched=["ent_1"], considered=["ent_2"]
            )
        ],
    ),
    "patch_statement": (
        {"id": "stm_1", "text": "an invite is reopened"},
        [
            _ledger_row(
                "invite reopened", "refinement", matched=["stm_1"], considered=["stm_1"]
            )
        ],
    ),
    "replace_text": (
        {"id": "stm_1", "text": "an invite is reopened"},
        [
            _ledger_row(
                "invite reopened", "refinement", matched=["stm_1"], considered=["stm_1"]
            )
        ],
    ),
    "merge_statements": (
        {"from_id": "stm_1", "into_id": "stm_2"},
        [_ledger_row("merge", "refinement", matched=["stm_1"], considered=["stm_2"])],
    ),
}


def test_t12_every_validator_accepted_op_binds_against_real_signature():
    """BIND-PROOF: for a representative valid payload of EACH emittable op kind,
    the validator accepts and queues it, and the QUEUED payload binds against the
    real tool's _ORIG_SIGNATURES entry without raising — so no op the validator
    accepts can TypeError ('unexpected keyword argument' / 'missing a required
    argument') at the curator's all-or-nothing replay."""
    from mycelium import server

    assert set(_BIND_PROOF_CASES) == set(_DEFAULT_KINDS) - {"search_statements"}, (
        "bind-proof must cover exactly the emittable op kinds"
    )
    for kind, (payload, ledger) in _BIND_PROOF_CASES.items():
        emit = _emit_input(
            ops=[_op(kind, payload)],
            ledger=ledger,
            flagged=[
                "a real contradiction so a draft is created even for non-statement ops"
            ],
        )
        responses = _reconcile_then_adjacency() + [
            _message([_tool_use(EMIT_TOOL, emit)])
        ]
        result, _client, _sub, emitter = _run(responses)
        assert isinstance(result, DraftCreated), f"{kind}: expected DraftCreated"
        queued = [(k, p) for (_d, k, p) in emitter.queued if k == kind]
        assert len(queued) == 1, (
            f"{kind}: expected exactly one queued op, got {emitter.queued}"
        )
        _k, queued_payload = queued[0]
        sig = server._ORIG_SIGNATURES.get(kind)
        assert sig is not None, f"{kind}: missing from _ORIG_SIGNATURES"
        # This is the exact call shape the curator replays. It must NOT raise.
        sig.bind(**queued_payload)
