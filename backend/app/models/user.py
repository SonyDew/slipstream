"""User accounts and authentication sessions."""

from __future__ import annotations

import enum
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime, utcnow

if TYPE_CHECKING:
    from app.models.job import DownloadJob


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Stored lowercase for case-insensitive uniqueness on SQLite, which has no
    # citext. `display_username` keeps the casing the user chose.
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    # Argon2id PHC string. Never a plaintext password, never logged.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(String(16), default=UserRole.USER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Set when the account was seeded with the temporary bootstrap password.
    # Privileged actions are refused until the admin rotates it.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list[DownloadJob]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    # -- helpers --------------------------------------------------------- #
    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username!r} role={self.role}>"


class UserSession(Base):
    """Server-side session record backing the HttpOnly session cookie.

    Only a SHA-256 hash of the token is stored, so a database leak does not hand
    an attacker usable sessions.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Truncated/coarse client metadata, kept for the "your sessions" view and
    # for security auditing. Not used for authorisation decisions.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at > utcnow()

    @staticmethod
    def expiry_from_now(lifetime_seconds: int) -> datetime:
        return utcnow() + timedelta(seconds=lifetime_seconds)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserSession id={self.id} user_id={self.user_id}>"
