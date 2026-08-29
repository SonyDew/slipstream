"""Engine, session factory and SQLite tuning.

Kept deliberately backend-neutral: the only SQLite-specific code is the PRAGMA
listener, which no-ops on other dialects. Switching ``DATABASE_URL`` to
PostgreSQL requires no changes here beyond installing a driver.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base

log = get_logger("slipstream.db")


def _sqlite_connect_args() -> dict[str, Any]:
    return {
        # FastAPI runs sync endpoints in a threadpool, so connections legitimately
        # move between threads. Safety is provided by the pool, not by this flag.
        "check_same_thread": False,
        # Wait rather than immediately raising "database is locked".
        "timeout": 30,
    }


def build_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    database_url = url or settings.DATABASE_URL
    kwargs: dict[str, Any] = {
        "echo": echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = _sqlite_connect_args()
        # A small pool is plenty: SQLite serialises writers anyway, and this
        # bounds file handles on a 1 GB VPS.
        if ":memory:" in database_url:
            # Every connection to :memory: gets its own database unless we share
            # a single connection, which is what tests need.
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
            kwargs["pool_recycle"] = 3600
            _ensure_sqlite_parent(database_url)
    else:  # pragma: no cover - exercised only in a PostgreSQL deployment
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_recycle"] = 1800

    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        _install_sqlite_pragmas(engine)
    return engine


def _ensure_sqlite_parent(database_url: str) -> None:
    """Create the directory holding the SQLite file if it does not exist."""
    raw = database_url.split("sqlite:///", 1)[-1]
    if not raw or raw.startswith(":"):
        return
    try:
        Path(raw).expanduser().parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover
        log.warning("could not create database directory: %s", exc)


def _install_sqlite_pragmas(engine: Engine) -> None:
    """Apply per-connection PRAGMAs.

    * ``foreign_keys`` — SQLite ignores FK constraints unless enabled per
      connection, which would silently defeat every ``ondelete`` rule.
    * ``journal_mode=WAL`` — readers no longer block the writer; essential when
      background workers write while requests read.
    * ``busy_timeout`` — retry a locked write instead of failing instantly.
    * ``synchronous=NORMAL`` — safe with WAL and dramatically cheaper on the
      slow block storage attached to free-tier VPS instances.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            # ~16 MiB page cache (negative = KiB). Bounded for small VPS RAM.
            cursor.execute("PRAGMA cache_size=-16000")
            cursor.execute("PRAGMA mmap_size=134217728")
        finally:
            cursor.close()


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background workers and CLI commands."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all() -> None:
    """Create tables directly.

    Used by the test suite and as the bootstrap path when Alembic has not run.
    Production uses ``alembic upgrade head``.
    """
    import app.models  # noqa: F401  (register mappers before create_all)

    Base.metadata.create_all(bind=engine)


def check_database() -> tuple[bool, str]:
    """Lightweight health probe."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, type(exc).__name__


def checkpoint_wal() -> None:
    """Fold the WAL back into the main database file.

    Called before a backup so a copied .db file is self-consistent.
    """
    if not settings.db_is_sqlite:
        return
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as exc:
        log.warning("wal checkpoint failed: %s", exc)
