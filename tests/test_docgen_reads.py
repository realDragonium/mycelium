"""The reads only a documentation run has: a flow preview and the opening
brief's context for one concept, both inside the run's audience."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pytest

from mycelium import audience_scope, docs_store, drafts_store, store
from mycelium.ask.substrate import InProcessSubstrate
from mycelium.audiences import Audience
from mycelium.docgen import flows, loop, prompts, reads
from mycelium.docgen.config import DocgenConfig
from mycelium.docgen.tools import PREVIEW_TOOL, READ_TOOLS, build_tools
from mycelium.docgen.trace import TraceBuilder

INTERNAL = Audience("internal-technical", "Internal technical", "internal", "All.", 1)
EXTERNAL = Audience(
    "external-technical", "External technical", "external", "Integrators.", 1
)


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    store.use_substrate_connection(conn)
    try:
        yield conn
    finally:
        store.reset_substrate()
        conn.close()


@dataclass(frozen=True)
class Corpus:
    export: str
    csv: str
    invoice: str
    audit: str
    requested: str
    queued: str
    ready: str
    failed: str
    expired: str
    sso: str
    retention: str


def _corpus(conn) -> Corpus:
    """A workspace export: requested, queued, then ready when single sign-on
    is enforced, or failed. Only internal readers see the failure and the
    retention rule that gates the link's expiry."""
    export = store.create_entity(conn, "A download of a workspace's data.")
    store.create_name(conn, "workspace export", export)
    csv = store.create_entity(conn, "The export as comma-separated rows.")
    store.create_name(conn, "csv export", csv)
    invoice = store.create_entity(conn, "A bill sent to a customer.")
    store.create_name(conn, "invoice", invoice)
    audit = store.create_entity(conn, "The record of who did what.")
    store.create_name(conn, "audit log", audit)
    store.insert_entity_links(
        conn, [(export, csv, "contains"), (export, audit, "uses")]
    )

    texts: dict[str, str] = {}

    def statement(kind: str, text: str, *, public: bool = True) -> str:
        statement_id = store.create_statement(conn, kind, text)
        texts[statement_id] = text
        if public:
            store.audience_labels.set_label(
                conn, statement_id, [INTERNAL.id, EXTERNAL.id], source="ai", reason="r"
            )
        return statement_id

    requested = statement("event", "A member requests a workspace export.")
    queued = statement("event", "The workspace export is queued.")
    ready = statement("event", "The workspace export is ready with every invoice.")
    failed = statement("event", "The workspace export fails on worker b.", public=False)
    expired = statement("event", "The download link of the workspace export expires.")
    sso = statement("state", "Single sign-on is enforced.")
    retention = statement("state", "Retention is set to seven days.", public=False)
    statement("state", "A csv export holds one row per invoice.")
    statement("event", "The audit log records each workspace export.")

    index = store.build_name_index(conn)
    for statement_id, text in texts.items():
        store.derive_mentions(conn, statement_id, text, index)
    store.insert_links(
        conn,
        [
            (requested, queued, "proceeds", None),
            (queued, ready, "proceeds", {"statement_id": sso}),
            (queued, failed, "on-failure", None),
            (ready, expired, "proceeds", {"statement_id": retention}),
        ],
    )
    conn.commit()
    return Corpus(
        export=export,
        csv=csv,
        invoice=invoice,
        audit=audit,
        requested=requested,
        queued=queued,
        ready=ready,
        failed=failed,
        expired=expired,
        sso=sso,
        retention=retention,
    )


def _substrate() -> reads.DocumentationSubstrate:
    return reads.DocumentationSubstrate(InProcessSubstrate())


def _context(audience: Audience) -> loop._RunContext:
    config = DocgenConfig.from_env()
    scoped = audience_scope.scoped(_substrate(), audience)
    return loop._RunContext(
        prompt="Explain workspace exports",
        client=None,
        substrate=scoped,
        report_gap=lambda text: {},
        config=config,
        trace=TraceBuilder(
            model=config.model,
            op_cap=config.limits.op_cap,
            wall_clock_s=config.limits.wall_clock_s,
        ),
        start=time.monotonic(),
        review_instructions="",
        visible_ids=scoped.scope.statement_ids,
        audience=audience,
    )


def _preview(ctx: loop._RunContext, **arguments) -> dict:
    loop._dispatch_read(PREVIEW_TOOL, arguments, "tu", ctx)
    result = ctx.messages[-1]["content"][0]
    assert not result["is_error"], result["content"]
    return json.loads(result["content"])


def test_a_preview_returns_the_drawing_and_makes_its_statements_citable(db):
    corpus = _corpus(db)
    ctx = _context(INTERNAL)

    drawing = _preview(ctx, start=corpus.requested)

    assert [(s["step"], s["id"]) for s in drawing["steps"]] == [
        (1, corpus.requested),
        (2, corpus.queued),
        (3, corpus.ready),
        (4, corpus.expired),
    ]
    assert drawing["steps"][0]["text"] == "A member requests a workspace export."
    assert drawing["steps"][0]["arrows"] == [{"to": 2}]
    assert drawing["steps"][1]["arrows"] == [
        {"to": 3, "label": f'then, when "{corpus.sso}"'}
    ]
    assert drawing["steps"][1]["outcomes"] == [
        {
            "id": corpus.failed,
            "kind": "event",
            "text": "The workspace export fails on worker b.",
            "label": "on failure",
        }
    ]
    assert {"id": corpus.sso, "text": "Single sign-on is enforced."} in drawing[
        "conditions"
    ]
    assert drawing["truncated"] is False
    assert "missing" not in drawing
    cited = [corpus.expired, corpus.failed, corpus.sso, corpus.retention]
    assert set(cited) <= ctx.retrieved_ids
    assert (
        loop._emit_problem(
            "Exports", "Body.", cited, ctx.retrieved_ids, ctx.visible_ids
        )
        is None
    )


def test_a_preview_stops_at_a_stop_and_reports_a_limit(db):
    corpus = _corpus(db)
    previous = corpus.expired
    for number in range(flows.MAX_STEPS):
        following = store.create_statement(db, "event", f"Reminder {number} is sent.")
        store.insert_links(db, [(previous, following, "proceeds", None)])
        previous = following
    db.commit()
    ctx = _context(INTERNAL)

    stopped = _preview(ctx, start=corpus.requested, stop=[corpus.ready])
    assert corpus.expired not in {step["id"] for step in stopped["steps"]}
    assert stopped["truncated"] is False

    cut = _preview(ctx, start=corpus.requested)
    assert len(cut["steps"]) == flows.MAX_STEPS
    assert cut["truncated"] is True
    assert cut["steps"][-1]["continues"] is True
    assert len(json.dumps(cut)) < 5000


def test_a_preview_shows_an_audience_only_what_it_may_see(db):
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)

    drawing = _preview(ctx, start=corpus.requested, stop=[corpus.failed])

    # The failure is internal, and so is the condition on the link to the
    # expiry: neither the statements nor that link exist for this audience.
    assert [step["id"] for step in drawing["steps"]] == [
        corpus.requested,
        corpus.queued,
        corpus.ready,
    ]
    assert drawing["missing"] == [corpus.failed]
    assert "arrows" not in drawing["steps"][2]
    for hidden in (corpus.failed, corpus.retention, corpus.expired):
        assert hidden not in ctx.retrieved_ids

    assert _preview(ctx, start=corpus.failed) == {
        "start": corpus.failed,
        "missing": [corpus.failed],
    }
    assert _preview(ctx, start="stm_absent")["missing"] == ["stm_absent"]


def test_a_malformed_preview_is_an_error_not_a_drawing(db):
    _corpus(db)
    ctx = _context(INTERNAL)

    loop._dispatch_read(PREVIEW_TOOL, {"stop": "stm_1"}, "tu", ctx)

    assert ctx.messages[-1]["content"][0]["is_error"] is True
    assert ctx.retrieved_ids == set()


def test_the_harness_draws_the_same_flow_inside_the_audience(db):
    corpus = _corpus(db)
    scoped = audience_scope.scoped(_substrate(), EXTERNAL)

    raw = scoped.call(
        reads.DRAW_CALL, {"start": corpus.requested, "stop": [corpus.failed]}
    )

    drawn = reads.DrawnFlow.model_validate(raw)
    assert drawn.drawing is not None
    assert drawn.drawing.statement_ids == [
        corpus.requested,
        corpus.queued,
        corpus.ready,
        corpus.sso,
    ]
    assert drawn.missing == [corpus.failed]
    assert scoped.call(reads.DRAW_CALL, {"start": corpus.failed}) == {
        "drawing": None,
        "missing": [corpus.failed],
    }


def test_the_preview_is_offered_to_documentation_and_not_to_ask():
    from mycelium import server

    discovered = {spec.name for spec in InProcessSubstrate(server).tool_specs()}
    offered = {tool["name"] for tool in build_tools(_substrate().tool_specs())}

    assert PREVIEW_TOOL in READ_TOOLS
    assert PREVIEW_TOOL in offered
    assert PREVIEW_TOOL not in discovered
    assert not {reads.DRAW_CALL, reads.CONTEXT_CALL} & offered


def test_the_brief_for_a_concept_says_where_flows_start_and_what_surrounds_it(db):
    corpus = _corpus(db)
    ctx = _context(INTERNAL)

    anchor = loop._read_anchor(ctx, corpus.export)

    assert anchor is not None and anchor.context is not None
    context = anchor.context
    assert [(s.statement_id, s.size) for s in context.flow_starts] == [
        (corpus.requested, 5)
    ]
    assert [(c.entity_id, c.link_type, c.direction) for c in context.related] == [
        (corpus.audit, "uses", "outgoing")
    ]
    assert [(c.entity_id, c.statements) for c in context.more_specific] == [
        (corpus.csv, 1)
    ]
    assert {(c.entity_id, c.statements) for c in context.named_together} == {
        (corpus.audit, 1),
        (corpus.invoice, 1),
    }
    brief = prompts.format_anchor(anchor)
    assert (
        f"- {corpus.requested} [event] A member requests a workspace export. "
        "(5 statements)"
    ) in brief
    assert f'- this concept uses "audit log" ({corpus.audit})' in brief
    assert f'- "csv export" ({corpus.csv}): 1' in brief
    assert f'- "invoice" ({corpus.invoice}): 1' in brief
    for heading in (
        "WHERE FLOWS START",
        "RELATED CONCEPTS",
        "MORE SPECIFIC CONCEPTS",
        "OFTEN NAMED TOGETHER",
    ):
        assert heading in brief


def test_the_brief_for_an_external_audience_withholds_the_hierarchy(db):
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)

    anchor = loop._read_anchor(ctx, corpus.export)

    assert anchor is not None and anchor.context is not None
    context = anchor.context
    assert [(s.statement_id, s.size) for s in context.flow_starts] == [
        (corpus.requested, 3)
    ]
    assert context.related == [] and context.more_specific == []
    assert {c.entity_id for c in context.named_together} == {
        corpus.audit,
        corpus.invoice,
    }
    brief = prompts.format_anchor(anchor)
    assert "WHERE FLOWS START" in brief and "OFTEN NAMED TOGETHER" in brief
    assert "RELATED CONCEPTS" not in brief
    assert "MORE SPECIFIC CONCEPTS" not in brief
    assert "worker b" not in brief


@pytest.fixture
def documents(tmp_path):
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    drafts_store.use_connection(conn)
    try:
        yield conn
    finally:
        drafts_store.reset()
        conn.close()


def _page(
    documents, entity_id: str, title: str, body: str, cited: list[str], **identity
) -> str:
    identity = {"guideline_set": "developer-reference", **identity}
    return docs_store.upsert_document(
        documents,
        slug=title.lower().replace(" ", "-"),
        title=title,
        body=body,
        document_type="entity-page",
        statement_ids=cited,
        anchor_entity_id=entity_id,
        **identity,
    )


def _profiled(audience: Audience) -> loop._RunContext:
    ctx = _context(audience)
    ctx.guideline_set, ctx.document_type = "developer-reference", "entity-page"
    return ctx


def test_the_brief_lists_pages_that_exist_for_the_surrounding_concepts(db, documents):
    corpus = _corpus(db)
    long_lead = " ".join(f"word{number}" for number in range(70))
    _page(
        documents,
        corpus.audit,
        "Audit log",
        "The [[audit log]] records who did what.\n\nMore.\n\n## Details\n\nText.\n",
        [corpus.requested],
    )
    _page(documents, corpus.csv, "CSV export", long_lead + "\n", [corpus.queued])
    # Another profile's page about a surrounding concept is not this one's.
    _page(
        documents,
        corpus.invoice,
        "Invoice",
        "A bill.\n",
        [corpus.ready],
        guideline_set="help-centre",
    )

    anchor = loop._read_anchor(_profiled(INTERNAL), corpus.export)

    assert anchor is not None
    assert [(page.entity_id, page.name, page.title) for page in anchor.pages] == [
        (corpus.audit, "audit log", "Audit log"),
        (corpus.csv, "csv export", "CSV export"),
    ]
    assert anchor.pages[0].lead == "The audit log records who did what."
    assert anchor.pages[1].lead.split() == [
        *(f"word{number}" for number in range(59)),
        "word59…",
    ]
    brief = prompts.format_anchor(anchor)
    assert "PAGES THAT EXIST" in brief
    assert '- "audit log": "Audit log" — The audit log records who did what.' in brief
    assert "Invoice" not in brief.split("PAGES THAT EXIST")[1].split("\n\n")[0]


def test_a_page_resting_on_what_the_audience_may_not_see_is_not_listed(db, documents):
    corpus = _corpus(db)
    _page(documents, corpus.audit, "Audit log", "Open.\n", [corpus.requested])
    _page(
        documents,
        corpus.invoice,
        "Invoice",
        "Worker b fails some exports.\n",
        [corpus.ready, corpus.failed],
    )

    external = loop._read_anchor(_profiled(EXTERNAL), corpus.export)
    internal = loop._read_anchor(_profiled(INTERNAL), corpus.export)

    assert external is not None and internal is not None
    assert [page.title for page in external.pages] == ["Audit log"]
    assert "Worker b" not in prompts.format_anchor(external)
    assert {page.title for page in internal.pages} == {"Audit log", "Invoice"}


def test_the_list_of_existing_pages_is_bounded(db, documents, monkeypatch):
    corpus = _corpus(db)
    _page(documents, corpus.audit, "Audit log", "Open.\n", [corpus.requested])
    _page(documents, corpus.csv, "CSV export", "Rows.\n", [corpus.queued])
    monkeypatch.setattr(loop, "_MAX_EXISTING_PAGES", 1)

    anchor = loop._read_anchor(_profiled(INTERNAL), corpus.export)

    assert anchor is not None
    assert [page.title for page in anchor.pages] == ["Audit log"]


def test_the_brief_names_the_preferred_name_and_lists_no_pages_without_any(db):
    corpus = _corpus(db)
    store.create_name(db, "data export", corpus.export)
    db.commit()

    anchor = loop._read_anchor(_profiled(INTERNAL), corpus.export)

    assert anchor is not None and anchor.pages == []
    brief = prompts.format_anchor(anchor)
    assert '"workspace export" is its preferred name' in brief
    assert "Call every concept by its preferred name throughout" in brief
    assert "Do not list this concept's other names: the page shows them" in brief
    assert "PAGES THAT EXIST" not in brief


def test_flow_starts_cover_statements_beyond_the_listed_page_and_stay_bounded(
    db, monkeypatch
):
    corpus = _corpus(db)
    index = store.build_name_index(db)
    for number in range(reads.MAX_FLOW_STARTS + 2):
        text = f"Workspace export reminder {number} is scheduled."
        first = store.create_statement(db, "event", text)
        store.derive_mentions(db, first, text, index)
        second = store.create_statement(db, "event", f"Reminder {number} is sent.")
        store.insert_links(db, [(first, second, "proceeds", None)])
    db.commit()
    monkeypatch.setattr(loop, "_MAX_ANCHOR_STATEMENTS", 2)
    monkeypatch.setattr(loop, "_ANCHOR_PAGE", 2)
    monkeypatch.setattr(reads, "MAX_NAMED_TOGETHER", 1)
    ctx = _context(INTERNAL)

    anchor = loop._read_anchor(ctx, corpus.export)

    assert anchor is not None and anchor.context is not None
    assert len(anchor.statements) == 2
    starts = anchor.context.flow_starts
    assert len(starts) == reads.MAX_FLOW_STARTS
    assert (starts[0].statement_id, starts[0].size) == (corpus.requested, 5)
    assert {start.size for start in starts[1:]} == {2}
    assert len(anchor.context.named_together) == 1
    # Shown with its text in the brief, so citable although never listed.
    assert starts[1].statement_id not in {row["id"] for row in anchor.statements}
    assert starts[1].statement_id in ctx.retrieved_ids


def test_coverage_defers_to_a_template_that_asks_for_a_summary():
    brief = prompts.format_anchor(
        prompts.Anchor(
            entity_id="ent_export",
            names=["workspace export"],
            description="",
            statements=[{"id": "stm_1", "kind": "event", "text": "An export runs."}],
            total=1,
        )
    )

    assert (
        "each belongs in the document unless it is off-topic for what the "
        "request asks or the template asks for a summary; leave one out "
        "deliberately, never by not getting to it."
    ) in brief
    assert "WHERE FLOWS START" not in brief
