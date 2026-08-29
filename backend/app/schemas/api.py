"""Request/response schemas.

Response models are intentionally permissive (services build plain dicts), while
*request* models are strict — they are the trust boundary, so field types,
lengths and allowed values are pinned here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    # Accepts a username or an email address.
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: str
    is_active: bool
    is_admin: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None = None


class SessionResponse(BaseModel):
    user: UserPayload
    csrf_token: str


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(min_length=4, max_length=2048)
    # Influences which container the derived options prefer.
    container: Literal["mp4", "webm"] = "mp4"

    @field_validator("url")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if any(ord(c) < 0x20 for c in value):
            raise ValueError("URL contains control characters")
        return value


class DownloadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(min_length=4, max_length=2048)
    mode: Literal["video", "audio", "image"] = "video"
    # A closed token set, validated against the real formats server-side. The
    # client can never send a raw extractor format selector.
    quality: str = Field(default="best", max_length=8, pattern=r"^(best|\d{2,4})$")
    container: Literal["mp4", "webm", "mp3"] = "mp4"
    # Which slideshow images to include; empty/None means all of them.
    image_indexes: list[int] | None = Field(default=None, max_length=200)

    @field_validator("image_indexes")
    @classmethod
    def _bounded_indexes(cls, value: list[int] | None) -> list[int] | None:
        if not value:
            return None
        if any(i < 0 or i > 999 for i in value):
            raise ValueError("image index out of range")
        return sorted(set(value))


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str | None
    platform: str
    source_domain: str
    title: str | None
    author: str | None
    thumbnail: str | None
    media_type: str
    quality: str | None
    output_format: str | None
    file_size: int | None
    status: str
    error_code: str | None
    created_at: datetime


class Paginated(BaseModel):
    items: list[Any]
    total: int
    page: int
    per_page: int
    pages: int


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    role: Literal["user", "admin"] | None = None
    new_password: str | None = Field(default=None, min_length=10, max_length=256)


class CreateUserRequest(BaseModel):
    """Admin-side account creation.

    Sent as a JSON body rather than query parameters so the password never
    appears in a URL, where reverse proxies and access logs would capture it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=256)
    role: Literal["user", "admin"] = "user"


class UpdateSettingsRequest(BaseModel):
    """Free-form key/value batch, validated against the settings registry."""

    model_config = ConfigDict(extra="forbid")

    settings: dict[str, Any] = Field(min_length=1)

    @field_validator("settings")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 40:
            raise ValueError("too many settings in one request")
        return value


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False
    meta: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorPayload
