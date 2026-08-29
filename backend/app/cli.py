"""Operational CLI.

    python -m app.cli init-db
    python -m app.cli verify
    python -m app.cli cleanup
    python -m app.cli create-admin --username alice --email a@example.com
    python -m app.cli reset-password --username admin
    python -m app.cli stats

Used by the setup/backup/update scripts on every platform, so operators never
need to open a Python REPL.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.version import VERSION

log = get_logger("slipstream.cli")


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init_db(args: argparse.Namespace) -> int:
    from app.db.init_db import init_database, verify_bootstrap

    result = init_database(use_migrations=not args.no_migrations)
    verification = verify_bootstrap()
    _print({"initialised": result, "verification": verification})

    if not verification.get("ok"):
        print("\nERROR: bootstrap verification failed.", file=sys.stderr)
        return 1
    if verification.get("must_change_password"):
        print(
            "\nWARNING: the administrator is using the temporary password.\n"
            "         Sign in and change it before using this deployment.",
            file=sys.stderr,
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Confirm the schema, the admin account and the password hashing."""
    from sqlalchemy import inspect

    from app.db.init_db import verify_bootstrap
    from app.db.session import check_database, engine

    db_ok, detail = check_database()
    tables = sorted(inspect(engine).get_table_names()) if db_ok else []
    expected = {
        "users",
        "sessions",
        "download_jobs",
        "download_history",
        "admin_audit_log",
        "app_settings",
    }
    missing = sorted(expected - set(tables))
    verification = verify_bootstrap() if db_ok else {"ok": False, "reason": detail}

    from app.services.extractor import extractor_status, ffmpeg_status

    payload = {
        "version": VERSION,
        "database": {"ok": db_ok, "detail": detail, "tables": tables, "missing": missing},
        "admin": verification,
        "extractor": extractor_status(),
        "ffmpeg": ffmpeg_status(),
    }
    _print(payload)

    ok = db_ok and not missing and bool(verification.get("ok"))
    return 0 if ok else 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    from app.services.cleanup import run_cleanup

    report = run_cleanup()
    _print(report.as_dict())
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    from app.db.session import SessionLocal
    from app.models.user import UserRole
    from app.services.auth import register_user

    password = args.password or getpass.getpass("Password: ")
    confirm = args.password or getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user = register_user(
            db,
            username=args.username,
            email=args.email,
            password=password,
            role=UserRole.ADMIN.value if args.admin else UserRole.USER.value,
            enforce_settings=False,
        )
        db.commit()
        _print(
            {
                "created": True,
                "id": user.id,
                "username": user.display_username,
                "role": user.role,
            }
        )
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_reset_password(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import User
    from app.services.auth import admin_set_password

    password = args.password or getpass.getpass("New password: ")
    db = SessionLocal()
    try:
        user = db.execute(
            select(User).where(User.username == args.username.strip().lower())
        ).scalar_one_or_none()
        if user is None:
            print(f"No such user: {args.username}", file=sys.stderr)
            return 1
        admin_set_password(db, user, password)
        db.commit()
        _print({"reset": True, "username": user.display_username})
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_stats(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.models.job import DownloadJob
    from app.models.records import DownloadHistory
    from app.models.user import User
    from app.services.storage import temp_usage

    db = SessionLocal()
    try:

        def count(model: Any) -> int:
            return int(db.execute(select(func.count()).select_from(model)).scalar() or 0)

        _print(
            {
                "users": count(User),
                "jobs": count(DownloadJob),
                "history": count(DownloadHistory),
                "temp": temp_usage(),
                "database_url": settings.DATABASE_URL.split("///")[-1],
            }
        )
        return 0
    finally:
        db.close()


def cmd_settings(args: argparse.Namespace) -> int:
    from app.core.settings_store import store
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if args.set:
            updates: dict[str, Any] = {}
            for pair in args.set:
                if "=" not in pair:
                    print(f"Expected key=value, got: {pair}", file=sys.stderr)
                    return 1
                key, _, value = pair.partition("=")
                updates[key.strip()] = value.strip()
            store.update(db, updates, actor="cli")
            db.commit()
        _print(store.all(db))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=f"Slipstream {VERSION} operational commands",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-db", help="create schema and seed the initial admin")
    init.add_argument(
        "--no-migrations",
        action="store_true",
        help="use metadata create_all instead of Alembic",
    )
    init.set_defaults(func=cmd_init_db)

    verify = subparsers.add_parser("verify", help="check schema, admin account and toolchain")
    verify.set_defaults(func=cmd_verify)

    cleanup = subparsers.add_parser("cleanup", help="run one cleanup sweep")
    cleanup.set_defaults(func=cmd_cleanup)

    create = subparsers.add_parser("create-admin", help="create a user account")
    create.add_argument("--username", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--password", help="omit to be prompted (recommended)")
    create.add_argument("--admin", action="store_true", default=True)
    create.add_argument("--no-admin", dest="admin", action="store_false")
    create.set_defaults(func=cmd_create_admin)

    reset = subparsers.add_parser("reset-password", help="set a user password")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password", help="omit to be prompted (recommended)")
    reset.set_defaults(func=cmd_reset_password)

    stats = subparsers.add_parser("stats", help="print row counts and temp usage")
    stats.set_defaults(func=cmd_stats)

    settings_cmd = subparsers.add_parser("settings", help="show or change runtime settings")
    settings_cmd.add_argument("--set", action="append", metavar="KEY=VALUE", help="may be repeated")
    settings_cmd.set_defaults(func=cmd_settings)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
