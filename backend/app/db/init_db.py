"""Database bootstrap.

Creates the schema (via Alembic when available, else metadata) and seeds the
initial administrator.

The bootstrap password is **hashed with Argon2id before it is written**; the
plaintext never touches the database, the logs, or the audit trail. When the
fallback development value is used, the account is flagged
``must_change_password`` so privileged endpoints stay locked until it is rotated.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal, create_all, engine
from app.models.user import User, UserRole
from app.services.auth import register_user

log = get_logger("slipstream.init")

# The documented development fallback. Treated as compromised by definition.
FALLBACK_ADMIN_PASSWORD = "oleg2017A!"  # noqa: S105 - published in the README on purpose


def alembic_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migrations() -> bool:
    """Upgrade to head. Returns False when Alembic is unavailable."""
    config_path = alembic_config_path()
    if not config_path.is_file():
        return False
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:  # pragma: no cover
        return False

    try:
        config = Config(str(config_path))
        config.set_main_option("script_location", str(config_path.parent / "alembic"))
        config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        command.upgrade(config, "head")
        log.info("migrations applied")
        return True
    except Exception as exc:
        log.error("migration failed: %s: %s", type(exc).__name__, exc)
        raise


def _schema_state() -> tuple[bool, bool]:
    """Return ``(core_tables_exist, alembic_version_recorded)``."""
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    except Exception:
        return False, False

    has_core = "users" in tables
    if "alembic_version" not in tables:
        return has_core, False
    try:
        with engine.connect() as conn:
            recorded = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        return has_core, recorded is not None
    except Exception:
        return has_core, False


def stamp_head() -> bool:
    """Mark an already-correct schema as migrated, without running DDL."""
    config_path = alembic_config_path()
    if not config_path.is_file():
        return False
    try:
        from alembic import command
        from alembic.config import Config

        config = Config(str(config_path))
        config.set_main_option("script_location", str(config_path.parent / "alembic"))
        config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        command.stamp(config, "head")
        log.info("stamped existing schema at head")
        return True
    except Exception as exc:
        log.warning("could not stamp schema: %s", type(exc).__name__)
        return False


def ensure_schema(*, use_migrations: bool = True) -> None:
    """Make sure every table exists and Alembic knows the current revision."""
    settings.ensure_directories()

    if not use_migrations:
        create_all()
        return

    has_core, has_version = _schema_state()
    if has_core and not has_version:
        # Tables were created by create_all (tests, a very old deployment, or a
        # restored backup). Stamping avoids a spurious "table already exists".
        stamp_head()

    try:
        if run_migrations():
            return
    except Exception:
        log.warning("falling back to metadata create_all after migration failure")
    create_all()


def seed_initial_admin(db: Session) -> tuple[User | None, bool]:
    """Create the first administrator if no admin exists.

    Returns ``(user, used_fallback_password)``.
    """
    existing_admins = int(
        db.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN.value)
        ).scalar()
        or 0
    )
    if existing_admins:
        return None, False

    username = (os.getenv("INITIAL_ADMIN_USERNAME") or settings.INITIAL_ADMIN_USERNAME).strip()
    email = (os.getenv("INITIAL_ADMIN_EMAIL") or settings.INITIAL_ADMIN_EMAIL).strip()
    password = os.getenv("INITIAL_ADMIN_PASSWORD") or settings.INITIAL_ADMIN_PASSWORD

    used_fallback = password == FALLBACK_ADMIN_PASSWORD

    admin = register_user(
        db,
        username=username,
        email=email,
        password=password,
        role=UserRole.ADMIN.value,
        # Bootstrap must work even when public registration is off, and the
        # username "admin" is otherwise reserved.
        enforce_settings=False,
        # Force rotation whenever the published fallback was used.
        must_change_password=used_fallback,
    )
    db.flush()

    # Note what happened without ever echoing the credential.
    log.warning(
        "initial administrator created",
        user_id=admin.id,
        username=admin.display_username,
        temporary_password=used_fallback,
    )
    return admin, used_fallback


def seed_settings(db: Session) -> int:
    """Materialise default settings rows so the admin UI has something to edit.

    Absent rows already fall back to environment defaults, so this is purely for
    discoverability.
    """
    from app.core.settings_store import SPECS
    from app.models.records import AppSetting

    created = 0
    for spec in SPECS:
        if db.get(AppSetting, spec.key) is None:
            db.add(
                AppSetting(
                    key=spec.key,
                    value={"v": spec.default()},
                    value_type=spec.type,
                    description=spec.description,
                    updated_by="system",
                )
            )
            created += 1
    db.flush()
    return created


def init_database(*, use_migrations: bool = True, seed: bool = True) -> dict[str, object]:
    """Full bootstrap. Idempotent; safe to run on every start."""
    ensure_schema(use_migrations=use_migrations)

    result: dict[str, object] = {
        "database_url": _redact_url(settings.DATABASE_URL),
        "admin_created": False,
        "temporary_password": False,
        "settings_seeded": 0,
    }
    if not seed:
        return result

    db = SessionLocal()
    try:
        admin, used_fallback = seed_initial_admin(db)
        result["admin_created"] = admin is not None
        result["temporary_password"] = used_fallback
        result["settings_seeded"] = seed_settings(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if result["temporary_password"]:
        _print_bootstrap_warning()
    return result


def has_temporary_admin_password() -> bool:
    """True when any admin still carries the forced-rotation flag."""
    db = SessionLocal()
    try:
        return bool(
            db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == UserRole.ADMIN.value,
                    User.must_change_password.is_(True),
                )
            ).scalar()
        )
    finally:
        db.close()


def _print_bootstrap_warning() -> None:
    line = "=" * 74
    log.warning(
        "\n%s\n"
        "  SECURITY: the initial administrator was created with the TEMPORARY\n"
        "  development password documented in the README.\n"
        "\n"
        "  Sign in and change it immediately. Administrator actions are blocked\n"
        "  until the password is rotated.\n"
        "\n"
        "  For production, set INITIAL_ADMIN_PASSWORD in .env BEFORE first start.\n"
        "%s",
        line,
        line,
    )


def _redact_url(url: str) -> str:
    """Hide any credentials in a database URL before logging it."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host_part = rest.rpartition("@")
    return f"{scheme}://***@{host_part}"


def verify_bootstrap() -> dict[str, object]:
    """Post-init assertions used by scripts and the test suite.

    Confirms an admin exists and that the stored value is an Argon2 hash rather
    than anything resembling the plaintext.
    """
    db = SessionLocal()
    try:
        admin = (
            db.execute(select(User).where(User.role == UserRole.ADMIN.value).order_by(User.id))
            .scalars()
            .first()
        )
        if admin is None:
            return {"ok": False, "reason": "no administrator account exists"}

        stored = admin.password_hash or ""
        is_argon2 = stored.startswith("$argon2id$")
        looks_plaintext = stored in {
            settings.INITIAL_ADMIN_PASSWORD,
            FALLBACK_ADMIN_PASSWORD,
        }
        return {
            "ok": is_argon2 and not looks_plaintext,
            "username": admin.display_username,
            "role": admin.role,
            "hash_algorithm": "argon2id" if is_argon2 else "unknown",
            "hash_prefix": stored[:14],
            "plaintext_stored": looks_plaintext,
            "must_change_password": admin.must_change_password,
        }
    finally:
        db.close()


def database_file_size() -> int | None:
    if not settings.db_is_sqlite:
        return None
    raw = settings.DATABASE_URL.split("sqlite:///", 1)[-1]
    try:
        return Path(raw).stat().st_size
    except OSError:
        return None


def dispose_engine() -> None:
    engine.dispose()
