"""Mycelium CLI entrypoint.

Subcommands:
    serve              (default) run the MCP server
    export             write a .tar.gz snapshot of the substrate
    import             restore a snapshot into the data dir
    users list         show all users + their roles
    users set-role     change a user's role by email
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _default_data_dir() -> Path:
    return Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser()


def _cmd_serve(args: argparse.Namespace) -> None:
    from . import server

    server.init(args.data_dir)
    server.run()


def _cmd_export(args: argparse.Namespace) -> None:
    from . import backup

    manifest = backup.export_substrate(
        args.data_dir,
        args.archive,
        include_history=not args.no_history,
        include_vectors=not args.no_vectors,
    )
    print(f"wrote {args.archive}", file=sys.stderr)
    for table, count in sorted(manifest["row_counts"].items()):
        print(f"  {table}: {count}", file=sys.stderr)


def _auth_db_path(data_dir: Path) -> Path:
    return data_dir / "mycelium-auth.db"


def _open_auth_conn(data_dir: Path):
    """Open the auth DB without going through `server.init` (which
    would also open the substrate, embed model, vector indexes — way
    more than `users` commands need). Returns a sqlite3 connection
    with FK enforcement on, same as `auth_store.connect`.
    """
    from . import auth_store

    path = _auth_db_path(data_dir)
    if not path.exists():
        print(
            f"auth DB not found at {path}; has the server been run yet?",
            file=sys.stderr,
        )
        sys.exit(1)
    conn = auth_store.connect(path)
    auth_store.migrate(conn)
    return conn


def _cmd_users_list(args: argparse.Namespace) -> None:
    conn = _open_auth_conn(args.data_dir)
    rows = conn.execute(
        "SELECT email, name, role, type, status, last_login_at "
        "FROM users ORDER BY role DESC, email"
    ).fetchall()
    if not rows:
        print("(no users)", file=sys.stderr)
        return
    print(
        f"{'EMAIL':<40} {'ROLE':<8} {'TYPE':<8} {'STATUS':<10} {'NAME':<24} LAST LOGIN"
    )
    for r in rows:
        last = (r["last_login_at"] or "")[:10] or "—"
        email = r["email"] or "(none)"
        print(
            f"{email:<40} {r['role']:<8} {r['type']:<8} {r['status']:<10} "
            f"{(r['name'] or '')[:24]:<24} {last}"
        )


def _cmd_users_set_role(args: argparse.Namespace) -> None:
    if args.role not in ("reader", "writer", "admin"):
        print(f"role must be reader|writer|admin (got {args.role!r})", file=sys.stderr)
        sys.exit(2)
    conn = _open_auth_conn(args.data_dir)
    row = conn.execute(
        "SELECT id, role FROM users WHERE LOWER(email) = LOWER(?)",
        (args.email,),
    ).fetchone()
    if row is None:
        print(f"no user with email {args.email!r}", file=sys.stderr)
        sys.exit(1)

    # Same last-admin guard the HTTP admin endpoint uses, replicated
    # here so the CLI can't lock you out either.
    if row["role"] == "admin" and args.role != "admin":
        n_admins = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()["n"]
        if n_admins <= 1:
            print(
                "refusing to demote the last active admin (would lock everyone out)",
                file=sys.stderr,
            )
            sys.exit(1)

    if row["role"] == args.role:
        print(
            f"{args.email} already has role {args.role}; nothing to do", file=sys.stderr
        )
        return

    conn.execute("UPDATE users SET role = ? WHERE id = ?", (args.role, row["id"]))
    conn.commit()
    print(f"{args.email}: {row['role']} → {args.role}")


def _cmd_import(args: argparse.Namespace) -> None:
    from . import backup

    manifest = backup.import_substrate(
        args.archive,
        args.data_dir,
        force=args.force,
    )
    print(f"restored {args.archive} into {args.data_dir}", file=sys.stderr)
    print(f"  exported_at: {manifest.get('exported_at')}", file=sys.stderr)
    for table, count in sorted(manifest["row_counts"].items()):
        print(f"  {table}: {count}", file=sys.stderr)


def main() -> None:
    # Local-dev convenience: read a `.env` from the working dir. A no-op in
    # deploy, where env is injected before the process starts (load_dotenv
    # never overrides an already-set variable).
    load_dotenv()
    parser = argparse.ArgumentParser(prog="mycelium")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help="data directory (default: $MYCELIUM_DATA_DIR or ./.mycelium)",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="run the MCP server (default)")
    p_serve.set_defaults(func=_cmd_serve)

    p_export = sub.add_parser("export", help="snapshot the substrate to a .tar.gz")
    p_export.add_argument("archive", type=Path, help="output archive path")
    p_export.add_argument(
        "--no-history", action="store_true", help="omit the audit log"
    )
    p_export.add_argument(
        "--no-vectors",
        action="store_true",
        help="omit vector indexes (import will re-embed from text)",
    )
    p_export.set_defaults(func=_cmd_export)

    p_import = sub.add_parser("import", help="restore a snapshot")
    p_import.add_argument("archive", type=Path, help="input archive path")
    p_import.add_argument(
        "--force",
        action="store_true",
        help="clobber an existing data dir (auto-snapshots first)",
    )
    p_import.set_defaults(func=_cmd_import)

    p_users = sub.add_parser("users", help="manage user roles in the auth DB")
    users_sub = p_users.add_subparsers(dest="users_cmd")

    p_users_list = users_sub.add_parser("list", help="list all users")
    p_users_list.set_defaults(func=_cmd_users_list)

    p_users_set = users_sub.add_parser("set-role", help="change a user's role by email")
    p_users_set.add_argument("email", help="user's email address")
    p_users_set.add_argument(
        "role", choices=["reader", "writer", "admin"], help="new role"
    )
    p_users_set.set_defaults(func=_cmd_users_set_role)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        # No subcommand → serve (preserves the prior CLI shape).
        _cmd_serve(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
