"""Tests for the `docgen` generation loop.

The loop is exercised with a fake Anthropic client (scripts the model's
tool-use turns), a fake substrate (canned read results), a recording gap
reporter, and a real in-memory prompt store holding the guideline rows — no
server, no network, no API key. Each test maps to a harness invariant.

What cannot be proven here is the quality of the prose, which is the model's;
what is proven is everything the harness decides — which set the run may
choose from, what it will refuse to record, and that a claim it could not
source becomes a filed gap rather than a paragraph.
"""

from __future__ import annotations

import json
import types

import pytest

from mycelium import guidelines, prompt_store
from mycelium.ask.substrate import InProcessSubstrate, SubstrateError, ToolSpec
from mycelium.docgen import DocgenConfig, DocumentWritten, NothingWritten
from mycelium.docgen.loop import _slug, run_docgen
from mycelium.docgen.tools import (
    EMIT_TOOL,
    GAP_TOOL,
    RESOLVE_TOOL,
    REVIEW_TOOL,
    build_tools,
)

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


def _resolve(set_name="kb-authoring", document_type="how-to"):
    return _message(
        [
            _tool_use(
                RESOLVE_TOOL,
                {
                    "guideline_set": set_name,
                    "document_type": document_type,
                    "reason": "the request asks how to do something",
                },
            )
        ]
    )


def _emit(**overrides):
    payload = {
        "title": "Configuring single sign-on",
        "body": "# Configuring single sign-on\n\nDo the thing.\n",
        "statement_ids": ["stm_1"],
        "gaps": [],
    }
    payload.update(overrides)
    return _message([_tool_use(EMIT_TOOL, payload)])


def _review_ok(*, check_exposure: bool = True):
    payload = {"conformance": {"status": "pass", "findings": []}}
    if check_exposure:
        payload["exposure"] = {"status": "pass", "findings": []}
    return _message(
        [
            _tool_use(
                REVIEW_TOOL,
                payload,
            )
        ]
    )


def _review_fail(
    *,
    check: str = "conformance",
    where: str = "Steps",
    problem: str = "the required verification step is missing",
    status: str = "fail",
    findings: list[dict] | None = None,
):
    payload = {
        "exposure": {"status": "pass", "findings": []},
        "conformance": {"status": "pass", "findings": []},
    }
    payload[check] = {
        "status": status,
        "findings": (
            [{"where": where, "problem": problem}] if findings is None else findings
        ),
    }
    return _message([_tool_use(REVIEW_TOOL, payload)])


class FakeAnthropic:
    """Scripts a sequence of model responses; records each request's kwargs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def with_options(self, **_kw):
        return self

    def create(self, **kwargs):
        messages = kwargs.get("messages") or []
        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            blocks = message.get("content")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                block_type = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if block_type != "tool_use":
                    continue
                tool_use_id = (
                    block.get("id")
                    if isinstance(block, dict)
                    else getattr(block, "id", None)
                )
                following = messages[index + 1] if index + 1 < len(messages) else {}
                results = following.get("content", [])
                answered = following.get("role") == "user" and any(
                    isinstance(result, dict)
                    and result.get("type") == "tool_result"
                    and result.get("tool_use_id") == tool_use_id
                    for result in results
                )
                assert answered, f"unanswered tool_use id: {tool_use_id}"
        # `messages` is one list the loop mutates in place, so the snapshot has
        # to be taken here or every recorded call would show the final state.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


_MIN_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}

_READ_NAMES = (
    "survey_statements",
    "search_statements",
    "grep_statements",
    "get_statements",
    "get_entity",
    "discover_facts",
    "list_statement_kinds",
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


class FakeGapReporter:
    def __init__(self, fail: bool = False):
        self.filed: list[str] = []
        self._fail = fail

    def __call__(self, text: str):
        if self._fail:
            raise RuntimeError("gap store is down")
        self.filed.append(text)
        return {"gap_id": f"gap_{len(self.filed)}"}


#: A statement the fake substrate hands back, so a run has something to cite.
_STATEMENT = {"id": "stm_1", "kind": "capability", "text": "a tenant can enable sso"}


def _substrate(**overrides):
    results = {"survey_statements": [_STATEMENT], "get_statements": [_STATEMENT]}
    results.update(overrides)
    return FakeSubstrate(results)


# --------------------------------------------------------------------------- #
# The prompt store: guideline rows + doctrine, as a booted instance would have
# --------------------------------------------------------------------------- #


@pytest.fixture
def prompts_db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    prompt_store.use_connection(conn)
    try:
        yield conn
    finally:
        prompt_store.reset()
        conn.close()


def _save_set(conn, set_name: str, slots: dict[str, str]) -> None:
    for slot, text in slots.items():
        prompt_store.save(
            conn, type=guidelines.TYPE, name=f"{set_name}/{slot}", text=text
        )


@pytest.fixture
def kb_set(prompts_db):
    _save_set(
        prompts_db,
        "kb-authoring",
        {
            "guidance": "SET-WIDE GUIDANCE: source everything.",
            "exposure": "EXPOSURE RULES: reveal only published behaviour.",
            "how-to": "HOW-TO TEMPLATE: steps.",
            "reference": "REFERENCE TEMPLATE: tables.",
        },
    )
    return prompts_db


def _config(**overrides) -> DocgenConfig:
    base = {
        "trace_dir": "",
        "trace_log_path": None,
        "thinking": False,
    }
    base.update(overrides)
    return DocgenConfig(**base)


def _run(client, substrate=None, report_gap=None, config=None, **kwargs):
    return run_docgen(
        kwargs.pop("prompt", "how do I configure single sign-on"),
        client=client,
        substrate=substrate if substrate is not None else _substrate(),
        report_gap=report_gap if report_gap is not None else FakeGapReporter(),
        config=config or _config(),
        **kwargs,
    )


def _execute_with(*, load_texts, client, guideline_set, document_type, catalogue=None):
    """Drive the core directly, with the guideline texts injected.

    `run_docgen` reads them from the prompt store, which cannot produce a
    listed-but-unloadable template on demand. `_execute` takes the reader as a
    plain callable precisely so that case is provable without one.
    """
    from mycelium.docgen.loop import _execute

    return _execute(
        "how do I configure single sign-on",
        requested_set=guideline_set,
        requested_type=document_type,
        client=client,
        substrate=_substrate(),
        report_gap=FakeGapReporter(),
        config=_config(),
        doctrine_text="",
        doctrine_note=None,
        catalogue=catalogue or {guideline_set: [document_type]},
        load_texts=load_texts,
    )


# --------------------------------------------------------------------------- #
# The tool surface: what the model can and cannot reach
# --------------------------------------------------------------------------- #


def _reader(name):
    def fn(**kwargs):
        return {"ok": name}

    fn.__name__ = name
    fn._mycelium_required_role = "reader"
    return fn


def _writer(name):
    def fn(**kwargs):
        return {}

    fn.__name__ = name
    fn._mycelium_required_role = "writer"
    return fn


def test_the_loop_names_no_read_primitive_of_its_own():
    """The read surface is whatever `ask/substrate.py` discovers, so a future
    read primitive reaches a documentation run with no edit in `docgen`."""
    stub = types.SimpleNamespace(
        TOOLS=[
            _reader("search_widgets"),  # a hypothetical FUTURE read primitive
            _reader("report_knowledge_gap"),  # withheld by discovery
            _writer("upsert_widget"),
        ]
    )
    names = [t["name"] for t in build_tools(InProcessSubstrate(stub).tool_specs())]

    assert names == ["search_widgets", GAP_TOOL, EMIT_TOOL]


def test_the_gap_report_is_offered_although_discovery_withholds_it():
    """`report_knowledge_gap` is reader-role but writes a record, so
    auto-discovery excludes it. A generation run wants it, and says so here —
    which is the only reason it is in the list."""
    from mycelium import server

    discovered = {s.name for s in InProcessSubstrate(server).tool_specs()}
    offered = {t["name"] for t in build_tools(InProcessSubstrate(server).tool_specs())}

    assert GAP_TOOL not in discovered
    assert GAP_TOOL in offered


def test_no_tool_the_model_sees_can_reach_the_substrate_or_a_draft():
    """The structural read-only guarantee, against the REAL registry: no
    mutation-prefixed tool, and no `draft_id` on anything."""
    from mycelium import server

    tools = build_tools(InProcessSubstrate(server).tool_specs())
    for tool in tools:
        assert not tool["name"].startswith(server._MUTATION_PREFIXES), tool["name"]
        assert "draft_id" not in (tool["input_schema"].get("properties") or {})


# --------------------------------------------------------------------------- #
# Resolution: which set and type the run writes against
# --------------------------------------------------------------------------- #


def test_resolution_offers_exactly_what_the_store_holds(kb_set):
    """A set added purely as rows is selectable with no code change: the
    resolution tool's enums ARE the listing."""
    _save_set(
        kb_set,
        "internal-doc",
        {"guidance": "terse", "exposure": "staff-safe", "reference": "table"},
    )
    client = FakeAnthropic(
        [_resolve("internal-doc", "reference"), _emit(), _review_ok()]
    )

    result = _run(client)

    schema = client.calls[0]["tools"][0]["input_schema"]["properties"]
    assert schema["guideline_set"]["enum"] == ["internal-doc", "kb-authoring"]
    assert schema["document_type"]["enum"] == ["how-to", "reference"]
    assert isinstance(result, DocumentWritten)
    assert (result.guideline_set, result.document_type) == (
        "internal-doc",
        "reference",
    )


def test_a_request_that_named_both_costs_no_resolution_turn(kb_set):
    client = FakeAnthropic([_emit(), _review_ok()])

    result = _run(client, guideline_set="kb-authoring", document_type="reference")

    assert isinstance(result, DocumentWritten)
    assert result.document_type == "reference"
    # One writer turn and one independent review. Nothing was asked of the
    # model about the set before the writer started.
    assert len(client.calls) == 2
    assert result.trace["resolution_reason"] == "named by the request"


def test_a_named_set_narrows_the_choice_to_its_own_types(kb_set):
    """The request fixed the set, so only that set's types are offerable —
    the model cannot answer with a type belonging to a different set."""
    _save_set(
        kb_set,
        "internal-doc",
        {"guidance": "terse", "exposure": "staff-safe", "tutorial": "walk"},
    )
    client = FakeAnthropic([_resolve("kb-authoring", "how-to"), _emit(), _review_ok()])

    _run(client, guideline_set="kb-authoring")

    schema = client.calls[0]["tools"][0]["input_schema"]["properties"]
    assert schema["guideline_set"]["enum"] == ["kb-authoring"]
    assert schema["document_type"]["enum"] == ["how-to", "reference"]


def test_a_pair_that_does_not_exist_together_is_sent_back_then_refused(kb_set):
    """`tutorial` exists in another set but not in this one. The harness says
    so once; a run that still cannot name a real pair writes nothing rather
    than falling back to a guess."""
    _save_set(
        kb_set,
        "internal-doc",
        {"guidance": "terse", "exposure": "staff-safe", "tutorial": "walk"},
    )
    client = FakeAnthropic(
        [_resolve("kb-authoring", "tutorial"), _resolve("kb-authoring", "tutorial")]
    )

    result = _run(client)

    assert isinstance(result, NothingWritten)
    assert "could not settle" in result.reason
    # Sent as a tool_result, not as plain user text: the assistant turn it
    # answers carries a pending tool_use, and the API requires that be
    # answered before the next turn.
    retry = client.calls[1]["messages"][-1]["content"][0]
    assert retry["type"] == "tool_result"
    assert retry["is_error"] is True
    assert "'tutorial' is not a document type 'kb-authoring' has" in retry["content"]
    assert "['how-to', 'reference']" in retry["content"]


def test_a_named_document_type_is_not_up_for_decision(kb_set):
    """The request named a type but no set, so only the set is open. The type
    is removed from the choice rather than merely asked for in prose — a
    strict enum of one — and a model that answers with a different one is
    treated as not having chosen."""
    _save_set(
        kb_set,
        "internal-doc",
        {"guidance": "terse", "exposure": "staff-safe", "reference": "table"},
    )
    client = FakeAnthropic(
        [
            _resolve("kb-authoring", "how-to"),
            _resolve("internal-doc", "reference"),
            _emit(),
            _review_ok(),
        ]
    )

    result = _run(client, document_type="reference")

    schema = client.calls[0]["tools"][0]["input_schema"]["properties"]
    assert schema["document_type"]["enum"] == ["reference"]
    assert schema["guideline_set"]["enum"] == ["internal-doc", "kb-authoring"]
    # The first answer swapped the type; it was sent back, not accepted.
    assert isinstance(result, DocumentWritten)
    assert (result.guideline_set, result.document_type) == (
        "internal-doc",
        "reference",
    )


def test_a_named_type_no_configured_set_can_write_refuses(kb_set):
    client = FakeAnthropic([])

    result = _run(client, document_type="tutorial")

    assert isinstance(result, NothingWritten)
    assert "no configured guideline set has a template" in result.reason
    assert client.calls == []


def test_a_named_pair_that_does_not_exist_is_refused_not_re_decided(kb_set):
    """`request_documentation` refuses this at the door; if one reaches the
    loop anyway it is a refusal, not an invitation to pick something else."""
    client = FakeAnthropic([])

    result = _run(client, guideline_set="kb-authoring", document_type="tutorial")

    assert isinstance(result, NothingWritten)
    assert "no template for" in result.reason
    assert client.calls == []


def test_an_unknown_requested_set_refuses_without_asking_the_model(kb_set):
    client = FakeAnthropic([])

    result = _run(client, guideline_set="no-such-set")

    assert isinstance(result, NothingWritten)
    assert "not configured" in result.reason
    assert client.calls == []


def test_an_empty_store_refuses_rather_than_inventing_a_set(prompts_db):
    client = FakeAnthropic([])

    result = _run(client)

    assert isinstance(result, NothingWritten)
    assert result.reason == "no guideline sets are configured"
    assert client.calls == []


def test_a_model_failure_during_resolution_degrades_to_nothing_written(kb_set):
    client = FakeAnthropic([RuntimeError("overloaded")])

    result = _run(client)

    assert isinstance(result, NothingWritten)
    assert "guideline resolution failed" in result.reason


def test_a_listed_type_whose_template_will_not_load_refuses():
    """The catalogue is built from row NAMES, so a type can be listed and its
    text still be unreadable a moment later (retired between the two reads, a
    store that failed). Writing against a template that is not there would be
    writing against nothing, so the run refuses."""
    result = _execute_with(
        load_texts=lambda *_a: (None, None, None),
        client=FakeAnthropic([]),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, NothingWritten)
    assert "no template stored" in result.reason
    assert result.guideline_set == "kb-authoring"


def test_a_set_with_no_guidance_row_costs_a_note_not_the_run():
    """Missing set-wide guidance only costs the run context; the template is
    what it cannot do without."""
    result = _execute_with(
        load_texts=lambda *_a: (None, "EXPOSURE", "TEMPLATE"),
        client=FakeAnthropic([_emit(), _review_ok()]),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, DocumentWritten)
    assert "no set-wide guidance row for 'kb-authoring'" in result.trace["notes"]


def test_a_set_with_no_exposure_slot_is_conformance_checked_with_exposure_unchecked():
    """No exposure row removes that property from the model's wire contract;
    the harness records unchecked while still requiring conformance."""
    client = FakeAnthropic([_emit(), _review_ok(check_exposure=False)])
    result = _execute_with(
        load_texts=lambda *_a: ("GUIDANCE", None, "TEMPLATE"),
        client=client,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, DocumentWritten)
    schema = client.calls[1]["tools"][0]["input_schema"]
    assert set(schema["properties"]) == {"conformance"}
    assert schema["required"] == ["conformance"]
    assert result.review.exposure.status == "unchecked"
    assert (
        "guideline set 'kb-authoring' states no exposure rules" in result.trace["notes"]
    )


# --------------------------------------------------------------------------- #
# The guideline set and the doctrine reach the model
# --------------------------------------------------------------------------- #


def test_both_guideline_texts_are_injected_and_labelled(kb_set):
    client = FakeAnthropic([_emit(), _review_ok()])

    _run(client, guideline_set="kb-authoring", document_type="how-to")

    system = client.calls[0]["system"]
    assert "SET-WIDE GUIDANCE: source everything." in system
    assert "HOW-TO TEMPLATE: steps." in system
    assert "REFERENCE TEMPLATE: tables." not in system  # only the resolved type
    assert "kb-authoring/how-to (the template you are filling)" in system


def test_the_resolved_sets_exposure_text_reaches_the_writer(kb_set):
    """The writer receives the disclosure boundary for the resolved set,
    labelled as that set's exposure row rather than undifferentiated prose."""
    client = FakeAnthropic([_emit(), _review_ok()])

    _run(client, guideline_set="kb-authoring", document_type="how-to")

    system = client.calls[0]["system"]
    assert "--- kb-authoring/exposure ---" in system
    assert "EXPOSURE RULES: reveal only published behaviour." in system


def test_the_stored_doctrine_wins_over_the_packaged_file(kb_set):
    prompt_store.save(
        kb_set, type="doctrine", name="docgen", text="EDITED DOCTRINE ROW"
    )
    client = FakeAnthropic([_emit(), _review_ok()])

    _run(client, guideline_set="kb-authoring", document_type="how-to")

    system = client.calls[0]["system"]
    assert "EDITED DOCTRINE ROW" in system
    assert "GENERATION DOCTRINE" in system


def test_an_unreadable_doctrine_leaves_the_run_standing(kb_set, tmp_path):
    client = FakeAnthropic([_emit(), _review_ok()])

    result = _run(
        client,
        guideline_set="kb-authoring",
        document_type="how-to",
        config=_config(doctrine_path=str(tmp_path / "gone.md")),
    )

    assert isinstance(result, DocumentWritten)
    assert any("doctrine unreadable" in n for n in result.trace["notes"])
    assert "GENERATION DOCTRINE" not in client.calls[0]["system"]


def test_the_packaged_doctrine_is_what_a_fresh_instance_reads(kb_set):
    """No stored row: the file beside the package is the seed and the
    fallback, and it actually reaches the model."""
    client = FakeAnthropic([_emit(), _review_ok()])

    _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert "# Documentation generation doctrine" in client.calls[0]["system"]


# --------------------------------------------------------------------------- #
# Reads and recon
# --------------------------------------------------------------------------- #


def test_recon_runs_on_the_request_and_its_ids_count_as_retrieved(kb_set):
    substrate = _substrate()
    client = FakeAnthropic([_emit(), _review_ok()])

    result = _run(
        client,
        substrate=substrate,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert substrate.calls[0][0] == "survey_statements"
    assert substrate.calls[0][1]["query"] == "how do I configure single sign-on"
    # stm_1 came back from recon, so citing it is allowed with no further read.
    assert isinstance(result, DocumentWritten)
    assert result.trace["grounding"]["retrieved_ids"] == 1


def test_a_failing_read_is_reported_not_fabricated(kb_set):
    substrate = _substrate(
        survey_statements=[], get_statements=Exception("index timeout")
    )
    client = FakeAnthropic(
        [
            _message([_tool_use("get_statements", {"ids": ["stm_9"]})]),
            _emit(statement_ids=["stm_9"]),
            _emit(statement_ids=["stm_9"]),
            _emit(statement_ids=["stm_9"]),
            _emit(statement_ids=["stm_9"]),
        ]
    )

    result = _run(
        client,
        substrate=substrate,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    # The read failed, so nothing was retrieved and the citation cannot stand.
    assert isinstance(result, NothingWritten)
    assert "never retrieved" in result.reason
    failed = [c for c in result.trace["tool_calls"] if c["name"] == "get_statements"]
    assert failed[0]["ok"] is False


# --------------------------------------------------------------------------- #
# The emit contract
# --------------------------------------------------------------------------- #


def test_a_document_with_no_statement_ids_is_refused_and_asked_again(kb_set):
    client = FakeAnthropic(
        [_emit(statement_ids=[]), _emit(statement_ids=["stm_1"]), _review_ok()]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.statement_ids == ["stm_1"]
    blocked = client.calls[1]["messages"][-1]["content"][0]
    assert blocked["is_error"] is True
    assert "rests on nothing is not recorded" in blocked["content"]
    assert result.trace["refused_emits"] == [
        "it carried no statement_ids. A document that rests on nothing is not "
        "recorded — cite the statements each section came from"
    ]


def test_a_document_that_never_finds_its_ids_is_not_recorded(kb_set):
    client = FakeAnthropic([_emit(statement_ids=[])] * 5)

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, NothingWritten)
    assert "was not recorded" in result.reason
    assert len(result.trace["refused_emits"]) == 4


def test_citing_an_id_the_run_never_retrieved_is_refused(kb_set):
    """The structural half of "do not invent": provenance can only name
    statements this run actually read."""
    client = FakeAnthropic(
        [
            _emit(statement_ids=["stm_1", "stm_404"]),
            _emit(statement_ids=["stm_1"]),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.statement_ids == ["stm_1"]
    blocked = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "stm_404" in blocked
    assert "stm_1," not in blocked  # the retrieved one is not complained about


def test_a_link_target_is_not_a_retrieved_statement(kb_set):
    """A `to_id` in a link is a pointer to something the run has NOT read.
    Citing it without hydrating it is refused."""
    linked = {
        "id": "stm_1",
        "text": "a tenant can enable sso",
        "links": [{"link_type": "requires", "to_id": "stm_2"}],
    }
    client = FakeAnthropic([_emit(statement_ids=["stm_2"])] * 5)

    result = _run(
        client,
        substrate=_substrate(survey_statements=[linked]),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, NothingWritten)
    assert "stm_2" in result.reason


def test_an_id_truncated_out_of_the_tool_result_is_not_retrieved(kb_set):
    """A large read is truncated on its way into the conversation. An id past
    the cut never reached the model, so citing it is a guess — and the gate
    treats it as one."""
    bulk = [{"id": f"stm_{i}", "text": "x" * 6000} for i in range(1, 5)]
    bulk.append({"id": "stm_cut", "text": "past the 20k cap"})
    client = FakeAnthropic(
        [
            _message([_tool_use("search_statements", {"query": "sso"})]),
            _emit(statement_ids=["stm_1", "stm_cut"]),
            _emit(statement_ids=["stm_1"]),
            _review_ok(),
        ]
    )

    result = _run(
        client,
        substrate=_substrate(survey_statements=[], search_statements=bulk),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, DocumentWritten)
    assert result.statement_ids == ["stm_1"]
    assert "stm_cut" in result.trace["refused_emits"][0]


def test_an_id_cut_by_the_cap_is_not_rescued_by_a_longer_id_sharing_its_prefix(kb_set):
    """`stm_1` is a prefix of `stm_12`, and only `stm_12` survived the cap.

    Checking the cited id against the text of the result would let the longer
    id vouch for the shorter one the model never saw. Retrieval is an identity,
    so the gate asks whether `stm_1` was retrieved, not whether its characters
    appear somewhere.
    """
    bulk = [{"id": "stm_12", "text": "x" * 6000}]
    bulk += [{"id": f"stm_{i}", "text": "x" * 6000} for i in (20, 21, 22)]
    bulk.append({"id": "stm_1", "text": "past the 20k cap"})
    client = FakeAnthropic(
        [
            _message([_tool_use("search_statements", {"query": "sso"})]),
            _emit(statement_ids=["stm_12", "stm_1"]),
            _emit(statement_ids=["stm_12"]),
            _review_ok(),
        ]
    )

    result = _run(
        client,
        substrate=_substrate(survey_statements=[], search_statements=bulk),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    refusal = " ".join(result.trace["refused_emits"])
    assert "never retrieved: stm_1" in refusal
    assert "stm_12" not in refusal
    assert isinstance(result, DocumentWritten)
    assert result.statement_ids == ["stm_12"]


def test_a_blank_title_or_body_is_refused(kb_set):
    client = FakeAnthropic(
        [_emit(title="   "), _emit(body="  \n "), _emit(), _review_ok()]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.trace["refused_emits"] == ["the title is blank", "the body is blank"]


def test_a_malformed_emit_is_retried_once_then_refused(kb_set):
    client = FakeAnthropic([_emit(title=None), _emit(title=None)])

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, NothingWritten)
    assert "malformed" in result.reason


def test_the_slug_is_derived_from_the_title_not_chosen(kb_set):
    client = FakeAnthropic([_emit(title="Configuring Single Sign-On!"), _review_ok()])

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.slug == "configuring-single-sign-on"
    # The emit schema has no slug field at all — the model cannot name a page.
    emit_schema = next(t for t in client.calls[0]["tools"] if t["name"] == EMIT_TOOL)[
        "input_schema"
    ]
    assert set(emit_schema["properties"]) == {
        "title",
        "body",
        "statement_ids",
        "gaps",
    }


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Configuring SSO", "configuring-sso"),
        ("  Spaces   and --- dashes  ", "spaces-and-dashes"),
        ("under_scores", "under-scores"),
        ("!!!", ""),
    ],
)
def test_slug_derivation(title, expected):
    assert _slug(title) == expected


# --------------------------------------------------------------------------- #
# Knowledge gaps: what the substrate could not supply
# --------------------------------------------------------------------------- #


def test_a_missing_fact_is_filed_as_a_gap_and_the_run_continues(kb_set):
    reporter = FakeGapReporter()
    client = FakeAnthropic(
        [
            _message(
                [_tool_use(GAP_TOOL, {"text": "no statements on sso session TTL"})]
            ),
            _emit(gaps=["session TTL"]),
            _review_ok(),
        ]
    )

    result = _run(
        client,
        report_gap=reporter,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert reporter.filed == ["no statements on sso session TTL"]
    assert isinstance(result, DocumentWritten)
    assert result.gaps == ["no statements on sso session TTL", "session TTL"]
    # The two lists stay distinguishable on the trace: `reported_gaps` is what
    # actually reached a curator's queue, `declared_gaps` is the run's own
    # account. A gap the model only declared must never read as one it filed.
    assert result.trace["reported_gaps"] == [
        "gap_1 :: no statements on sso session TTL"
    ]
    assert result.trace["declared_gaps"] == ["session TTL"]
    # Not terminal: the gap's result went back as an ordinary tool_result.
    gap_result = client.calls[1]["messages"][-1]["content"][0]
    assert gap_result["is_error"] is False
    assert "gap_1" in gap_result["content"]


def test_a_gap_store_failure_does_not_take_the_run_down(kb_set):
    client = FakeAnthropic(
        [
            _message([_tool_use(GAP_TOOL, {"text": "missing"})]),
            _emit(),
            _review_ok(),
        ]
    )

    result = _run(
        client,
        report_gap=FakeGapReporter(fail=True),
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, DocumentWritten)
    reported = client.calls[1]["messages"][-1]["content"][0]
    assert reported["is_error"] is True
    assert "gap store is down" in reported["content"]


def test_an_empty_gap_report_is_rejected_without_reaching_the_store(kb_set):
    reporter = FakeGapReporter()
    client = FakeAnthropic(
        [
            _message([_tool_use(GAP_TOOL, {"text": "   "})]),
            _emit(),
            _review_ok(),
        ]
    )

    _run(
        client,
        report_gap=reporter,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert reporter.filed == []


# --------------------------------------------------------------------------- #
# Budgets and degradation
# --------------------------------------------------------------------------- #


def test_the_op_cap_forces_a_finalize_that_is_still_gated(kb_set):
    """A budget cap is a reason to stop gathering, never a reason to record a
    groundless page: the forced emit meets the same grounding check."""
    client = FakeAnthropic([_emit(statement_ids=[])])

    result = _run(
        client,
        guideline_set="kb-authoring",
        document_type="how-to",
        config=_config(op_cap=1),  # recon alone spends it
    )

    assert isinstance(result, NothingWritten)
    assert result.trace["forced_finalize"] == "op_cap"
    assert result.trace["degraded"] is True
    forced = client.calls[0]
    assert forced["tool_choice"]["name"] == EMIT_TOOL
    assert "thinking" not in forced


def test_a_forced_finalize_can_still_produce_a_grounded_document(kb_set):
    client = FakeAnthropic([_emit(), _review_ok()])

    result = _run(
        client,
        guideline_set="kb-authoring",
        document_type="how-to",
        config=_config(op_cap=1),
    )

    assert isinstance(result, DocumentWritten)
    assert result.trace["degraded"] is True
    assert result.statement_ids == ["stm_1"]


def test_a_text_only_turn_is_nudged_once_then_forced(kb_set):
    client = FakeAnthropic(
        [
            _message([_text("Here is the document:")], stop="end_turn"),
            _emit(),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert "You stopped without finishing" in client.calls[1]["messages"][-1]["content"]


def test_a_model_error_mid_run_degrades_rather_than_raising(kb_set):
    client = FakeAnthropic([RuntimeError("overloaded"), _emit(), _review_ok()])

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.trace["forced_finalize"] == "api_error"


# --------------------------------------------------------------------------- #
# Independent review
# --------------------------------------------------------------------------- #


def test_the_reviewer_never_receives_the_writers_reasoning(kb_set):
    """The isolation claim is pinned at the client boundary: writer-only
    reasoning reaches a later writer request and no part of the review call."""
    sentinel = "WRITER_PRIVATE_REASONING_7e3c"
    thinking = types.SimpleNamespace(
        type="thinking", thinking=sentinel, signature="test-signature"
    )
    client = FakeAnthropic(
        [
            _message(
                [
                    thinking,
                    _text(sentinel),
                    _tool_use("get_statements", {"ids": ["stm_1"]}, id="read-1"),
                ]
            ),
            _emit(),
            _review_ok(),
        ]
    )

    result = _run(
        client,
        guideline_set="kb-authoring",
        document_type="how-to",
        config=_config(thinking=True),
    )

    assert isinstance(result, DocumentWritten)
    writer_calls = client.calls[:2]
    reviewer_calls = client.calls[2:]
    assert sentinel in json.dumps(writer_calls, default=str)
    assert all(sentinel not in json.dumps(call, default=str) for call in reviewer_calls)
    assert len(reviewer_calls) == 1
    review_call = reviewer_calls[0]
    assert len(review_call["messages"]) == 1
    assert review_call["messages"][0]["role"] == "user"
    assert review_call["system"] != writer_calls[0]["system"]


def test_the_reviewer_is_given_the_document_the_exposure_text_and_the_template(
    kb_set,
):
    """The judging context receives its evidence and both judging rules, but
    not the production guidance that belongs only to the writer."""
    body = "# SSO\n\nA reader-visible finished body."
    client = FakeAnthropic([_emit(body=body), _review_ok()])

    _run(client, guideline_set="kb-authoring", document_type="how-to")

    review_call = client.calls[1]
    assert body in review_call["messages"][0]["content"]
    assert "EXPOSURE RULES: reveal only published behaviour." in review_call["system"]
    assert "HOW-TO TEMPLATE: steps." in review_call["system"]
    assert "SET-WIDE GUIDANCE: source everything." not in review_call["system"]


def test_the_reviewer_sees_the_statements_the_document_cited(kb_set):
    """The harness hydrates cited ids for review, so the reviewer can inspect
    the material behind a disclosure without inheriting the writer's reads."""
    cited = {"id": "stm_1", "kind": "capability", "text": "CITED SSO FACT"}
    uncited = {"id": "stm_2", "kind": "state", "text": "UNCITED OTHER FACT"}

    def get_statements(arguments):
        return [item for item in (cited, uncited) if item["id"] in arguments["ids"]]

    substrate = _substrate(
        survey_statements=[cited, uncited], get_statements=get_statements
    )
    client = FakeAnthropic([_emit(statement_ids=["stm_1"]), _review_ok()])

    result = _run(
        client,
        substrate=substrate,
        guideline_set="kb-authoring",
        document_type="how-to",
    )

    assert isinstance(result, DocumentWritten)
    review_request = json.dumps(client.calls[1], default=str)
    assert "CITED SSO FACT" in review_request
    assert "UNCITED OTHER FACT" not in review_request


def test_the_two_checks_are_reported_separately(kb_set):
    """An exposure failure does not blur into conformance; each verdict and
    its own findings remain independently visible in the review trace."""
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(
                check="exposure",
                where="Credentials",
                problem="reveals an internal token",
            ),
            _emit(),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    first = result.trace["reviews"][0]
    assert first["exposure"]["status"] == "fail"
    assert first["exposure"]["findings"][0]["problem"] == ("reveals an internal token")
    assert first["conformance"] == {"status": "pass", "findings": []}


def test_a_failed_review_returns_to_the_writer_exactly_once(kb_set):
    """One rejection creates one fresh writer request carrying the rejected
    body and actionable finding; a passing second review ends the exchange."""
    rejected_body = "# SSO\n\nRejected body version one."
    client = FakeAnthropic(
        [
            _emit(body=rejected_body),
            _review_fail(problem="add the missing verification step"),
            _emit(body="# SSO\n\nRevised body with verification."),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.review.attempts == 2
    retry = client.calls[2]
    assert len(retry["messages"]) == 1
    assert retry["messages"][0]["role"] == "user"
    retry_text = retry["messages"][0]["content"]
    assert "add the missing verification step" in retry_text
    assert rejected_body in retry_text
    assert "RECON (survey_statements" not in retry_text
    assert len(result.trace["reviews"]) == 2


def test_a_second_failed_review_finishes_the_run_with_the_findings(kb_set):
    """The one retry is a hard boundary: another rejection returns nothing,
    and its actionable text is preserved for the documentation run row."""
    problem = "the procedure still omits validation"
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(problem="add validation"),
            _emit(body="# SSO\n\nStill incomplete."),
            _review_fail(problem=problem),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, NothingWritten)
    assert result.review is not None
    assert result.review.passed is False
    assert result.review.attempts == 2
    assert problem in result.reason


def test_findings_make_a_check_fail_however_the_reviewer_labelled_it(kb_set):
    """Finding evidence wins over a contradictory pass label and sends the
    document back through the single writer retry."""
    problem = "the summary exposes an internal hostname"
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(
                check="exposure", status="pass", problem=problem, where="Summary"
            ),
            _emit(body="# SSO\n\nHostname removed."),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.trace["reviews"][0]["exposure"]["status"] == "fail"
    assert problem in client.calls[2]["messages"][0]["content"]


def test_a_reviewer_that_fails_a_check_without_saying_where_still_gives_the_writer_something(
    kb_set,
):
    """A bare fail is reconciled into a harness-authored finding, avoiding a
    content-free instruction to try the same document again."""
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(findings=[]),
            _emit(body="# SSO\n\nA second version."),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    retry_text = client.calls[2]["messages"][0]["content"]
    assert "without naming a problem" in retry_text
    first_finding = result.trace["reviews"][0]["conformance"]["findings"][0]
    assert first_finding["where"] == "the document (no location supplied)"


@pytest.mark.parametrize(
    "blank",
    [
        {"where": "", "problem": ""},
        {"where": "   ", "problem": "\t\n "},
        {"where": "Summary", "problem": "   "},
        {"where": " ", "problem": "the summary exposes a hostname"},
    ],
    ids=["empty", "whitespace", "blank-problem", "blank-where"],
)
def test_a_finding_that_names_nothing_is_treated_as_a_bare_fail(kb_set, blank):
    """A finding whose text is blank is evidence of nothing.

    Rendered, it becomes `conformance:  — ` on the run row and `-  — ` in the
    retry: exactly the content-free verdict the bare-`fail` branch already
    refuses to pass on. So it is reconciled the same way.
    """
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(findings=[blank]),
            _emit(body="# SSO\n\nA second version."),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    retry_text = client.calls[2]["messages"][0]["content"]
    assert "without naming a problem" in retry_text
    assert " — \n" not in retry_text and not retry_text.endswith(" — ")
    findings = result.trace["reviews"][0]["conformance"]["findings"]
    assert [
        f for f in findings if not f["where"].strip() or not f["problem"].strip()
    ] == []


def test_a_finding_rejects_the_document_whatever_the_label_says(kb_set):
    """A reviewer that reasons in the findings list throws the document away.

    The label is not the verdict: a check carrying real findings fails even when
    the reviewer marked it a pass. That coupling is what the review protocol
    warns about, so it is pinned here. A reviewer noting what it examined and
    accepted spends the run exactly as a real defect would.
    """
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(
                status="pass",
                findings=[
                    {
                        "where": "SCIM deprovisioning",
                        "problem": "The document abstracts this correctly. No finding on this point.",
                    }
                ],
            ),
            _emit(),
            _review_fail(
                status="pass",
                findings=[
                    {
                        "where": "SCIM deprovisioning",
                        "problem": "The document abstracts this correctly. No finding on this point.",
                    }
                ],
            ),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, NothingWritten)
    assert result.review.conformance.status == "fail"
    # The retry fired and the second review rejected too, so this covers the
    # path that actually spends the run rather than a first-round refusal.
    assert result.review.attempts == 2


def test_a_pass_carrying_only_blank_findings_stays_a_pass(kb_set):
    """Blank findings are not evidence, so they cannot flip a pass to a fail
    the way real findings do."""
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(status="pass", findings=[{"where": "", "problem": ""}]),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert result.review.conformance.status == "pass"
    assert result.review.conformance.findings == []


def test_a_review_that_cannot_be_run_records_no_document(kb_set):
    """A reviewer API failure closes the registry gate; grounded writer text
    cannot escape as DocumentWritten without an independent verdict."""
    client = FakeAnthropic([_emit(), RuntimeError("review service unavailable")])

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, NothingWritten)
    assert result.review is None
    assert "could not be reviewed" in result.reason
    assert "review service unavailable" in result.reason


def test_the_trace_records_every_review(kb_set):
    """Each gate invocation has an ordered trace entry with its attempt,
    separate checks, findings, and combined verdict."""
    client = FakeAnthropic(
        [
            _emit(),
            _review_fail(problem="missing prerequisite"),
            _emit(body="# SSO\n\nPrerequisite added."),
            _review_ok(),
        ]
    )

    result = _run(client, guideline_set="kb-authoring", document_type="how-to")

    assert isinstance(result, DocumentWritten)
    assert [review["attempt"] for review in result.trace["reviews"]] == [1, 2]
    assert result.trace["reviews"][0]["passed"] is False
    assert result.trace["reviews"][1] == {
        "attempt": 2,
        "exposure": {"status": "pass", "findings": []},
        "conformance": {"status": "pass", "findings": []},
        "passed": True,
    }


# --------------------------------------------------------------------------- #
# The trace
# --------------------------------------------------------------------------- #


def test_the_trace_records_what_the_run_resolved_and_grounded(kb_set):
    client = FakeAnthropic([_resolve(), _emit(), _review_ok()])

    result = _run(client)

    trace = result.trace
    assert trace["outcome"] == "document_written"
    assert trace["requested_set"] is None
    assert trace["guideline_set"] == "kb-authoring"
    assert trace["document_type"] == "how-to"
    assert trace["resolution_reason"] == "the request asks how to do something"
    assert trace["grounding"] == {
        "successful_reads": 1,
        "retrieved_ids": 1,
        "cited_ids": 1,
        "gaps_filed": 0,
    }
    assert trace["model_turns"] == 3
    assert trace["tokens"]["total"] == 45
