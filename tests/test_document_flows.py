"""Concept links and flows in a document: what a submission may carry, what is
drawn and resolved inside its audience, and what the reviewer and a revising
writer are shown."""

from __future__ import annotations

import dataclasses

import pytest

from mycelium import docs_store, store
from mycelium.ask.substrate import SubstrateError
from mycelium.docgen import flows, loop, prompts, schema
from mycelium.docgen.schema import FlowDefinition, StoredFlow
from mycelium.docgen.tools import parse_emit_flows
from test_docgen_reads import (  # noqa: F401 — `db` is a fixture
    EXTERNAL,
    INTERNAL,
    _context,
    _corpus,
    db,
)

NAME = "request-to-download"
BODY = f"A member asks for the file.\n\n```flow\n{NAME}\n```\n"


def _flow(start: str, name: str = NAME, stop: tuple[str, ...] = ()) -> FlowDefinition:
    return FlowDefinition(
        name=name, title="From request to download", start=start, stop=list(stop)
    )


def _stored(db, corpus) -> StoredFlow:  # noqa: F811
    problem, [stored] = loop._submission_problem(
        _context(INTERNAL), "Exports", BODY, [corpus.queued], [_flow(corpus.requested)]
    )
    assert problem is None
    return stored


class _Unreadable:
    def has(self, name: str) -> bool:
        return True

    def call(self, name: str, arguments: dict) -> object:
        raise SubstrateError(f"{name} must not run for a plain document")


def test_a_submitted_flow_is_drawn_inside_the_audience_and_its_statements_cited(db):  # noqa: F811
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)

    # Nothing was read before: drawing the flow is what makes `queued` citable.
    problem, drawn = loop._submission_problem(
        ctx, "Exports", BODY, [corpus.queued], [_flow(corpus.requested)]
    )

    assert problem is None
    [stored] = drawn
    assert (stored.name, stored.title, stored.start, stored.stop) == (
        NAME,
        "From request to download",
        corpus.requested,
        [],
    )
    # The failure and the retention condition are internal.
    assert stored.drawing.statement_ids == [
        corpus.requested,
        corpus.queued,
        corpus.ready,
        corpus.sso,
    ]
    assert loop._with_flow_statements([corpus.queued], drawn) == [
        corpus.queued,
        corpus.requested,
        corpus.ready,
        corpus.sso,
    ]
    internal = _stored(db, corpus)
    assert corpus.failed in internal.drawing.statement_ids


def test_every_problem_with_the_flows_comes_back_in_one_refusal(db):  # noqa: F811
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)
    ctx.retrieved_ids.add(corpus.queued)
    body = BODY + "\n```flow\nrenewal\n```\n\n```flow\ntwice\n```\n"

    problem, drawn = loop._submission_problem(
        ctx,
        "Exports",
        body,
        [corpus.queued],
        [
            _flow(corpus.requested, stop=(corpus.failed, "stm_absent")),
            _flow(corpus.failed, name="hidden-start"),
            _flow(corpus.ready, name="Too_Short"),
            _flow(corpus.requested, name="twice"),
            _flow(corpus.queued, name="twice"),
        ],
    )

    assert drawn == []
    assert problem is not None
    for reason in (
        "the body places a flow 'renewal' that `flows` does not hold",
        "flow 'twice' is submitted 2 times",
        f"flow '{NAME}' has a stop, {corpus.failed}, that does not exist or that "
        "this document's audience may not see",
        f"flow '{NAME}' has a stop, stm_absent, that does not exist",
        f"flow 'hidden-start' has a start, {corpus.failed}, that does not exist",
        "flow 'hidden-start' is never placed in the body",
        "flow 'Too_Short' has a name that is not lowercase letters, digits and",
        "flow 'Too_Short' draws fewer than 3 statements (1)",
    ):
        assert reason in problem
    assert problem.count("its flows cannot be stored") == 1
    assert corpus.failed not in ctx.retrieved_ids


def test_a_document_without_flows_or_links_reads_nothing_more(db):  # noqa: F811
    corpus = _corpus(db)
    ctx = dataclasses.replace(_context(INTERNAL), substrate=_Unreadable())
    ctx.retrieved_ids.add(corpus.queued)
    body = "Exports arrive as `[[rows]]`.\n\n```python\nflow\n```\n"

    assert loop._submission_problem(ctx, "Exports", body, [corpus.queued], []) == (
        None,
        [],
    )
    assert loop._resolve_links(ctx, body) == ([], [])
    assert parse_emit_flows({"title": "Exports", "body": body}) == []
    assert ctx.trace.notes == []


def test_a_malformed_flows_value_is_a_malformed_submission():
    with pytest.raises(ValueError):
        parse_emit_flows({"flows": [{"name": "a", "title": "A", "start": 7}]})


def test_concept_links_resolve_ignoring_case_inside_the_audience(db):  # noqa: F811
    corpus = _corpus(db)
    worker = store.create_entity(db, "A machine that builds exports.")
    store.create_name(db, "worker b", worker)
    store.derive_mentions(
        db,
        corpus.failed,
        "The workspace export fails on worker b.",
        store.build_name_index(db),
    )
    db.commit()
    body = (
        "A [[Workspace Export]] holds every [[invoice|bill]] as a "
        "[[CSV export]], built on [[Worker B]]; see [[Billing run]]."
    )

    internal = _context(INTERNAL)
    links, unmatched = loop._resolve_links(internal, body)
    assert [(link.name, link.entity_id) for link in links] == [
        ("Workspace Export", corpus.export),
        ("invoice", corpus.invoice),
        ("CSV export", corpus.csv),
        ("Worker B", worker),
    ]
    assert unmatched == ["Billing run"]
    assert internal.trace.notes == [
        "concept links that match no concept, or more than one, and read as "
        "plain text: [[Billing run]]"
    ]
    assert internal.trace.unmatched_links == ["Billing run"]

    # Only an internal statement names the worker, so the external audience
    # has no such concept.
    external = _context(EXTERNAL)
    links, unmatched = loop._resolve_links(external, body)
    assert worker not in {link.entity_id for link in links}
    assert unmatched == ["Worker B", "Billing run"]


def test_the_reviewer_is_told_what_each_placed_flow_shows(db):  # noqa: F811
    corpus = _corpus(db)
    stored = _stored(db, corpus)

    message = prompts.review_message(
        prompt="Explain workspace exports",
        title="Exports",
        body=BODY,
        statements=None,
        placed_flows=[stored],
    )

    assert "PLACED FLOWS" in message
    assert f'- `{NAME}`: "From request to download"' in message
    assert "  1. A member requests a workspace export. (event)" in message
    assert '     -> step 3: then, when "Single sign-on is enforced."' in message
    shown = message[message.index("PLACED FLOWS") :]
    assert "stm_" not in shown
    plain = prompts.review_message(
        prompt="p", title="Exports", body="Body.", statements=None
    )
    assert "PLACED FLOWS" not in plain
    system = prompts.build_review_system_prompt(
        guideline_set="developer-reference",
        document_type="entity-page",
        exposure=None,
        template="Template.",
    )
    assert "permitted body syntax, not placeholders" in system
    assert (
        "Fail CONFORMANCE for a flow that does not show what the surrounding "
        "text describes" in " ".join(system.split())
    )


def test_a_revision_brief_shows_the_current_flows_and_says_they_are_replaced(db):  # noqa: F811
    corpus = _corpus(db)
    stored = _stored(db, corpus)

    message = prompts.initial_user_message(
        "Tighten the lead",
        [],
        guideline_set="developer-reference",
        document_type="entity-page",
        current_document=BODY,
        current_flows=[stored],
    )

    assert "CURRENT FLOWS" in message
    assert "The `flows` you submit replace this set" in message
    assert (
        f'- {{"name": "{NAME}", "title": "From request to download", '
        f'"start": "{corpus.requested}", "stop": []}}'
    ) in message
    assert f"  1. [{corpus.requested}] A member requests a workspace export." in (
        message
    )
    first = prompts.initial_user_message(
        "Explain exports", [], guideline_set="s", document_type="t"
    )
    assert "CURRENT FLOWS" not in first


def test_a_vague_image_placeholder_is_refused_together_with_the_flows(db):  # noqa: F811
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)
    ctx.retrieved_ids.add(corpus.queued)
    body = (
        BODY
        + "\n![export dialog](image-wanted)\n\n"
        + "![The export dialog with CSV selected](image-wanted)\n"
    )

    problem, _drawn = loop._submission_problem(
        ctx, "Exports", body, [corpus.queued], [_flow(corpus.failed)]
    )

    assert problem is not None
    assert "its flows cannot be stored" in problem
    assert (
        "an image placeholder does not say what to show: ![export dialog](image-wanted)"
    ) in problem
    assert "CSV selected" not in problem
    assert "at least 3 words" in problem


def test_a_described_image_placeholder_is_neither_media_nor_refused(db):  # noqa: F811
    corpus = _corpus(db)
    ctx = _context(EXTERNAL)
    ctx.retrieved_ids.add(corpus.queued)
    body = "A member asks.\n\n![The export dialog with CSV selected](image-wanted)\n"

    assert loop._submission_problem(ctx, "Exports", body, [corpus.queued], []) == (
        None,
        [],
    )
    assert loop._media_problem(ctx, body) is None


def test_links_and_flows_are_stored_with_their_revision_and_not_carried_on(
    db,  # noqa: F811
    tmp_path,
):
    corpus = _corpus(db)
    stored = _stored(db, corpus)
    drafts = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(drafts)
    link = schema.StoredLink(name="Invoice", entity_id=corpus.invoice)

    document = docs_store.upsert_document(
        drafts,
        slug="exports",
        title="Exports",
        body=BODY,
        statement_ids=stored.drawing.statement_ids,
        concept_links=[link.model_dump()],
        flows=[stored.model_dump(mode="json")],
    )
    docs_store.upsert_document(
        drafts,
        slug="exports",
        title="Exports",
        body="Rewritten without either.",
        updates=document,
        replacing=docs_store.body_digest(BODY),
        expected_revision=1,
    )

    first = docs_store.get_revision(drafts, document, 1)
    assert schema.revision_flows(first) == [stored]
    assert schema.revision_links(first) == [link]
    assert schema.revision_flows(first)[0].drawing.link_set
    serialized = docs_store.serialize_revision(first)
    assert serialized["concept_links"] == [
        {"name": "Invoice", "entity_id": corpus.invoice}
    ]
    assert serialized["flows"][0]["name"] == NAME
    assert "flows" not in docs_store.serialize_revision(first, include_body=False)
    second = docs_store.get_revision(drafts, document, 2)
    assert schema.revision_flows(second) == [] == schema.revision_links(second)
    drafts.close()


def test_an_existing_database_gains_the_columns_and_its_revisions_read_empty(
    tmp_path,
):
    drafts = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(drafts)
    for column in ("concept_links", "flows"):
        drafts.execute(f"ALTER TABLE generated_document_revisions DROP COLUMN {column}")
    drafts.execute(
        "INSERT INTO generated_documents (id, slug, title, body, created_at, "
        "updated_at) VALUES ('gdc_old', 'sso', 'SSO', 'Old body', 't', 't')"
    )
    drafts.execute(
        "INSERT INTO generated_document_revisions (document_id, revision, slug, "
        "title, guideline_set, document_type, body, statement_ids, review, "
        "created_at) VALUES ('gdc_old', 1, 'sso', 'SSO', '', '', 'Old body', "
        "'[]', '{}', 't')"
    )
    drafts.commit()

    docs_store.migrate(drafts)

    row = docs_store.get_revision(drafts, "gdc_old", 1)
    assert row["body"] == "Old body"
    assert schema.revision_flows(row) == [] == schema.revision_links(row)
    assert docs_store.links_and_flows(row) == {"concept_links": [], "flows": []}
    drafts.close()


def test_a_drawing_survives_storage_unchanged(db):  # noqa: F811
    corpus = _corpus(db)
    stored = _stored(db, corpus)

    again = StoredFlow.model_validate_json(stored.model_dump_json())

    assert flows.flow_lines(again.drawing) == flows.flow_lines(stored.drawing)
