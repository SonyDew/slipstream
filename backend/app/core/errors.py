"""Application error taxonomy.

Every failure the user can trigger maps to an :class:`AppError` subclass with a
stable machine code and a human-readable message that is safe to show. Raw
exception text and stack traces never leave the server.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected, user-presentable failures."""

    code: str = "internal_error"
    status_code: int = 400
    message: str = "Something went wrong."
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        # detail is for server-side logs only; never serialised to the client.
        self.detail = detail
        self.meta = meta or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }
        if self.meta:
            payload["error"]["meta"] = self.meta
        return payload


# --------------------------------------------------------------------------- #
# Input / URL problems
# --------------------------------------------------------------------------- #
class InvalidURLError(AppError):
    code = "invalid_url"
    status_code = 400
    message = "That does not look like a valid link. Paste a full https:// URL."


class UnsupportedURLError(AppError):
    code = "unsupported_url"
    status_code = 400
    message = "This site is not supported yet."


class BlockedTargetError(AppError):
    code = "blocked_target"
    status_code = 400
    message = "That address is not allowed."


class PlatformDisabledError(AppError):
    code = "platform_disabled"
    status_code = 403
    message = "Downloads from this platform are currently disabled by the administrator."


# --------------------------------------------------------------------------- #
# Extraction problems
# --------------------------------------------------------------------------- #
class MediaUnavailableError(AppError):
    code = "media_unavailable"
    status_code = 404
    message = "This media is unavailable. It may have been deleted or made private."


class PrivateContentError(AppError):
    code = "private_content"
    status_code = 403
    message = (
        "This content is private or restricted. Slipstream only handles publicly "
        "accessible media."
    )


class AuthRequiredContentError(AppError):
    code = "auth_required_content"
    status_code = 403
    message = "This content requires signing in on the source platform, so it cannot be processed."


class GeoRestrictedError(AppError):
    code = "geo_restricted"
    status_code = 403
    message = "This media is not available from the region this server runs in."


class ExtractorFailureError(AppError):
    code = "extractor_failure"
    status_code = 502
    message = (
        "The extractor could not read this link. The platform may have changed; "
        "please try again later."
    )
    retryable = True


class PlatformTemporarilyUnsupportedError(AppError):
    code = "platform_temporarily_unsupported"
    status_code = 503
    message = "This platform is temporarily unsupported while the extractor is updated."
    retryable = True


class DRMProtectedError(AppError):
    code = "drm_protected"
    status_code = 403
    message = "This media is DRM-protected and cannot be processed."


# --------------------------------------------------------------------------- #
# Processing problems
# --------------------------------------------------------------------------- #
class FFmpegError(AppError):
    code = "ffmpeg_failure"
    status_code = 500
    message = "Media conversion failed. Please try a different quality or format."
    retryable = True


class FFmpegMissingError(AppError):
    code = "ffmpeg_missing"
    status_code = 503
    message = "FFmpeg is not installed on the server, so this conversion is unavailable."


class NetworkTimeoutError(AppError):
    code = "network_timeout"
    status_code = 504
    message = "The source site took too long to respond. Please try again."
    retryable = True


class FileTooLargeError(AppError):
    code = "file_too_large"
    status_code = 413
    message = "This file exceeds the maximum allowed size."


class VideoTooLongError(AppError):
    code = "video_too_long"
    status_code = 413
    message = "This video is longer than the maximum allowed duration."


class NoSuitableFormatError(AppError):
    code = "no_suitable_format"
    status_code = 400
    message = "The requested quality is not available for this media."


# --------------------------------------------------------------------------- #
# Job problems
# --------------------------------------------------------------------------- #
class JobNotFoundError(AppError):
    code = "job_not_found"
    status_code = 404
    message = "This job no longer exists."


class JobNotReadyError(AppError):
    code = "job_not_ready"
    status_code = 409
    message = "This download is still being prepared."
    retryable = True


class DownloadExpiredError(AppError):
    code = "download_expired"
    status_code = 410
    message = "This download has expired. Please analyse the link again."


class QueueFullError(AppError):
    code = "queue_full"
    status_code = 503
    message = "The server is busy right now. Please try again in a moment."
    retryable = True


class JobCancelledError(AppError):
    code = "job_cancelled"
    status_code = 409
    message = "This job was cancelled."


# --------------------------------------------------------------------------- #
# Auth / authorisation
# --------------------------------------------------------------------------- #
class AuthenticationError(AppError):
    code = "authentication_failed"
    status_code = 401
    message = "Incorrect username or password."


class NotAuthenticatedError(AppError):
    code = "not_authenticated"
    status_code = 401
    message = "Please sign in to continue."


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status_code = 403
    message = "You do not have permission to do that."


class AccountDisabledError(AppError):
    code = "account_disabled"
    status_code = 403
    message = "This account has been disabled."


class RegistrationDisabledError(AppError):
    code = "registration_disabled"
    status_code = 403
    message = "New registrations are currently disabled."


class GuestDownloadsDisabledError(AppError):
    code = "guest_downloads_disabled"
    status_code = 403
    message = "Guest downloads are disabled. Please sign in to continue."


class DuplicateAccountError(AppError):
    code = "duplicate_account"
    status_code = 409
    message = "That username or email is already registered."


class WeakPasswordError(AppError):
    code = "weak_password"
    status_code = 400
    message = "Please choose a stronger password."


class PasswordChangeRequiredError(AppError):
    code = "password_change_required"
    status_code = 403
    message = (
        "You are still using the temporary administrator password. "
        "Change it before performing administrator actions."
    )


class CSRFError(AppError):
    code = "csrf_failed"
    status_code = 403
    message = "Your session token expired. Please refresh the page and try again."


class LastAdminError(AppError):
    code = "last_admin"
    status_code = 409
    message = "You cannot remove or disable the last remaining administrator."


# --------------------------------------------------------------------------- #
# Throttling / availability
# --------------------------------------------------------------------------- #
class RateLimitError(AppError):
    code = "rate_limited"
    status_code = 429
    message = "Rate limit reached. Please wait before trying again."
    retryable = True

    def __init__(self, retry_after: int = 60, message: str | None = None) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(message, meta={"retry_after": self.retry_after})


class MaintenanceModeError(AppError):
    code = "maintenance_mode"
    status_code = 503
    message = "Slipstream is in maintenance mode. Please check back shortly."
    retryable = True


class ValidationError(AppError):
    code = "validation_error"
    status_code = 422
    message = "Some of the submitted values are invalid."
