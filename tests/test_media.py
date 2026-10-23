"""Media: what is accepted, what is served, and to whom."""

from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

import media_samples
from mycelium import auth, auth_store, drafts_store, media, media_formats, server, store
from mycelium.server import runtime

# --- formats ----------------------------------------------------------------


def test_a_png_loses_its_text_chunks_and_keeps_its_picture():
    original = media_samples.png(text=b"GPS\x0052.1,4.3")

    cleaned = media_formats.clean(original)

    assert cleaned.content_type == "image/png"
    assert b"tEXt" not in cleaned.data
    assert cleaned.data == media_samples.png()


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def test_a_jpeg_loses_exif_and_comments_but_keeps_jfif():
    jfif = _jpeg_segment(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00")
    exif = _jpeg_segment(0xE1, b"Exif\x00\x00GPSINFO")
    comment = _jpeg_segment(0xFE, b"shot on a phone")
    scan = _jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\x34\xff\xd9"
    original = b"\xff\xd8" + jfif + exif + comment + scan

    cleaned = media_formats.clean(original)

    assert cleaned.data == b"\xff\xd8" + jfif + scan


def test_a_gif_keeps_only_frames_timing_and_looping():
    header = b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0, 0, 0)
    comment = b"\x21\xfe\x05hello\x00"
    looping = b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    timing = b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    frame = b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02\x02\x44\x01\x00"

    cleaned = media_formats.clean(header + comment + looping + timing + frame + b";")

    assert cleaned.data == header + looping + timing + frame + b";"


def test_an_mp4_metadata_box_becomes_free_space_of_the_same_size():
    ftyp = struct.pack(">I", 16) + b"ftypisom" + b"\x00\x00\x02\x00"
    udta = struct.pack(">I", 16) + b"udta" + b"location"
    moov = struct.pack(">I", 8 + len(udta)) + b"moov" + udta
    original = ftyp + moov

    cleaned = media_formats.clean(original)

    assert len(cleaned.data) == len(original)
    assert b"udta" not in cleaned.data and b"location" not in cleaned.data
    assert cleaned.data.endswith(struct.pack(">I", 16) + b"free" + bytes(8))


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<!DOCTYPE html><html><script>alert(1)</script></html>",
        b"%PDF-1.7\n",
        media_samples.png()[:30],
    ],
    ids=["svg", "html", "pdf", "truncated-png"],
)
def test_anything_else_is_refused(data):
    with pytest.raises(media_formats.Rejected):
        media_formats.clean(data)


# --- through the running app, auth on ------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda text: [1.0] + [0.0] * 767)
    from mycelium.http import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _bearer(role: str, audience_id: str | None = None) -> dict[str, str]:
    conn = runtime._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(
            conn, user_id=user, name="t", scope=role, audience_id=audience_id
        )
    return {"Authorization": f"Bearer {raw}"}


def _statement(client: TestClient, headers: dict[str, str], text: str) -> str:
    r = client.post(
        "/upsert-statement",
        headers=headers,
        json={
            "kind": "state",
            "text": text,
            "links": [],
            "allow_phrasing_violations": True,
        },
    )
    assert r.status_code == 200, r.text
    return str(r.json()["statement_id"])


def _upload(
    client: TestClient, headers: dict[str, str], statement_id: str, data: bytes
) -> dict[str, object]:
    r = client.post(
        "/api/media",
        headers=headers,
        params={"alt_text": "The export dialog", "statement_id": statement_id},
        content=data,
    )
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def test_an_upload_is_served_stripped_and_sandboxed(client):
    admin = _bearer("admin")
    statement = _statement(client, admin, "A workspace export downloads as CSV.")

    item = _upload(client, admin, statement, media_samples.png(text=b"author\x00me"))
    r = client.get(str(item["url"]), headers=admin)

    assert r.status_code == 200
    assert r.content == media_samples.png()
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["content-disposition"].startswith("inline; filename=")
    again = client.get(
        str(item["url"]), headers={**admin, "If-None-Match": r.headers["etag"]}
    )
    assert again.status_code == 304


def test_an_upload_over_the_cap_is_refused_before_it_is_read(client, monkeypatch):
    admin = _bearer("admin")
    statement = _statement(client, admin, "A workspace export downloads as CSV.")
    monkeypatch.setattr(media, "max_bytes", lambda: 64)

    r = client.post(
        "/api/media",
        headers=admin,
        params={"alt_text": "x", "statement_id": statement},
        content=media_samples.png() + bytes(100),
    )

    assert r.status_code == 413
    assert media.library() == []


def test_an_svg_upload_is_refused(client):
    admin = _bearer("admin")
    r = client.post(
        "/api/media", headers=admin, params={"alt_text": "x"}, content=b"<svg/>"
    )
    assert r.status_code == 415


def test_an_external_token_sees_media_only_once_labelled_for_it(client):
    admin = _bearer("admin")
    statement = _statement(client, admin, "A workspace export downloads as CSV.")
    r = client.put(
        f"/api/statements/{statement}/audiences",
        headers=admin,
        json={"audiences": ["external-technical"], "reason": "public"},
    )
    assert r.status_code == 200, r.text
    item = _upload(client, admin, statement, media_samples.png())
    external = _bearer("reader", "external-technical")

    def seen() -> tuple[int, list[str]]:
        content = client.get(str(item["url"]), headers=external).status_code
        listed = client.post(
            "/list-media", headers=external, json={"statement_id": statement}
        )
        assert listed.status_code == 200, listed.text
        return content, [entry["id"] for entry in listed.json()]

    assert seen() == (404, [])
    r = client.put(
        f"/api/media/{item['id']}/audiences",
        headers=admin,
        json={"audiences": ["external-technical"]},
    )
    assert r.status_code == 200, r.text
    assert seen() == (200, [item["id"]])
    assert client.get(f"/api/media/{item['id']}", headers=external).status_code == 403


def test_an_upload_link_takes_one_file_without_sign_in(client):
    writer = _bearer("writer")
    r = client.post(
        "/create-media-upload", headers=writer, json={"alt_text": "The invoice list"}
    )
    assert r.status_code == 200, r.text
    url = r.json()["upload_url"]

    assert client.post(url, content=b"<svg/>").status_code == 415
    done = client.post(url, content=media_samples.png())
    assert done.status_code == 201, done.text
    assert client.post(url, content=media_samples.png()).status_code == 404

    item = media.get(done.json()["media_id"])
    assert (item.origin, item.audiences, item.attachments) == ("agent", None, [])


def test_applying_a_draft_attaches_its_media_evidence(client):
    admin = _bearer("admin")
    item = media.create(
        media_samples.png(),
        media.Details(alt_text="The SSO settings page"),
        origin="agent",
        actor="d1",
    )
    drafter = auth.Principal(id="d1", name="D", role="drafter", type="service")
    token = auth.current_principal.set(drafter)
    session = auth.current_session_id.set("sess-media")
    try:
        queued = server.upsert_statement(
            "capability",
            "An admin can enforce SSO for a workspace.",
            [],
            allow_phrasing_violations=True,
        )
        server.set_operation_evidence(
            queued["draft_id"],
            queued["operation_ref"],
            [{"kind": "media", "media_id": item.id, "claim": "The toggle exists."}],
            queued["revision"],
        )
        draft = server.get_draft(queued["draft_id"])
        server.submit_draft(queued["draft_id"])
    finally:
        auth.current_session_id.reset(session)
        auth.current_principal.reset(token)

    assert (
        draft["ops"][0]["evidence"][0]["excerpt"] == "Alt text: The SSO settings page"
    )
    r = client.post(f"/api/drafts/{queued['draft_id']}/approve", headers=admin)
    assert r.status_code == 200, r.text
    statement_id = r.json()["results"][0]["result"]["statement_id"]
    assert [(a.kind, a.id) for a in media.get(item.id).attachments] == [
        ("statement", statement_id)
    ]


def test_merging_a_statement_moves_its_media(client):
    admin = _bearer("admin")
    kept = _statement(client, admin, "A workspace export downloads as CSV.")
    gone = _statement(client, admin, "Workspace exports download as CSV files.")
    item = _upload(client, admin, gone, media_samples.png())

    r = client.post(
        "/merge-statements", headers=admin, json={"from_id": gone, "into_id": kept}
    )

    assert r.status_code == 200, r.text
    assert [(a.kind, a.id) for a in media.get(str(item["id"])).attachments] == [
        ("statement", kept)
    ]
