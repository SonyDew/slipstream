"""SQLAlchemy declarative base and shared column helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Stored naive-in-UTC on SQLite (which has no tz type) but always constructed
    aware so comparisons in application code are unambiguous.
    """
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """DateTime that round-trips as timezone-aware UTC on every backend.

    SQLite discards tzinfo; this normalises on the way in and re-attaches UTC on
    the way out so callers never see a naive datetime.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class JSONEncodedDict(TypeDecorator):
    """Portable JSON column.

    SQLite gained JSON functions late and PostgreSQL prefers JSONB; storing a
    TEXT blob keeps the model backend-neutral, which is what the "PostgreSQL
    later" requirement needs. Values are always dict/list.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or value == "":
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None


class Base(DeclarativeBase):
    """Declarative base for every model."""

    type_annotation_map: ClassVar[dict] = {
        dict[str, Any]: JSONEncodedDict,
        datetime: UTCDateTime,
    }


class TimestampMixin:
    """created_at / updated_at maintained by the ORM."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
