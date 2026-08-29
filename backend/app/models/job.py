"""Download jobs — the unit of work for the queue."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONEncodedDict, TimestampMixin, UTCDateTime, utcnow

if TYPE_CHECKING:
    from app.models.user import User


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> set[str]:
        return {cls.READY.value, cls.FAILED.value, cls.EXPIRED.value, cls.CANCELLED.value}

    @classmethod
    def active(cls) -> set[str]:
        return {
            cls.QUEUED.value,
            cls.ANALYZING.value,
            cls.DOWNLOADING.value,
            cls.PROCESSING.value,
        }


class MediaType(str, enum.Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    IMAGE_SET = "image_set"
    UNKNOWN = "unknown"


class DownloadJob(Base, TimestampMixin):
    __tablename__ = "download_jobs"
    __table_args__ = (
        Index("ix_download_jobs_status_created", "status", "created_at"),
        Index("ix_download_jobs_user_created", "user_id", "created_at"),
        Index("ix_download_jobs_expires", "expires_at"),
        Index("ix_download_jobs_claim", "status", "id"),
    )

    # UUID4 hex string: unguessable, so possession of the id is a capability to
    # fetch the resulting file (guests have no account to scope it to).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Salted hash of the guest IP — enough to rate-limit and audit, not enough
    # to reconstruct the address from a database dump.
    guest_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    status: Mapped[str] = mapped_column(
        String(16), default=JobStatus.QUEUED.value, nullable=False, index=True
    )

    # -- request ---------------------------------------------------------- #
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Host only. Shown in admin instead of the full URL so tracking parameters
    # and tokens embedded in query strings are not put on screen.
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    media_type: Mapped[str] = mapped_column(
        String(16), default=MediaType.VIDEO.value, nullable=False
    )
    requested_quality: Mapped[str] = mapped_column(String(32), default="best", nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), default="mp4", nullable=False)
    # Which images a user picked from a slideshow; None means "all".
    selected_images: Mapped[dict[str, Any] | None] = mapped_column(JSONEncodedDict, nullable=True)

    # -- resolved metadata ------------------------------------------------ #
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extractor: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- output ----------------------------------------------------------- #
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # -- progress / lifecycle --------------------------------------------- #
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Set once the file has actually been served, for the "downloaded" metric.
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User | None] = relationship(back_populates="jobs")

    # -- helpers ---------------------------------------------------------- #
    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.terminal()

    @property
    def is_downloadable(self) -> bool:
        if self.status != JobStatus.READY.value or not self.file_path:
            return False
        return not self.is_expired

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= utcnow()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DownloadJob id={self.id} status={self.status} platform={self.platform}>"
