"""Explicit saved product configuration for isolated tests."""

import tempfile
from pathlib import Path

from mycelium import product_settings, prompt_store

_directories: list[tempfile.TemporaryDirectory] = []


def connection():
    if not prompt_store.is_configured():
        directory = tempfile.TemporaryDirectory(prefix="mycelium-product-test-")
        _directories.append(directory)
        prompt_store.configure(Path(directory.name) / "prompts.db")
        conn = prompt_store.connection()
        prompt_store.migrate(conn)
        prompt_store.use_connection(conn)
    return prompt_store.connection()


def set_product(body: product_settings.Body) -> None:
    conn = connection()
    conn.execute(
        "INSERT INTO product_settings VALUES (?, 1, ?) ON CONFLICT(section) DO UPDATE SET body_json=excluded.body_json",
        (body.kind, body.model_dump_json()),
    )


def import_product_environment() -> None:
    conn = connection()
    for default in product_settings.DEFAULTS:
        body = product_settings._legacy(default, conn)
        set_product(body)
