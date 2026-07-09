"""The server's per-application runtime state, owned as one object.

``server.init`` builds an ``AppContext`` whole and hands it to the ``server``
module, which holds the single ``_ctx`` and reaches everything through it.
Before this owner existed the same state lived as five loose module globals
plus the layout baker's own module singleton; consolidating them gives one
"is the server up?" check (``_ctx is None``) and one thing to hang the layout
baker on.

Deliberately narrow: it owns only what was previously loose in the ``server``
module — the two vector indexes, the data dir, and the layout baker. The
substrate / auth / drafts stores stay as independent modules with their own
per-thread connections; they are already well-factored and do not belong in a
single god-object.

Plain data, no framework imports — a tool can build one from plain values and
test against it without starting a server. The ``index`` / ``name_index``
fields point at mutable ``vector.Index`` objects that the server mutates in
place (add/replace/delete/save); the frozen dataclass fixes the *identity* of
what the context owns, not the contents of those indexes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import vector
from .layout_baker import LayoutBaker


@dataclass(frozen=True)
class AppContext:
    #: Data dir the substrate was opened from — used to site per-feature
    #: artifacts (e.g. the `ask` eval-harness trace log) alongside the
    #: substrate files.
    data_dir: Path
    index: vector.Index
    index_path: Path
    name_index: vector.Index
    name_index_path: Path
    layout_baker: LayoutBaker
