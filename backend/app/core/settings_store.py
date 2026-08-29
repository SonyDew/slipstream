"""Runtime application settings.

Environment variables provide the defaults; the ``app_settings`` table holds
administrator overrides. Reads go through a short-lived cache so a hot path like
rate-limit lookup does not hit SQLite on every request, while a multi-worker
deployment still converges within a few seconds of an admin change.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as env_settings
from app.core.logging import get_logger

log = get_logger("slipstream.settings")

SettingType = Literal["bool", "int", "string", "list"]

# How long a cached snapshot is trusted. Short enough that an admin change takes
# effect promptly across workers, long enough to keep SQLite reads off hot paths.
CACHE_TTL_SECONDS = 10.0


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: SettingType
    default: Callable[[], Any]
    description: str
    minimum: int | None = None
    maximum: int | None = None
    # Settings that are unsafe to expose to non-admins.
    admin_only: bool = True
    group: str = "general"


SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "guest_downloads_enabled",
        "bool",
        lambda: env_settings.GUEST_DOWNLOADS_ENABLED,
        "Allow downloads without an account.",
        group="access",
    ),
    SettingSpec(
        "registration_enabled",
        "bool",
        lambda: env_settings.REGISTRATION_ENABLED,
        "Allow new users to register.",
        group="access",
    ),
    SettingSpec(
        "maintenance_mode",
        "bool",
        lambda: env_settings.MAINTENANCE_MODE,
        "Reject all non-admin requests with a maintenance notice.",
        group="access",
    ),
    SettingSpec(
        "allowed_platforms",
        "list",
        lambda: env_settings.allowed_platform_list,
        "Platforms users may download from. Empty means all supported platforms.",
        group="platforms",
    ),
    SettingSpec(
        "max_file_size",
        "int",
        lambda: env_settings.MAX_FILE_SIZE,
        "Largest output file in bytes.",
        minimum=1024 * 1024,
        maximum=64 * 1024 * 1024 * 1024,
        group="limits",
    ),
    SettingSpec(
        "max_video_duration",
        "int",
        lambda: env_settings.MAX_VIDEO_DURATION,
        "Longest video in seconds.",
        minimum=10,
        maximum=60 * 60 * 24,
        group="limits",
    ),
    SettingSpec(
        "max_concurrent_downloads",
        "int",
        lambda: env_settings.MAX_CONCURRENT_DOWNLOADS,
        "Jobs processed simultaneously. Raise carefully on small servers.",
        minimum=1,
        maximum=32,
        group="limits",
    ),
    SettingSpec(
        "temp_file_ttl",
        "int",
        lambda: env_settings.TEMP_FILE_TTL,
        "Seconds a finished file stays downloadable before cleanup removes it.",
        minimum=60,
        maximum=60 * 60 * 24 * 7,
        group="limits",
    ),
    SettingSpec(
        "history_retention_days",
        "int",
        lambda: env_settings.HISTORY_RETENTION_DAYS,
        "Days of download history to keep. 0 disables history entirely.",
        minimum=0,
        maximum=3650,
        group="privacy",
    ),
    SettingSpec(
        "rate_limit_guest",
        "int",
        lambda: env_settings.RATE_LIMIT_GUEST,
        "Guest analyses per hour per IP. 0 means unlimited.",
        minimum=0,
        maximum=100000,
        group="rate_limits",
    ),
    SettingSpec(
        "rate_limit_guest_download",
        "int",
        lambda: env_settings.RATE_LIMIT_GUEST_DOWNLOAD,
        "Guest downloads per hour per IP. 0 means unlimited.",
        minimum=0,
        maximum=100000,
        group="rate_limits",
    ),
    SettingSpec(
        "rate_limit_user",
        "int",
        lambda: env_settings.RATE_LIMIT_USER,
        "Analyses per hour for signed-in users. 0 means unlimited.",
        minimum=0,
        maximum=100000,
        group="rate_limits",
    ),
    SettingSpec(
        "rate_limit_user_download",
        "int",
        lambda: env_settings.RATE_LIMIT_USER_DOWNLOAD,
        "Downloads per hour for signed-in users. 0 means unlimited.",
        minimum=0,
        maximum=100000,
        group="rate_limits",
    ),
    SettingSpec(
        "rate_limit_admin",
        "int",
        lambda: env_settings.RATE_LIMIT_ADMIN,
        "Requests per hour for administrators. 0 means unlimited.",
        minimum=0,
        maximum=1000000,
        group="rate_limits",
    ),
)

SPEC_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SPECS}


@dataclass
class _Cache:
    values: dict[str, Any] = field(default_factory=dict)
    loaded_at: float = 0.0


class SettingsStore:
    """Cached read/write access to runtime settings."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS) -> None:
        self._cache = _Cache()
        self._lock = threading.Lock()
        self._ttl = ttl

    # -- defaults --------------------------------------------------------- #
    @staticmethod
    def defaults() -> dict[str, Any]:
        return {spec.key: spec.default() for spec in SPECS}

    # -- reads ------------------------------------------------------------ #
    def all(self, db: Session) -> dict[str, Any]:
        """Every setting, DB overrides merged over environment defaults."""
        now = time.monotonic()
        with self._lock:
            if self._cache.values and now - self._cache.loaded_at < self._ttl:
                return dict(self._cache.values)

        values = self.defaults()
        try:
            from app.models.records import AppSetting

            rows = db.execute(select(AppSetting)).scalars().all()
            for row in rows:
                if row.key not in SPEC_BY_KEY:
                    continue  # stale key from an older version
                coerced = self._coerce(row.key, self._unwrap(row.value))
                if coerced is not None:
                    values[row.key] = coerced
        except Exception as exc:
            log.warning("could not load app settings: %s", type(exc).__name__)

        with self._lock:
            self._cache = _Cache(values=dict(values), loaded_at=time.monotonic())
        return values

    def get(self, db: Session, key: str) -> Any:
        return self.all(db).get(key, SPEC_BY_KEY[key].default() if key in SPEC_BY_KEY else None)

    def get_bool(self, db: Session, key: str) -> bool:
        return bool(self.get(db, key))

    def get_int(self, db: Session, key: str) -> int:
        value = self.get(db, key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(SPEC_BY_KEY[key].default())

    def get_list(self, db: Session, key: str) -> list[str]:
        value = self.get(db, key)
        return [str(v) for v in value] if isinstance(value, list) else []

    # -- writes ----------------------------------------------------------- #
    def update(
        self,
        db: Session,
        updates: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Validate and persist a batch of settings. Returns applied values."""
        from app.core.errors import ValidationError
        from app.models.records import AppSetting

        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}

        for key, raw_value in updates.items():
            spec = SPEC_BY_KEY.get(key)
            if spec is None:
                errors[key] = "Unknown setting."
                continue
            try:
                value = self._validate(spec, raw_value)
            except ValueError as exc:
                errors[key] = str(exc)
                continue
            applied[key] = value

        if errors:
            raise ValidationError("Some settings could not be saved.", meta={"fields": errors})

        for key, value in applied.items():
            spec = SPEC_BY_KEY[key]
            row = db.get(AppSetting, key)
            # Wrapped in a dict because the column is a JSON object column.
            payload = {"v": value}
            if row is None:
                db.add(
                    AppSetting(
                        key=key,
                        value=payload,
                        value_type=spec.type,
                        description=spec.description,
                        updated_by=actor,
                    )
                )
            else:
                row.value = payload
                row.value_type = spec.type
                row.description = spec.description
                row.updated_by = actor
        db.flush()
        self.invalidate()
        return applied

    def invalidate(self) -> None:
        with self._lock:
            self._cache = _Cache()

    # -- coercion / validation -------------------------------------------- #
    @staticmethod
    def _unwrap(stored: Any) -> Any:
        """Settings are stored as ``{"v": value}`` so scalars fit a JSON column."""
        if isinstance(stored, dict) and "v" in stored:
            return stored["v"]
        return stored

    def _coerce(self, key: str, value: Any) -> Any:
        spec = SPEC_BY_KEY[key]
        try:
            return self._validate(spec, value)
        except ValueError:
            log.warning("stored setting %s is invalid; using default", key)
            return None

    @staticmethod
    def _validate(spec: SettingSpec, value: Any) -> Any:
        if spec.type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in {"true", "1", "yes", "on"}:
                    return True
                if value.lower() in {"false", "0", "no", "off"}:
                    return False
            if isinstance(value, int):
                return bool(value)
            raise ValueError("Must be true or false.")

        if spec.type == "int":
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError("Must be a whole number.") from None
            if spec.minimum is not None and number < spec.minimum:
                raise ValueError(f"Must be at least {spec.minimum}.")
            if spec.maximum is not None and number > spec.maximum:
                raise ValueError(f"Must be at most {spec.maximum}.")
            return number

        if spec.type == "list":
            if isinstance(value, str):
                items = [v.strip() for v in value.split(",")]
            elif isinstance(value, (list, tuple)):
                items = [str(v).strip() for v in value]
            else:
                raise ValueError("Must be a list of values.")
            cleaned = [v.lower() for v in items if v]
            if spec.key == "allowed_platforms":
                from app.providers.registry import registry

                known = set(registry.platform_names())
                unknown = [v for v in cleaned if v not in known]
                if unknown:
                    raise ValueError(f"Unknown platforms: {', '.join(unknown[:5])}")
            return cleaned

        return str(value)[:500]

    # -- introspection for the admin UI ----------------------------------- #
    def describe(self, db: Session) -> list[dict[str, Any]]:
        current = self.all(db)
        return [
            {
                "key": spec.key,
                "type": spec.type,
                "value": current.get(spec.key),
                "default": spec.default(),
                "description": spec.description,
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "group": spec.group,
            }
            for spec in SPECS
        ]


store = SettingsStore()


# --------------------------------------------------------------------------- #
# Public read helpers used across the app
# --------------------------------------------------------------------------- #
def public_settings(db: Session) -> dict[str, Any]:
    """The subset the unauthenticated frontend is allowed to know."""
    values = store.all(db)
    return {
        "registration_enabled": bool(values["registration_enabled"]),
        "guest_downloads_enabled": bool(values["guest_downloads_enabled"]),
        "maintenance_mode": bool(values["maintenance_mode"]),
        "max_file_size": int(values["max_file_size"]),
        "max_video_duration": int(values["max_video_duration"]),
        "allowed_platforms": list(values["allowed_platforms"]),
    }
