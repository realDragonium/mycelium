"""Duplicate-entity detection against names embedded by nomic-embed-text.

The vectors in `fixtures/entity_duplicate_vectors.json` are real model
output, so the threshold and wording rules are checked against what an
instance actually sees. Re-record them after changing the names below, with
Ollama serving the embedding model:

    uv run python tests/test_entity_duplicates.py
"""

from __future__ import annotations

import base64
import json
import os
import struct
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from mycelium import embed, server, store
from mycelium.server import runtime

VECTORS = Path(__file__).parent / "fixtures" / "entity_duplicate_vectors.json"

DUPLICATES = [
    ("SSO", "Single sign-on"),
    ("Login page", "Sign-in page"),
    ("Email address", "E-mail address"),
    ("Admin", "Administrator"),
    ("Login", "Sign-in"),
    ("Only Admin Exports", "Admin Only Exports"),
]
# Each embeds at least as close to a name above as some true duplicates do:
# "Sign-up" scores 0.87 against "Sign-in", "Login page" 0.83 to "Sign-in page".
NEAR_MISSES = ["Logout", "Sign-up", "Sign-out", "Email"]
# Sibling names that embed as close as the duplicates above: one token tells
# them apart, one name extends the other, or they share only a stem or a
# family prefix.
SIBLINGS = [
    "invoice_template_v1",
    "invoice_template_v2",
    "invoice_template_-_v3",
    "export_batch_i_size",
    "export_batch_ii_size",
    "sync_xyzh_interval",
    "sync_xyzm_interval",
    "invoice_tax_total",
    "invoice_discount_total",
    "invoice_eu_tax_total",
    "login_rate_window_report",
    "login_rate_burst_cap_report",
    "InvoiceHub",
    "InvoiceHive",
    "Export Schedule Setting",
    "Export Schedule Config",
]
NOTIFY_FAMILY = [
    "notify_invoice_paid",
    "notify_export_ready",
    "notify_login_failed",
    "notify_seat_added",
    "notify_plan_changed",
    "notify_sso_enabled",
    "notify_trial_ending",
    "notify_card_expiring",
    "notify_member_removed",
    "notify_quota_reached",
]


def _populate() -> dict[str, str]:
    names = [name for pair in DUPLICATES for name in pair]
    names += NEAR_MISSES + SIBLINGS + NOTIFY_FAMILY
    return {
        name: server.upsert_entity(name=name, description="")["entity_id"]
        for name in names
    }


def _recorded() -> Callable[[str], list[float]]:
    blobs = json.loads(VECTORS.read_text())

    def embedder(text: str) -> list[float]:
        raw = base64.b64decode(blobs[text])
        return list(struct.unpack(f"<{len(raw) // 2}e", raw))

    return embedder


@pytest.fixture
def entities(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", _recorded())
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    runtime._ctx = None
    server.init(tmp_path)
    return _populate()


def _reported(ids: dict[str, str]) -> set[frozenset[str]]:
    label = {entity_id: name for name, entity_id in ids.items()}
    return {
        frozenset((label[c["a_entity_id"]], label[c["b_entity_id"]]))
        for c in server.find_entity_duplicates()["candidates"]
    }


def test_reports_genuine_duplicates_and_not_near_misses(entities):
    assert _reported(entities) == {frozenset(pair) for pair in DUPLICATES}


def test_explains_each_match(entities):
    candidates = server.find_entity_duplicates()["candidates"]
    by_names = {
        frozenset((m["a_name"], m["b_name"])): m
        for c in candidates
        for m in c["matches"]
    }
    assert by_names[frozenset(("SSO", "Single sign-on"))]["via"] == "initials"
    login = by_names[frozenset(("Login page", "Sign-in page"))]
    assert login["via"] == "embedding"
    assert 0.75 <= login["score"] < 0.9
    admin_only = by_names[frozenset(("Only Admin Exports", "Admin Only Exports"))]
    assert admin_only["via"] == "same_words"


def test_ranks_lexical_matches_above_embedding_only_ones(entities):
    candidates = server.find_entity_duplicates()["candidates"]
    lexical = [any(m["via"] != "embedding" for m in c["matches"]) for c in candidates]
    assert lexical == sorted(lexical, reverse=True)
    assert candidates[0]["score"] >= candidates[-1]["score"]


def test_pages_through_every_candidate_with_a_total(entities):
    everything = server.find_entity_duplicates()
    first = server.find_entity_duplicates(limit=2)
    rest = server.find_entity_duplicates(limit=50, offset=2)
    assert first["total"] == rest["total"] == len(DUPLICATES)
    assert first["candidates"] + rest["candidates"] == everything["candidates"]


def test_dismissed_pair_stays_hidden_until_an_entity_merges(entities):
    sso, single = entities["SSO"], entities["Single sign-on"]
    with store.transaction(server._db()):
        store.dismiss_entity_duplicate(server._db(), single, sso)
    assert frozenset(("SSO", "Single sign-on")) not in _reported(entities)

    server.merge_entities(sso, entities["Login"])
    assert store.dismissed_entity_duplicates(server._db()) == set()


def _record_vectors() -> None:
    blobs: dict[str, str] = {}
    real = embed.embed

    def recorder(text: str) -> list[float]:
        vector = real(text)
        packed = struct.pack(f"<{len(vector)}e", *vector)
        blobs[text] = base64.b64encode(packed).decode()
        return vector

    os.environ.setdefault("MYCELIUM_DISABLE_MENTION_WORKER", "1")
    os.environ["MYCELIUM_AUTH"] = "off"
    embed.embed = recorder
    with tempfile.TemporaryDirectory() as data_dir:
        os.environ["MYCELIUM_DATA_DIR"] = data_dir
        server.init(Path(data_dir))
        _populate()
    VECTORS.parent.mkdir(exist_ok=True)
    VECTORS.write_text(json.dumps(blobs, indent=0, sort_keys=True) + "\n")


if __name__ == "__main__":
    _record_vectors()
