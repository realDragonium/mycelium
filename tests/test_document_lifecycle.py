"""A generated document after it leaves Mycelium: its identity, its pull
request, and the text people edit at the destination."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from mycelium import doc_runs, docs_store
from mycelium.docgen import publication
from mycelium.docgen.schema import CurrentDocument, RevisionTarget
from product_settings_helpers import import_product_environment

TARGET = json.dumps(
    {"host": "github.com", "owner": "acme", "repo": "handbook", "base_branch": "main"}
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(connection)
    yield connection
    connection.close()


def _document(
    conn: sqlite3.Connection,
    *,
    slug: str = "sso",
    anchor: str | None = None,
    body: str = "# SSO\n",
) -> str:
    return docs_store.upsert_document(
        conn,
        slug=slug,
        title="SSO",
        body=body,
        guideline_set="kb",
        document_type="how-to",
        statement_ids=["stm_1"],
        anchor_entity_id=anchor,
    )


def _deliver(
    conn: sqlite3.Connection, document_id: str, *, number: int | None = 17
) -> None:
    docs_store.record_delivery(
        conn,
        document_id,
        destination="docs",
        target=TARGET,
        path="docs/sso.md",
        reference=f"https://github.com/acme/handbook/pull/{number or 1}",
        content_revision="a" * 40,
        revision=int(docs_store.get_document(conn, document_id)["current_revision"]),
        pull_request_number=number,
    )


def _serialized(conn: sqlite3.Connection, document_id: str) -> dict[str, object]:
    row = docs_store.get_document(conn, document_id)
    assert row is not None
    return docs_store.serialize_document(row)


# --- identity ---------------------------------------------------------------


def test_an_anchor_identifies_one_document_per_set_and_type(conn):
    document_id = _document(conn, anchor="ent_sso")

    found = docs_store.find_by_anchor(conn, "kb", "how-to", "ent_sso")

    assert found is not None and found["id"] == document_id
    assert docs_store.find_by_anchor(conn, "kb", "reference", "ent_sso") is None
    with pytest.raises(ValueError, match="already holds anchor 'ent_sso'"):
        _document(conn, slug="other", anchor="ent_sso")


def test_an_anchored_document_takes_a_free_slug_beside_a_same_titled_page(conn):
    unanchored = _document(conn)
    second = _document(conn, anchor="ent_okta", body="# Okta SSO\n")
    third = _document(conn, anchor="ent_entra", body="# Entra SSO\n")

    slugs = {
        document_id: docs_store.get_document(conn, document_id)["slug"]
        for document_id in (unanchored, second, third)
    }
    assert slugs == {unanchored: "sso", second: "sso-2", third: "sso-3"}
    assert docs_store.get_document(conn, unanchored)["body"] == "# SSO\n"


def test_an_unanchored_title_collision_is_still_refused(conn):
    _document(conn)

    with pytest.raises(ValueError, match="would replace a stored body"):
        _document(conn, body="# Different\n")


def test_merged_anchors_move_to_the_target_unless_it_holds_that_identity(conn):
    moving = _document(conn, slug="okta", anchor="ent_okta")
    conn.execute(
        "UPDATE generated_documents SET document_type = 'reference' WHERE id = ?",
        (moving,),
    )
    conn.commit()
    unanchored = _document(conn, slug="okta-how-to", anchor="ent_okta")
    held = _document(conn, slug="sso", anchor="ent_sso")

    docs_store.move_anchors(conn, "ent_okta", "ent_sso")

    anchors = {
        document_id: docs_store.get_document(conn, document_id)["anchor_entity_id"]
        for document_id in (moving, unanchored, held)
    }
    assert anchors == {moving: "ent_sso", unanchored: None, held: "ent_sso"}


# --- pull request tracking --------------------------------------------------


def test_delivery_records_an_open_pull_request(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)

    document = _serialized(conn, document_id)
    pull_request = document["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (17, "open")
    assert pull_request["url"] == "https://github.com/acme/handbook/pull/17"
    assert document["delivery_status"] == "published"


@pytest.mark.parametrize("state", ["merged", "closed"])
def test_a_finished_pull_request_shows_in_the_delivery_status(conn, state):
    document_id = _document(conn)
    _deliver(conn, document_id)

    docs_store.record_pull_request_state(conn, document_id, 17, state)

    assert _serialized(conn, document_id)["delivery_status"] == state


def test_a_newer_internal_revision_outranks_a_merged_pull_request(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)
    docs_store.record_pull_request_state(conn, document_id, 17, "merged")
    docs_store.upsert_document(
        conn,
        slug="sso",
        title="SSO",
        body="# SSO, revised\n",
        guideline_set="kb",
        document_type="how-to",
        updates=document_id,
        replacing=docs_store.body_digest("# SSO\n"),
        expected_revision=1,
    )

    document = _serialized(conn, document_id)
    assert document["delivery_status"] == "changes_pending"
    pull_request = document["pull_request"]
    assert isinstance(pull_request, dict) and pull_request["state"] == "merged"


def test_a_state_read_for_a_replaced_pull_request_is_discarded(conn):
    document_id = _document(conn)
    _deliver(conn, document_id, number=17)
    _deliver(conn, document_id, number=18)

    docs_store.record_pull_request_state(conn, document_id, 17, "merged")

    pull_request = _serialized(conn, document_id)["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (18, "open")


def test_a_delivery_that_does_not_report_its_number_keeps_the_same_pull_request(
    conn,
):
    """The server's own delivery path does not pass the number yet."""
    document_id = _document(conn)
    _deliver(conn, document_id, number=17)
    docs_store.record_delivery(
        conn,
        document_id,
        destination="docs",
        target=TARGET,
        path="docs/sso.md",
        reference="https://github.com/acme/handbook/pull/17",
        content_revision="b" * 40,
        revision=1,
    )

    pull_request = _serialized(conn, document_id)["pull_request"]
    assert isinstance(pull_request, dict) and pull_request["number"] == 17


def test_an_unknown_pull_request_state_is_refused(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)

    with pytest.raises(ValueError, match="invalid pull request state"):
        docs_store.record_pull_request_state(conn, document_id, 17, "draft")


def test_upgrade_reads_the_pull_request_number_back_from_the_review_url(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = docs_store.connect(path)
    docs_store.migrate(legacy)
    document_id = _document(legacy)
    _deliver(legacy, document_id, number=None)
    legacy.execute(
        "UPDATE generated_documents SET delivery_reference = ?",
        ("https://github.com/acme/handbook/pull/42",),
    )
    for column in (
        "pull_request_number",
        "pull_request_state",
        "pull_request_refreshed_at",
    ):
        legacy.execute(f"ALTER TABLE generated_documents DROP COLUMN {column}")
    legacy.commit()

    docs_store.migrate(legacy)

    pull_request = _serialized(legacy, document_id)["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (42, None)
    legacy.close()


# --- which text a revision starts from --------------------------------------


def _published(conn: sqlite3.Connection, body: str = "# SSO\n") -> sqlite3.Row:
    document_id = _document(conn, body=body)
    docs_store.record_delivery(
        conn,
        document_id,
        destination="docs",
        target=TARGET,
        path="docs/sso.md",
        reference="https://github.com/acme/handbook/pull/17",
        content_revision=_blob(body),
        revision=1,
        pull_request_number=17,
    )
    row = docs_store.get_document(conn, document_id)
    assert row is not None
    return row


def _revised_internally(conn: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    docs_store.upsert_document(
        conn,
        slug="sso",
        title="SSO",
        body="# SSO, revised here\n",
        guideline_set="kb",
        document_type="how-to",
        updates=row["id"],
        replacing=docs_store.body_digest(row["body"]),
        expected_revision=1,
    )
    revised = docs_store.get_document(conn, row["id"])
    assert revised is not None
    return revised


def _blob(body: str) -> str:
    encoded = body.encode("utf-8")
    return hashlib.sha1(
        f"blob {len(encoded)}\0".encode() + encoded, usedforsecurity=False
    ).hexdigest()


def _remote(body: str) -> CurrentDocument:
    return CurrentDocument(body=body, content_revision=_blob(body))


def _start(row, remote, published=frozenset(), **kwargs):
    return publication.revision_start(row, remote, published, **kwargs)


def test_an_untouched_published_copy_leaves_the_internal_head_as_the_start(conn):
    row = _revised_internally(conn, _published(conn))

    start = _start(row, _remote("# SSO\n"))

    assert start.base == "internal"
    assert start.current == CurrentDocument("# SSO, revised here\n", _blob("# SSO\n"))


def test_a_copy_edited_on_github_is_the_start_when_nothing_is_unpublished(conn):
    row = _published(conn)

    start = _start(row, _remote("# SSO, edited by a reviewer\n"))

    assert start.base == "destination"
    assert start.current == _remote("# SSO, edited by a reviewer\n")


def test_edits_on_both_sides_are_refused_with_the_ways_forward(conn):
    row = _revised_internally(conn, _published(conn))

    with pytest.raises(ValueError) as refusal:
        _start(row, _remote("# SSO, edited by a reviewer\n"))

    message = str(refusal.value)
    assert "edited on GitHub after revision 1 was published" in message
    assert "revision 2 here has not been published" in message
    assert "start_from_destination" in message
    assert "close pull request #17 without merging" in message


def test_starting_from_the_destination_is_an_explicit_way_past_the_refusal(conn):
    row = _revised_internally(conn, _published(conn))

    start = _start(
        row, _remote("# SSO, edited by a reviewer\n"), start_from_destination=True
    )

    assert start.base == "destination"


def test_an_earlier_published_text_is_not_mistaken_for_an_edit(conn):
    """After an unmerged close the base branch still holds an older version."""
    row = _revised_internally(conn, _published(conn, body="# SSO v2\n"))

    start = _start(row, _remote("# SSO v1\n"), frozenset({_blob("# SSO v1\n")}))

    assert start.base == "internal"
    assert start.current.content_revision == _blob("# SSO v1\n")


def test_a_copy_already_matching_the_head_needs_no_reconciling(conn):
    row = _revised_internally(conn, _published(conn))

    start = _start(row, _remote("# SSO, revised here\n"))

    assert start.base == "internal"


def test_an_absent_copy_keeps_the_internal_head_and_the_sync_point(conn):
    row = _revised_internally(conn, _published(conn))

    assert _start(row, None) == publication.RevisionStart(
        CurrentDocument("# SSO, revised here\n"), "internal"
    )
    with pytest.raises(ValueError, match="no published copy"):
        _start(row, None, start_from_destination=True)


# --- the whole loop against a fake GitHub -----------------------------------


class FakeGitHub:
    """Enough of GitHub's Git Data, contents and pulls APIs to hold state.

    Trees are path-to-text maps, so a commit's file is a lookup. Nothing here
    reaches the network: `handle` is an httpx MockTransport handler.
    """

    def __init__(self) -> None:
        root_tree, root_commit = "e" * 40, "f" * 40
        self.trees: dict[str, dict[str, str]] = {root_tree: {}}
        self.commits: dict[str, str] = {root_commit: root_tree}
        self.branches: dict[str, str] = {"main": root_commit}
        self.pulls: dict[int, dict[str, object]] = {}
        self.blobs: dict[str, str] = {}
        self.counter = 0

    def _sha(self) -> str:
        self.counter += 1
        return f"{self.counter:040x}"

    def commit_file(self, branch: str, path: str, body: str) -> None:
        tree = {**self.trees[self.commits[self.branches[branch]]], path: body}
        tree_sha, commit_sha = self._sha(), self._sha()
        self.trees[tree_sha] = tree
        self.commits[commit_sha] = tree_sha
        self.branches[branch] = commit_sha

    def merge(self, number: int) -> None:
        pull = self.pulls[number]
        self.branches["main"] = self.branches[str(pull["head"])]
        pull.update(state="closed", merged=True)

    def close(self, number: int) -> None:
        self.pulls[number].update(state="closed")

    def file(self, branch: str, path: str) -> str | None:
        return self.trees[self.commits[self.branches[branch]]].get(path)

    def _pull_json(self, number: int) -> dict[str, object]:
        pull = self.pulls[number]
        return {
            "html_url": f"https://github.com/acme/handbook/pull/{number}",
            "state": pull["state"],
            "merged": pull["merged"],
            "base": {"ref": "main"},
            "head": {"ref": pull["head"], "repo": {"full_name": "acme/handbook"}},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/repos/acme/handbook")
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET" and path == "/pulls":
            head = request.url.params["head"].removeprefix("acme:")
            return httpx.Response(
                200,
                json=[
                    self._pull_json(number)
                    for number, pull in self.pulls.items()
                    if pull["head"] == head and pull["state"] == "open"
                ],
            )
        if request.method == "GET" and path.startswith("/pulls/"):
            return httpx.Response(200, json=self._pull_json(int(path.split("/")[2])))
        if request.method == "POST" and path == "/pulls":
            number = len(self.pulls) + 17
            self.pulls[number] = {
                "head": body["head"],
                "state": "open",
                "merged": False,
            }
            return httpx.Response(201, json=self._pull_json(number))
        if request.method == "GET" and path.startswith("/contents/"):
            text = self.file(request.url.params["ref"], path.removeprefix("/contents/"))
            if text is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(text.encode()).decode(),
                    "sha": _blob(text),
                },
            )
        if request.method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path.removeprefix("/git/ref/heads/")
            if branch not in self.branches:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": self.branches[branch]}})
        if request.method == "GET" and path == "/branches/main":
            commit = self.branches["main"]
            return httpx.Response(
                200,
                json={
                    "commit": {
                        "sha": commit,
                        "commit": {"tree": {"sha": self.commits[commit]}},
                    }
                },
            )
        if request.method == "GET" and path.startswith("/git/commits/"):
            return httpx.Response(
                200, json={"tree": {"sha": self.commits[path.split("/")[3]]}}
            )
        if request.method == "POST" and path == "/git/blobs":
            blob_sha = _blob(body["content"])
            self.blobs[blob_sha] = body["content"]
            return httpx.Response(201, json={"sha": blob_sha})
        if request.method == "POST" and path == "/git/trees":
            entry = body["tree"][0]
            sha = self._sha()
            self.trees[sha] = {
                **self.trees[body["base_tree"]],
                entry["path"]: self.blobs[entry["sha"]],
            }
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "/git/commits":
            sha = self._sha()
            self.commits[sha] = body["tree"]
            return httpx.Response(201, json={"sha": sha})
        if path.startswith("/git/refs"):
            branch = (
                body["ref"].removeprefix("refs/heads/")
                if "ref" in body
                else path.removeprefix("/git/refs/heads/")
            )
            self.branches[branch] = body["sha"]
            return httpx.Response(
                201,
                json={
                    "ref": f"refs/heads/{branch}",
                    "object": {"type": "commit", "sha": body["sha"]},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    from mycelium.docgen import github_destination

    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps(
            {
                "docs": {
                    "type": "github",
                    "path_template": "docs/{slug}.md",
                    "config": {
                        "owner": "acme",
                        "repo": "handbook",
                        "base_branch": "main",
                        "token_env": "DOCS_TOKEN",
                    },
                }
            }
        ),
    )
    monkeypatch.setenv("DOCS_TOKEN", "test-only-credential")
    import_product_environment()
    fake = FakeGitHub()
    monkeypatch.setattr(
        github_destination,
        "_client",
        lambda config, token: httpx.Client(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


def _later() -> datetime:
    return datetime.now(UTC) + publication.REFRESH_INTERVAL


def _revise(conn, document_id, prompt, **kwargs) -> str:
    row = docs_store.get_document(conn, document_id)
    run_id = doc_runs.start_run(
        prompt=prompt,
        guideline_set=None,
        document_type=None,
        created_by=None,
        conn=conn,
        target_document_id=document_id,
        expected_revision=int(row["current_revision"]),
        **kwargs,
    )
    doc_runs.wait_all()
    return run_id


def test_a_document_round_trips_through_review_edits_and_merge(
    conn, github, monkeypatch
):
    started_from: list[RevisionTarget] = []

    def runner(prompt, *, revision_target=None, **kwargs):
        assert revision_target is not None
        started_from.append(revision_target)
        return {
            "outcome": "document_written",
            "slug": "ignored",
            "title": "SSO",
            "body": revision_target.current.body + f"\n{prompt}\n",
            "statement_ids": ["stm_1"],
        }

    monkeypatch.setattr(doc_runs, "_default_runner", runner)
    document_id = _document(conn)
    path = "docs/sso.md"
    branch = f"mycelium/docs/sso-{document_id}"

    first = publication.publish(conn, document_id, "docs")
    assert (first["pull_request_number"], github.file(branch, path)) == (17, "# SSO\n")

    github.commit_file(branch, path, "# SSO\n\nReviewer: mind the IdP clock.\n")
    run = docs_store.get_run(conn, _revise(conn, document_id, "Add a summary."))
    assert (run["outcome"], run["revision_base"]) == ("document_written", "destination")
    assert "Reviewer: mind the IdP clock." in started_from[-1].current.body

    publication.publish(conn, document_id, "docs")
    assert github.file(branch, path) == (
        "# SSO\n\nReviewer: mind the IdP clock.\n\nAdd a summary.\n"
    )
    assert list(github.pulls) == [17]

    github.merge(17)
    publication.refresh_pull_request(conn, document_id, now=_later())
    assert _serialized(conn, document_id)["delivery_status"] == "merged"

    github.commit_file("main", path, "# SSO\n\nEdited on main after merge.\n")
    _revise(conn, document_id, "Add a caveat.")
    assert started_from[-1].base == "destination"
    second = publication.publish(conn, document_id, "docs")
    assert second["pull_request_number"] == 18
    assert github.file(branch, path) == (
        "# SSO\n\nEdited on main after merge.\n\nAdd a caveat.\n"
    )
    assert _serialized(conn, document_id)["delivery_status"] == "published"

    github.close(18)
    publication.refresh_pull_request(conn, document_id, now=_later())
    assert _serialized(conn, document_id)["delivery_status"] == "closed"
    third = publication.publish(conn, document_id, "docs")
    assert third["pull_request_number"] == 19


def test_a_revision_over_edits_on_both_sides_is_refused_before_a_run_exists(
    conn, github, monkeypatch
):
    monkeypatch.setattr(
        doc_runs, "_default_runner", lambda *args, **kwargs: pytest.fail("ran")
    )
    document_id = _document(conn)
    publication.publish(conn, document_id, "docs")
    github.commit_file(f"mycelium/docs/sso-{document_id}", "docs/sso.md", "# Edited\n")
    row = docs_store.get_document(conn, document_id)
    docs_store.upsert_document(
        conn,
        slug="sso",
        title="SSO",
        body="# SSO, edited here too\n",
        guideline_set="kb",
        document_type="how-to",
        updates=document_id,
        replacing=docs_store.body_digest(row["body"]),
        expected_revision=1,
    )

    with pytest.raises(ValueError, match="Mycelium will not merge the two"):
        _revise(conn, document_id, "Tidy up.")

    assert docs_store.list_runs(conn) == []


def test_refresh_keeps_the_last_state_when_github_cannot_be_reached(
    conn, github, monkeypatch, caplog
):
    from mycelium.docgen import github_destination

    document_id = _document(conn)
    publication.publish(conn, document_id, "docs")
    monkeypatch.setattr(
        github_destination,
        "_client",
        lambda config, token: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(502))
        ),
    )

    publication.refresh_pull_request(conn, document_id, now=_later())

    pull_request = _serialized(conn, document_id)["pull_request"]
    assert isinstance(pull_request, dict) and pull_request["state"] == "open"
    assert "pull request state" in caplog.text


def test_refresh_reuses_a_recent_answer(conn, github):
    document_id = _document(conn)
    publication.publish(conn, document_id, "docs")
    github.merge(17)

    publication.refresh_pull_request(conn, document_id)

    assert _serialized(conn, document_id)["delivery_status"] == "published"


# --- the same loop through the HTTP routes ----------------------------------


def test_the_http_routes_track_the_pull_request_and_offer_both_sides(
    conn, github, monkeypatch
):
    from fastapi.testclient import TestClient

    from mycelium import auth, drafts_store, guidelines, prompt_store
    from mycelium.http import AuthMiddleware, app

    async def writer(*_):
        return auth.Principal(id="w", name="Writer", role="writer", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", writer)
    prompts = prompt_store.connection()
    # Routes run on worker threads, past a thread-pinned connection.
    monkeypatch.setattr(drafts_store, "connection", lambda: conn)
    monkeypatch.setattr(prompt_store, "connection", lambda: prompts)
    for slot in ("guidance", "how-to"):
        prompt_store.save(prompts, type=guidelines.TYPE, name=f"kb/{slot}", text="t")
    monkeypatch.setattr(
        doc_runs,
        "_default_runner",
        lambda prompt, *, revision_target, **kwargs: {
            "outcome": "document_written",
            "slug": "sso",
            "title": "SSO",
            "body": revision_target.current.body + prompt + "\n",
            "statement_ids": ["stm_1"],
        },
    )
    client = TestClient(app)
    document_id = _document(conn)
    url = f"/api/documentation/documents/{document_id}"
    delivered = client.post(
        url + "/delivery", json={"destination": "docs", "expected_revision": 1}
    )
    assert delivered.json()["pull_request_number"] == 17
    assert client.get(url).json()["pull_request"]["state"] == "open"

    github.commit_file(f"mycelium/docs/sso-{document_id}", "docs/sso.md", "# Ed\n")
    docs_store.upsert_document(
        conn,
        slug="sso",
        title="SSO",
        body="# SSO, edited here too\n",
        guideline_set="kb",
        document_type="how-to",
        updates=document_id,
        replacing=docs_store.body_digest("# SSO\n"),
        expected_revision=1,
    )
    revise = {"prompt": "Tidy.", "expected_revision": 2}
    refused = client.post(url + "/revisions", json=revise)
    assert (refused.status_code, refused.json()["code"]) == (
        409,
        "both_sides_edited",
    )

    run = client.post(
        url + "/revisions", json={**revise, "start_from_destination": True}
    ).json()
    doc_runs.wait_all()
    assert run["revision_base"] == "destination"
    assert docs_store.get_document(conn, document_id)["body"] == "# Ed\nTidy.\n"

    github.merge(17)
    monkeypatch.setattr(publication, "REFRESH_INTERVAL", timedelta(0))
    assert client.get(url).json()["pull_request"]["state"] == "merged"
