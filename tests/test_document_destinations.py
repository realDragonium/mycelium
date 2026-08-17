from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from functools import partial

import httpx
import pytest

from mycelium import docs_store, drafts_store, server
from mycelium.docgen.destinations import (
    DeliveryDocument,
    DestinationConfig,
    DestinationError,
    load_destinations,
)
from mycelium.docgen.github_destination import deliver

TOKEN = "credential-sentinel-8d76"
REFLECTION_TOKEN = "dec0de00" * 5
BASE_COMMIT_SHA = "1" * 40
BASE_TREE_SHA = "2" * 40
TREE_SHA = "4" * 40
DELIVERY_SHA = "5" * 40
SECOND_TREE_SHA = "6" * 40
SECOND_DELIVERY_SHA = "7" * 40


def _blob_id(content: str) -> str:
    encoded = content.encode("utf-8")
    header = f"blob {len(encoded)}\0".encode()
    return hashlib.sha1(header + encoded, usedforsecurity=False).hexdigest()


CONTENT_SHA = _blob_id("# Configuring SSO\n")


def _config(**overrides) -> DestinationConfig:
    generic = {
        "name": overrides.pop("name", "knowledge-base"),
        "type": overrides.pop("type", "github"),
        "path_template": overrides.pop(
            "path_template", "docs/{guideline_set}/{slug}.{document_type}.md"
        ),
    }
    settings = {
        "owner": "acme",
        "repo": "handbook",
        "token_env": "DOCS_GITHUB_TOKEN",
        "host": "github.com",
        "base_branch": "docs-main",
    }
    settings.update(overrides)
    return DestinationConfig(**generic, settings=settings)


def _entry(*, path_template="docs/{slug}.md", **settings_overrides) -> dict:
    settings = {
        "owner": "acme",
        "repo": "handbook",
        "token_env": "DOCS_GITHUB_TOKEN",
        "base_branch": "docs-main",
    }
    settings.update(settings_overrides)
    return {
        "type": "github",
        "path_template": path_template,
        "config": settings,
    }


def _document() -> DeliveryDocument:
    return DeliveryDocument(
        id="gdc_123",
        slug="configuring-sso",
        title="Configuring SSO",
        body="# Configuring SSO\n",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=("stm_1", "stm_2"),
    )


def _responses(
    *,
    blob_sha: str = CONTENT_SHA,
    reference: str | None = None,
    existing_reference: str | None = None,
) -> tuple[list[httpx.Request], Callable[[httpx.Request], httpx.Response]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if "/git/ref/heads/" in path and request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        if path.endswith("/branches/docs-main"):
            return httpx.Response(
                200,
                json={
                    "commit": {
                        "sha": BASE_COMMIT_SHA,
                        "commit": {"tree": {"sha": BASE_TREE_SHA}},
                    }
                },
            )
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": blob_sha})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": TREE_SHA})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": DELIVERY_SHA})
        if path.endswith("/git/refs"):
            return httpx.Response(
                201,
                json={"ref": "refs/heads/mycelium/docs/configuring-sso-gdc_123"},
            )
        if path.endswith("/pulls") and request.method == "GET":
            pulls = (
                [] if existing_reference is None else [{"html_url": existing_reference}]
            )
            return httpx.Response(200, json=pulls)
        if path.endswith("/pulls"):
            return httpx.Response(
                201,
                json={
                    "html_url": reference or "https://github.com/acme/handbook/pull/17"
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return requests, handler


def _request_json(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _retry_pull_response(request: httpx.Request, remote: dict) -> httpx.Response:
    if request.method == "GET":
        if remote["open_pull"] is None:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"html_url": remote["open_pull"]}])
    if remote["fail_review"]:
        remote["fail_review"] = False
        remote["open_pull"] = "https://github.com/acme/handbook/pull/17"
        return httpx.Response(500, text=f"failed with {TOKEN}")
    return httpx.Response(422, json={"message": "Pull request exists"})


def _retry_response(
    request: httpx.Request, requests: list[httpx.Request], remote: dict
) -> httpx.Response:
    requests.append(request)
    path = request.url.path
    if "/git/ref/heads/" in path and request.method == "GET":
        if remote["branch_sha"] is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json={"object": {"sha": remote["branch_sha"]}})
    if path.endswith("/branches/docs-main"):
        return httpx.Response(
            200,
            json={
                "commit": {
                    "sha": BASE_COMMIT_SHA,
                    "commit": {"tree": {"sha": BASE_TREE_SHA}},
                }
            },
        )
    if "/git/commits/" in path and request.method == "GET":
        commit_sha = path.rsplit("/", 1)[-1]
        return httpx.Response(
            200, json={"tree": {"sha": remote["commits"][commit_sha]}}
        )
    if path.endswith("/git/blobs"):
        return httpx.Response(201, json={"sha": CONTENT_SHA})
    if path.endswith("/git/trees"):
        tree_sha = remote["tree_responses"].pop(0)
        return httpx.Response(201, json={"sha": tree_sha})
    if path.endswith("/git/commits"):
        commit_sha = remote["commit_responses"].pop(0)
        remote["commits"][commit_sha] = _request_json(request)["tree"]
        return httpx.Response(201, json={"sha": commit_sha})
    if path.endswith("/git/refs") and request.method == "POST":
        if remote["branch_sha"] is not None:
            return httpx.Response(422, json={"message": "Reference exists"})
        remote["branch_sha"] = _request_json(request)["sha"]
        return httpx.Response(201, json={"ref": "created"})
    if "/git/refs/heads/" in path and request.method == "PATCH":
        remote["branch_sha"] = _request_json(request)["sha"]
        return httpx.Response(200, json={"ref": "updated"})
    if path.endswith("/pulls"):
        return _retry_pull_response(request, remote)
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


def test_the_github_destination_runs_the_git_data_sequence_and_opens_review():
    requests, handler = _responses()
    client = httpx.Client(transport=httpx.MockTransport(handler))

    delivery = deliver(
        _config(),
        _document(),
        {"DOCS_GITHUB_TOKEN": TOKEN},
        client=client,
    )

    assert [request.method for request in requests] == [
        "GET",
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "POST",
    ]
    assert [request.url.path for request in requests] == [
        "/repos/acme/handbook/git/ref/heads/mycelium/docs/configuring-sso-gdc_123",
        "/repos/acme/handbook/branches/docs-main",
        "/repos/acme/handbook/git/blobs",
        "/repos/acme/handbook/git/trees",
        "/repos/acme/handbook/git/commits",
        "/repos/acme/handbook/git/refs",
        "/repos/acme/handbook/pulls",
        "/repos/acme/handbook/pulls",
    ]
    assert _request_json(requests[2]) == {
        "content": "# Configuring SSO\n",
        "encoding": "utf-8",
    }
    assert _request_json(requests[3]) == {
        "base_tree": BASE_TREE_SHA,
        "tree": [
            {
                "path": "docs/kb-authoring/configuring-sso.how-to.md",
                "mode": "100644",
                "type": "blob",
                "sha": CONTENT_SHA,
            }
        ],
    }
    assert _request_json(requests[4]) == {
        "message": "Deliver Configuring SSO",
        "tree": TREE_SHA,
        "parents": [BASE_COMMIT_SHA],
    }
    assert _request_json(requests[5]) == {
        "ref": "refs/heads/mycelium/docs/configuring-sso-gdc_123",
        "sha": DELIVERY_SHA,
    }
    assert dict(requests[6].url.params) == {
        "state": "open",
        "head": "acme:mycelium/docs/configuring-sso-gdc_123",
    }
    review = _request_json(requests[7])
    assert review["head"] == "mycelium/docs/configuring-sso-gdc_123"
    assert review["base"] == "docs-main"
    assert "stm_1" in review["body"]
    assert all(
        request.headers["Authorization"] == f"Bearer {TOKEN}" for request in requests
    )
    assert all(TOKEN not in str(request.url) for request in requests)
    assert delivery.destination == "knowledge-base"
    assert delivery.path == "docs/kb-authoring/configuring-sso.how-to.md"
    assert delivery.reference == "https://github.com/acme/handbook/pull/17"
    assert delivery.content_revision == CONTENT_SHA


def test_an_enterprise_destination_uses_the_hosts_api_v3_base():
    requests, handler = _responses(
        reference="https://ghe.corp.example:8443/acme/handbook/pull/17"
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))

    deliver(
        _config(host="ghe.corp.example:8443"),
        _document(),
        {"DOCS_GITHUB_TOKEN": TOKEN},
        client=client,
    )

    assert requests[0].url == (
        "https://ghe.corp.example:8443/api/v3/repos/acme/handbook/git/ref/heads/"
        "mycelium/docs/configuring-sso-gdc_123"
    )


@pytest.mark.parametrize("host", ["GITHUB.COM", "github.com."])
def test_public_github_host_spellings_use_the_public_api_base(host):
    requests, handler = _responses()
    client = httpx.Client(transport=httpx.MockTransport(handler))

    deliver(
        _config(host=host),
        _document(),
        {"DOCS_GITHUB_TOKEN": TOKEN},
        client=client,
    )

    assert requests[0].url == (
        "https://api.github.com/repos/acme/handbook/git/ref/heads/mycelium/docs/"
        "configuring-sso-gdc_123"
    )


@pytest.mark.parametrize(
    "path_template",
    [
        "docs/../{slug}.md",
        "/docs/{slug}.md",
        "-docs/{slug}.md",
        "docs\\{slug}.md",
        "docs/{unknown}.md",
    ],
)
def test_path_templates_that_can_escape_or_name_unknown_fields_are_refused(
    path_template,
):
    raw = json.dumps({"knowledge-base": _entry(path_template=path_template)})

    with pytest.raises(DestinationError):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": raw})


@pytest.mark.parametrize(
    "host",
    [
        "evil.example/@github.com",
        "github.com@evil.example",
        "github.com/path",
        "github.com\n",
    ],
)
def test_a_crafted_host_cannot_redirect_the_credential(host):
    with pytest.raises(DestinationError):
        load_destinations(
            {
                "MYCELIUM_DOC_DESTINATIONS": json.dumps(
                    {"knowledge-base": _entry(host=host)}
                )
            }
        )


def test_unknown_top_level_configuration_fields_are_refused_fail_closed():
    entry = _entry()
    entry["api_url"] = "https://evil.example"

    with pytest.raises(DestinationError, match="unknown field"):
        load_destinations(
            {"MYCELIUM_DOC_DESTINATIONS": json.dumps({"knowledge-base": entry})}
        )


def test_unknown_github_configuration_fields_are_refused_when_destinations_load():
    raw = json.dumps({"knowledge-base": _entry(api_url="https://evil.example")})

    with pytest.raises(DestinationError, match="unknown field"):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": raw})


def test_a_non_object_type_specific_config_is_refused_when_destinations_load():
    entry = _entry()
    entry["config"] = None

    with pytest.raises(DestinationError, match="config must be a JSON object"):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": json.dumps({"broken": entry})})


def test_an_unsupported_destination_type_is_refused_when_destinations_load():
    entry = _entry()
    entry["type"] = "unsupported"

    with pytest.raises(DestinationError, match="unsupported type"):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": json.dumps({"broken": entry})})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "-acme"),
        ("repo", "../handbook"),
        ("base_branch", "--upload-pack=evil"),
        ("token_env", "TOKEN-NAME"),
        ("owner", "acme\n"),
        ("base_branch", "main\n"),
    ],
)
def test_repository_coordinates_and_token_names_are_validated_fail_closed(field, value):
    raw = json.dumps({"knowledge-base": _entry(**{field: value})})

    with pytest.raises(DestinationError):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": raw})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", ["github.com"]),
        ("owner", {"name": "acme"}),
        ("base_branch", True),
    ],
)
def test_non_string_github_configuration_fields_are_refused_fail_closed(field, value):
    raw = json.dumps({"knowledge-base": _entry(**{field: value})})

    with pytest.raises(DestinationError):
        load_destinations({"MYCELIUM_DOC_DESTINATIONS": raw})


def test_non_string_generic_configuration_fields_are_refused_fail_closed():
    entry = _entry()
    entry["type"] = ["github"]

    with pytest.raises(DestinationError):
        load_destinations(
            {"MYCELIUM_DOC_DESTINATIONS": json.dumps({"knowledge-base": entry})}
        )


def test_document_values_cannot_render_a_path_outside_the_destination():
    requests, handler = _responses()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    document = _document()
    escaping = DeliveryDocument(
        id=document.id,
        slug=document.slug,
        title=document.title,
        body=document.body,
        guideline_set="../outside",
        document_type=document.document_type,
        statement_ids=document.statement_ids,
    )

    with pytest.raises(DestinationError):
        deliver(
            _config(path_template="docs/{guideline_set}/{slug}.md"),
            escaping,
            {"DOCS_GITHUB_TOKEN": TOKEN},
            client=client,
        )
    assert requests == []


def test_a_failed_review_can_be_retried_against_the_existing_remote_branch(
    tmp_path, monkeypatch
):
    from mycelium.docgen import github_destination

    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    document_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="# Configuring SSO\n",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=["stm_1", "stm_2"],
    )
    before = dict(docs_store.get_document(conn, document_id))
    drafts_store.use_connection(conn)
    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps({"knowledge-base": _entry()}),
    )
    monkeypatch.setenv("DOCS_GITHUB_TOKEN", TOKEN)
    requests: list[httpx.Request] = []
    remote = {
        "branch_sha": None,
        "commits": {},
        "tree_responses": [TREE_SHA, SECOND_TREE_SHA],
        "commit_responses": [DELIVERY_SHA, SECOND_DELIVERY_SHA],
        "open_pull": None,
        "fail_review": True,
    }

    monkeypatch.setattr(
        github_destination,
        "_client",
        lambda config, token: httpx.Client(
            transport=httpx.MockTransport(
                partial(_retry_response, requests=requests, remote=remote)
            )
        ),
    )

    try:
        with pytest.raises(ValueError) as excinfo:
            server.deliver_document(document_id, "knowledge-base")
        assert dict(docs_store.get_document(conn, document_id)) == before
        assert remote["branch_sha"] == DELIVERY_SHA
        assert TOKEN not in str(excinfo.value)
        assert "***" in str(excinfo.value)
        assert excinfo.value.__cause__ is None

        result = server.deliver_document(document_id, "knowledge-base")
        stored = docs_store.serialize_document(
            docs_store.get_document(conn, document_id)
        )
    finally:
        drafts_store.reset()
        conn.close()

    assert result["content_revision"] == CONTENT_SHA
    assert stored["delivery_content_revision"] == CONTENT_SHA
    assert remote["branch_sha"] == SECOND_DELIVERY_SHA
    trees = [
        _request_json(request)
        for request in requests
        if request.url.path.endswith("/git/trees")
    ]
    assert [tree["base_tree"] for tree in trees] == [BASE_TREE_SHA, TREE_SHA]
    commits = [
        _request_json(request)
        for request in requests
        if request.url.path.endswith("/git/commits") and request.method == "POST"
    ]
    assert [commit["parents"] for commit in commits] == [
        [BASE_COMMIT_SHA],
        [DELIVERY_SHA],
    ]
    base_reads = [
        request
        for request in requests
        if request.url.path.endswith("/branches/docs-main")
    ]
    assert len(base_reads) == 1
    creates = [
        request
        for request in requests
        if request.url.path.endswith("/git/refs") and request.method == "POST"
    ]
    assert len(creates) == 1
    updates = [request for request in requests if request.method == "PATCH"]
    assert len(updates) == 1
    assert _request_json(updates[0]) == {"sha": SECOND_DELIVERY_SHA}
    pull_creates = [
        request
        for request in requests
        if request.url.path.endswith("/pulls") and request.method == "POST"
    ]
    assert len(pull_creates) == 1


def test_a_non_fast_forward_update_is_refused_because_the_branch_moved():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if "/git/ref/heads/" in path:
            return httpx.Response(200, json={"object": {"sha": DELIVERY_SHA}})
        if path.endswith(f"/git/commits/{DELIVERY_SHA}"):
            return httpx.Response(200, json={"tree": {"sha": TREE_SHA}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": CONTENT_SHA})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": SECOND_TREE_SHA})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": SECOND_DELIVERY_SHA})
        if "/git/refs/heads/" in path and request.method == "PATCH":
            return httpx.Response(422, json={"message": "Update is not a fast forward"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError, match="branch moved"):
        deliver(
            _config(),
            _document(),
            {"DOCS_GITHUB_TOKEN": TOKEN},
            client=client,
        )

    assert not any(
        request.url.path.endswith("/branches/docs-main") for request in requests
    )
    update = next(request for request in requests if request.method == "PATCH")
    assert _request_json(update) == {"sha": SECOND_DELIVERY_SHA}
    assert not any(request.url.path.endswith("/pulls") for request in requests)


def test_transport_errors_are_scrubbed_and_do_not_chain_the_credential():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError(f"network exposed {TOKEN}", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(),
            _document(),
            {"DOCS_GITHUB_TOKEN": TOKEN},
            client=client,
        )

    assert TOKEN not in str(excinfo.value)
    assert "***" in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_a_redirect_is_refused_without_contacting_or_authorizing_its_target(
    monkeypatch,
):
    from mycelium.docgen import github_destination

    real_client = httpx.Client
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"location": "https://redirect.example/collect"}
            )
        if request.url.host == "redirect.example":
            return httpx.Response(
                200,
                json={
                    "commit": {
                        "sha": BASE_COMMIT_SHA,
                        "commit": {"tree": {"sha": BASE_TREE_SHA}},
                    }
                },
            )
        return httpx.Response(500, text="stop")

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(github_destination.httpx, "Client", client_factory)

    with pytest.raises(DestinationError, match="HTTP 302"):
        deliver(_config(), _document(), {"DOCS_GITHUB_TOKEN": TOKEN})

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert [
        request.headers.get("Authorization")
        for request in requests
        if request.url.host == "redirect.example"
    ] == []


def test_a_token_shaped_git_object_id_is_refused_without_reflection():
    _, handler = _responses(blob_sha=REFLECTION_TOKEN)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(),
            _document(),
            {"DOCS_GITHUB_TOKEN": REFLECTION_TOKEN},
            client=client,
        )

    assert REFLECTION_TOKEN not in str(excinfo.value)


def test_non_ascii_review_digits_are_refused_without_reflecting_a_token_shaped_value():
    reference = (
        f"https://github.com/acme/{REFLECTION_TOKEN}/pull/\N{ARABIC-INDIC DIGIT ONE}"
        f"\N{ARABIC-INDIC DIGIT SEVEN}"
    )
    _, handler = _responses(reference=reference)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(repo=REFLECTION_TOKEN),
            _document(),
            {"DOCS_GITHUB_TOKEN": REFLECTION_TOKEN},
            client=client,
        )

    assert REFLECTION_TOKEN not in str(excinfo.value)


@pytest.mark.parametrize(
    "reference",
    [
        f"\x00 https://github.com/acme/{REFLECTION_TOKEN}/pull/17",
        f"https://github.com/acme/{REFLECTION_TOKEN}/pull/\n17",
    ],
)
def test_control_characters_in_review_references_are_refused_without_reflection(
    reference,
):
    _, handler = _responses(reference=reference)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(repo=REFLECTION_TOKEN),
            _document(),
            {"DOCS_GITHUB_TOKEN": REFLECTION_TOKEN},
            client=client,
        )

    assert REFLECTION_TOKEN not in str(excinfo.value)


def test_review_path_comparison_does_not_fold_non_ascii_text_into_coordinates():
    reference = f"https://github.com/ß/{REFLECTION_TOKEN}/pull/17"
    _, handler = _responses(reference=reference)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(owner="ss", repo=REFLECTION_TOKEN),
            _document(),
            {"DOCS_GITHUB_TOKEN": REFLECTION_TOKEN},
            client=client,
        )

    assert REFLECTION_TOKEN not in str(excinfo.value)


def test_an_existing_review_reference_passes_through_reference_validation():
    requests, handler = _responses(existing_reference=REFLECTION_TOKEN)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(),
            _document(),
            {"DOCS_GITHUB_TOKEN": REFLECTION_TOKEN},
            client=client,
        )

    assert REFLECTION_TOKEN not in str(excinfo.value)
    assert not any(
        request.url.path.endswith("/pulls") and request.method == "POST"
        for request in requests
    )


@pytest.mark.parametrize(
    "reference",
    [
        TOKEN,
        "http://github.com/acme/handbook/pull/17",
        "https://redirect.example/acme/handbook/pull/17",
        "https://github.com/acme/other/pull/17",
        f"https://github.com/acme/handbook/pull/{TOKEN}",
    ],
)
def test_unopenable_or_wrong_repository_review_references_are_refused_without_reflection(
    reference,
):
    _, handler = _responses(reference=reference)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DestinationError) as excinfo:
        deliver(
            _config(),
            _document(),
            {"DOCS_GITHUB_TOKEN": TOKEN},
            client=client,
        )

    assert TOKEN not in str(excinfo.value)


def test_the_delivery_tool_records_a_completed_delivery(tmp_path, monkeypatch):
    from mycelium.docgen import github_destination

    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    document_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="# Configuring SSO\n",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=["stm_1", "stm_2"],
    )
    drafts_store.use_connection(conn)
    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps({"knowledge-base": _entry()}),
    )
    monkeypatch.setenv("DOCS_GITHUB_TOKEN", TOKEN)
    _, handler = _responses()
    monkeypatch.setattr(
        github_destination,
        "_client",
        lambda config, token: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    try:
        result = server.deliver_document(document_id, "knowledge-base")
        document = docs_store.serialize_document(
            docs_store.get_document(conn, document_id)
        )
    finally:
        drafts_store.reset()
        conn.close()

    assert result == {
        "destination": "knowledge-base",
        "path": "docs/configuring-sso.md",
        "reference": "https://github.com/acme/handbook/pull/17",
        "content_revision": CONTENT_SHA,
    }
    assert document["body"] == "# Configuring SSO\n"
    assert document["delivery_destination"] == "knowledge-base"
    assert document["delivery_path"] == "docs/configuring-sso.md"
    assert document["delivery_reference"] == (
        "https://github.com/acme/handbook/pull/17"
    )
    assert document["delivery_content_revision"] == CONTENT_SHA


def test_listing_destinations_returns_only_generic_configuration(monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps({"knowledge-base": _entry()}),
    )
    monkeypatch.setenv("DOCS_GITHUB_TOKEN", TOKEN)

    listed = server.list_documentation_destinations()

    assert listed == {
        "destinations": [
            {
                "name": "knowledge-base",
                "type": "github",
                "path_template": "docs/{slug}.md",
            }
        ]
    }
    rendered = json.dumps(listed)
    assert "DOCS_GITHUB_TOKEN" not in rendered
    assert TOKEN not in rendered


def test_listing_refuses_a_destination_whose_specific_config_cannot_be_parsed(
    monkeypatch,
):
    entry = _entry()
    entry["config"] = None
    monkeypatch.setenv("MYCELIUM_DOC_DESTINATIONS", json.dumps({"broken": entry}))

    with pytest.raises(ValueError, match="config must be a JSON object"):
        server.list_documentation_destinations()


def test_delivering_an_unknown_document_refuses_before_contacting_a_destination(
    monkeypatch,
):
    from mycelium.docgen import destinations

    conn = docs_store.connect(":memory:")
    docs_store.migrate(conn)
    drafts_store.use_connection(conn)
    contacted = False

    def unexpected_delivery(*args, **kwargs):
        nonlocal contacted
        contacted = True

    monkeypatch.setattr(destinations, "deliver_document", unexpected_delivery)
    try:
        with pytest.raises(ValueError, match="generated document not found"):
            server.deliver_document("gdc_missing", "knowledge-base")
        assert contacted is False
    finally:
        drafts_store.reset()
        conn.close()


def test_delivery_tools_are_registered_with_their_inferred_roles():
    assert server.deliver_document._mycelium_required_role == "writer"
    assert server.list_documentation_destinations._mycelium_required_role == "reader"
