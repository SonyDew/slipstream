"""Download history, admin audit log and persisted application settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONEncodedDict, UTCDateTime, utcnow


class DownloadHistory(Base):
    """Durable per-user record of a completed (or failed) download.

    Separate from :class:`~app.models.job.DownloadJob` on purpose: jobs are
    ephemeral and get pruned aggressively along with their temporary files,
    while history is the account-visible ledger with its own retention policy.
    """

    __tablename__ = "download_history"
    __table_args__ = (
        Index("ix_history_user_created", "user_id", "created_at"),
        Index("ix_history_platform", "platform"),
        Index("ix_history_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Null for guests: nothing is retained for an anonymous download.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Intentionally not a foreign key — history must outlive the pruned job row.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)

    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    output_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DownloadHistory id={self.id} platform={self.platform} status={self.status}>"


class AdminAuditLog(Base):
    """Append-only record of privileged actions.

    Never stores credentials, session tokens or secret values — only the action,
    who performed it, what it targeted, and a small safe metadata payload.
    """

    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_admin_created", "admin_user_id", "created_at"),
        Index("ix_audit_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # SET NULL rather than CASCADE: deleting an admin must not erase the record
    # of what that admin did.
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised so the log stays readable after the account is gone.
    admin_username: Mapped[str] = mapped_column(String(64), nullable=False)

    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONEncodedDict, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AdminAuditLog id={self.id} action={self.action}>"


class AppSetting(Base):
    """Runtime-editable settings, overriding environment defaults.

    Values are JSON-encoded so a setting can hold a bool, int, string or list
    without a schema change.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONEncodedDict, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16), default="string", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppSetting key={self.key!r}>"


class AuditAction:
    """Canonical audit action names (kept as constants, not an Enum, so old
    values read back from the database never fail to deserialise)."""

    USER_DISABLED = "USER_DISABLED"
    USER_ENABLED = "USER_ENABLED"
    USER_DELETED = "USER_DELETED"
    USER_CREATED = "USER_CREATED"
    ROLE_CHANGED = "ROLE_CHANGED"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - an action name, not a credential
    SETTINGS_UPDATED = "SETTINGS_UPDATED"
    MAINTENANCE_ENABLED = "MAINTENANCE_ENABLED"
    MAINTENANCE_DISABLED = "MAINTENANCE_DISABLED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_DELETED = "JOB_DELETED"
    HISTORY_CLEARED = "HISTORY_CLEARED"
    CLEANUP_TRIGGERED = "CLEANUP_TRIGGERED"
    ADMIN_LOGIN = "ADMIN_LOGIN"
