"""Process startup: opening every database and loading the vector indexes.

`init` is the one place the runtime context is built, and stdio and HTTP both
call it. It builds the context whole or not at all: on re-entry it clears the
old context first, so a failure partway leaves the process uninitialized
rather than serving stale indexes against a new substrate. An index file that
is missing or marked dirty is rebuilt by re-embedding before the context
exists.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .. import databases, store, vector
from ..app_context import AppContext
from ..layout_baker import LayoutBaker
from . import runtime
from .draft_application import _substrate_application_result
from .indexes import (
    _clear_dirty_marker,
    _dirty_marker_path,
    _fsync_file,
    _rebuild_vector_index,
    _write_dirty_marker,
)
from .prompt_texts import _seed_prompt_texts
from .runtime import _auth_db, _db, _drafts_db, _prompts_db

logger = logging.getLogger(__name__)


def init(data_dir: Path) -> None:
    """Open the substrate + auth DBs and load (or create) the two
    vector indexes (statements, entity names).

    Auth lives in its own SQLite file (`mycelium-auth.db`) so the
    substrate file can be replaced without disturbing identity or
    tokens — drop `mycelium.db` and restart, every existing user
    session and bearer token keeps working.
    """
    # Invalidate before reconfiguring: if init is re-entered and fails partway
    # (store providers already repointed at the new data dir), leave the
    # process cleanly uninitialized rather than serving the old context's
    # indexes against the new substrate.
    runtime._ctx = None

    from .. import auth_store, docs_store, drafts_store, prompt_store

    data_dir.mkdir(parents=True, exist_ok=True)
    # Before anything below recreates a missing database empty.
    partial_restore = databases.check_restore(data_dir)
    prompt_store.configure(data_dir / "mycelium-prompts.db")
    prompts = _prompts_db()
    existing_settings_instance = (data_dir / "mycelium.db").exists() or prompts.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name IN ('prompt_texts', 'model_settings', 'draft_review_settings')"
    ).fetchone() is not None
    # Persist fresh-instance provenance before other databases can make a
    # retry after interrupted startup look like a legacy upgrade.
    prompt_store.prepare_settings(
        prompts, import_environment=existing_settings_instance
    )
    prompt_store.migrate(prompts)
    prompt_store.initialize_settings(
        prompts, import_environment=existing_settings_instance
    )

    store.configure_substrate(
        data_dir / "mycelium.db",
        history_path=data_dir / "mycelium-history.db",
    )
    baker = LayoutBaker(data_dir / "mycelium.db")
    store.migrate(_db())
    baker.ensure_initial()

    # Point each provider at its file and run the one-time migration on this
    # thread's connection; every other thread reopens lazily against the same
    # file (see the provider in each store module).
    auth_store.configure(data_dir / "mycelium-auth.db")
    auth_store.migrate(_auth_db())

    drafts_store.configure(data_dir / "mycelium-drafts.db")
    drafts_store.migrate(_drafts_db())
    from .. import draft_review_store

    draft_review_store.mark_orphaned(
        _drafts_db(),
        lambda application_id: (
            _substrate_application_result(application_id) is not None
        ),
    )
    docs_store.migrate(_drafts_db())
    from ..docgen import destinations

    destinations.bind_legacy_deliveries(_drafts_db())

    _seed_prompt_texts()

    orphaned_docs = docs_store.mark_orphaned(_drafts_db())
    if orphaned_docs:
        logger.warning(
            "marked %d documentation run(s) failed: orphaned by restart",
            orphaned_docs,
        )

    # The .vec files are re-derivable from the substrate, so a backup may omit
    # them while keeping the *_vector_ids mappings in the DB. When a .vec is
    # missing (a fresh checkout, or a restore of such a backup) or marked dirty
    # after an interrupted write, rebuild the index by re-embedding, or search
    # could silently use vectors that diverge from the populated substrate.
    index_path = data_dir / "mycelium.vec"
    index_dirty = _dirty_marker_path(index_path).exists()
    if index_path.exists() and not index_dirty:
        index = vector.Index.load(index_path)
    else:
        if index_dirty:
            logger.warning(
                "rebuilding statement vector index: dirty marker indicates a "
                "crash before the index was persisted"
            )
        _write_dirty_marker(index_path)
        index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                index,
                store.all_statements_with_text(_db()),
                store.get_vector_id,
                store.next_vector_id,
                store.set_vector_id,
                label="statement",
            )
        index.save(index_path)
        _fsync_file(index_path)
        _clear_dirty_marker(index_path)

    name_index_path = data_dir / "mycelium-names.vec"
    name_index_dirty = _dirty_marker_path(name_index_path).exists()
    if name_index_path.exists() and not name_index_dirty:
        name_index = vector.Index.load(name_index_path)
        # A migration can drop name rows and their vector mappings while
        # the persisted index keeps the vectors (v6's case-variant merge
        # does). Stranded vectors resolve to nothing but still occupy
        # top-k slots in every name search — prune them on load.
        stranded = [
            vid
            for vid in name_index.ids()
            if store.get_name_id_by_vector_id(_db(), vid) is None
        ]
        if stranded:
            logger.info("pruning %d stranded name vector(s)", len(stranded))
            _write_dirty_marker(name_index_path)
            for vid in stranded:
                name_index.delete(vid)
            name_index.save(name_index_path)
            _fsync_file(name_index_path)
            _clear_dirty_marker(name_index_path)
    else:
        if name_index_dirty:
            logger.warning(
                "rebuilding name vector index: dirty marker indicates a crash "
                "before the index was persisted"
            )
        _write_dirty_marker(name_index_path)
        name_index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                name_index,
                store.list_all_names(_db()),
                store.get_name_vector_id,
                store.next_name_vector_id,
                store.set_name_vector_id,
                label="name",
            )
        name_index.save(name_index_path)
        _fsync_file(name_index_path)
        _clear_dirty_marker(name_index_path)

    runtime._ctx = AppContext(
        data_dir=data_dir,
        index=index,
        index_path=index_path,
        name_index=name_index,
        name_index_path=name_index_path,
        layout_baker=baker,
        partial_restore=partial_restore,
    )

    # Start the background mention worker on its own thread and connection
    # (transport-agnostic: both stdio and HTTP funnel through init). The flag is
    # the test suite's "background worker off" switch, so tests can drain the
    # queue synchronously without thread races.
    if os.environ.get("MYCELIUM_DISABLE_MENTION_WORKER") != "1":
        from .. import mention_worker  # local import: workers are optional

        mention_worker.start(data_dir)
    if os.environ.get("MYCELIUM_DISABLE_AUDIENCE_WORKER") != "1":
        from .. import audience_labelling

        audience_labelling.start(data_dir)
    if os.environ.get("MYCELIUM_DISABLE_REVIEW_SWEEP") != "1":
        from .. import draft_review_runs

        draft_review_runs.start_sweeper()
