"""Freeze a populated instance of this build as a migration fixture.

Writes `tests/migration_fixtures/v<NN>-<label>/`: one `<database>.sql` dump
per instance database, `export.tar.gz` made by this build's own `export`,
and `fixture.json`. `tests/test_migration_fixtures.py` starts the current
build on every fixture and imports every archive into a fresh instance, so
each schema shape and archive format this repository has shipped is proven
to carry forward.

Run it whenever that test reports the newest fixture is behind the schema —
in the change that alters the schema, after the migration is written:

    uv run python scripts/capture_migration_fixture.py

To capture an older build, put its source first on the path; the scenario
detects which tables and tools that build has:

    git archive <commit> src | tar -x -C /tmp/old
    PYTHONPATH=/tmp/old/src uv run python scripts/capture_migration_fixture.py \\
        --label <commit>
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "migration_fixtures"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--label", help="fixture label (default: current git commit, short)"
    )
    args = parser.parse_args()

    os.environ.setdefault("MYCELIUM_DISABLE_MENTION_WORKER", "1")
    os.environ.setdefault("MYCELIUM_DISABLE_MCP_HTTP", "1")
    os.environ["MYCELIUM_AUTH"] = "off"
    sys.path.insert(0, str(REPO / "tests"))
    import instance_scenario
    from mycelium import backup, embed, migrations, phrasing

    embed.embed = instance_scenario.embed
    phrasing.check = lambda text, kind=None: []

    version = migrations.CURRENT_VERSION
    label = args.label or _git("rev-parse", "--short", "HEAD")
    out = FIXTURES / f"v{version:02d}-{label}"
    if out.exists():
        sys.exit(f"{out} already exists")

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        instance_scenario.populate(data_dir)
        out.mkdir(parents=True)
        # Vectors are left out: hnswlib files are large, and the importer
        # rebuilds them, which is the path a fresh-instance restore takes.
        backup.export_substrate(data_dir, out / "export.tar.gz", include_vectors=False)
        for db in sorted(data_dir.glob("*.db")):
            with closing(sqlite3.connect(db)) as conn:
                dump = "\n".join(conn.iterdump())
                user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            # iterdump omits user_version, which the migration runner keys on.
            (out / f"{db.stem}.sql").write_text(
                f"PRAGMA user_version = {user_version};\n{dump}\n", encoding="utf-8"
            )
    (out / "fixture.json").write_text(
        json.dumps(
            {
                "schema_version": version,
                "source": label,
                "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out.relative_to(REPO)}")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


if __name__ == "__main__":
    main()
