"""FastAPI dependencies: authentication, authorisation, rate limiting, cookies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    GuestDownloadsDisabledError,
    NotAuthenticatedError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    RateLimitError,
)
from app.core.logging import get_logger
from app.core.ratelimit import client_identity, limiter
from app.core.security import generate_token
from app.core.settings_store import store
from app.db.session import SessionLocal
from app.models.user import User, UserSession
from app.services.auth import guest_key_for, resolve_session

log = get_logger("slipstream.deps")

HOUR = 3600


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


# --------------------------------------------------------------------------- #
# Request identity
# --------------------------------------------------------------------------- #
def client_ip(request: Request) -> str:
    return getattr(request.state, "client_ip", None) or (
        request.client.host if request.client else "unknown"
    )


ClientIP = Annotated[str, Depends(client_ip)]


class AuthContext:
    """Resolved caller identity for one request."""

    __slots__ = ("guest_key", "ip", "session", "user")

    def __init__(
        self,
        user: User | None,
        session: UserSession | None,
        ip: str,
    ) -> None:
        self.user = user
        self.session = session
        self.ip = ip
        self.guest_key = None if user else guest_key_for(ip)

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    @property
    def is_admin(self) -> bool:
        return self.user is not None and self.user.is_admin

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    @property
    def rate_key(self) -> str:
        return client_identity(self.ip, self.user_id)


def get_auth_context(request: Request, db: DbSession) -> AuthContext:
    """Resolve the session cookie into a user, or an anonymous context."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
    ip = client_ip(request)

    if not token:
        return AuthContext(None, None, ip)

    resolved = resolve_session(db, token)
    if resolved is None:
        return AuthContext(None, None, ip)

    user, session_row = resolved
    request.state.user_id = user.id
    return AuthContext(user, session_row, ip)


Auth = Annotated[AuthContext, Depends(get_auth_context)]


def require_user(auth: Auth) -> AuthContext:
    if auth.user is None:
        raise NotAuthenticatedError()
    return auth


RequireUser = Annotated[AuthContext, Depends(require_user)]


def require_admin(auth: Auth) -> AuthContext:
    if auth.user is None:
        raise NotAuthenticatedError()
    if not auth.user.is_admin:
        log.warning(
            "non-admin attempted an admin endpoint",
            user_id=auth.user.id,
        )
        raise PermissionDeniedError("Administrator access is required.")
    return auth


RequireAdmin = Annotated[AuthContext, Depends(require_admin)]


def require_admin_verified(auth: RequireAdmin) -> AuthContext:
    """Admin *and* not still using the bootstrap password.

    Read-only admin views use :data:`RequireAdmin`; anything that mutates state
    uses this so a stolen bootstrap credential cannot change the system.
    """
    if auth.user is not None and auth.user.must_change_password:
        raise PasswordChangeRequiredError()
    return auth


RequireAdminVerified = Annotated[AuthContext, Depends(require_admin_verified)]


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def set_session_cookies(response: Response, token: str, *, csrf_token: str | None = None) -> str:
    """Attach the session + CSRF cookies. Returns the CSRF token."""
    csrf = csrf_token or generate_token(24)

    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_LIFETIME,
        httponly=True,  # never readable from JavaScript
        secure=bool(settings.COOKIE_SECURE),
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )
    # Deliberately readable by JS: the SPA must echo it in the X-CSRF-Token
    # header for the double-submit check.
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf,
        max_age=settings.SESSION_LIFETIME,
        httponly=False,
        secure=bool(settings.COOKIE_SECURE),
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            path="/",
            secure=bool(settings.COOKIE_SECURE),
            samesite=settings.COOKIE_SAMESITE,
        )


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
def _limit_for(db: Session, auth: AuthContext, kind: str) -> int:
    if auth.is_admin:
        return store.get_int(db, "rate_limit_admin")
    if auth.is_authenticated:
        key = "rate_limit_user_download" if kind == "download" else "rate_limit_user"
    else:
        key = "rate_limit_guest_download" if kind == "download" else "rate_limit_guest"
    return store.get_int(db, key)


def _apply(db: Session, auth: AuthContext, kind: str, response: Response | None = None) -> None:
    limit = _limit_for(db, auth, kind)
    result = limiter.check(f"{kind}:{auth.rate_key}", limit, HOUR)

    if response is not None and limit > 0:
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, result.remaining))

    if not result.allowed:
        log.info("rate limited", kind=kind, authenticated=auth.is_authenticated)
        minutes = max(1, result.retry_after // 60)
        raise RateLimitError(
            result.retry_after,
            f"You have reached the {kind} limit of {result.limit} per hour. "
            f"Try again in about {minutes} minute{'s' if minutes != 1 else ''}"
            + (" or sign in for higher limits." if not auth.is_authenticated else "."),
        )


def rate_limit_analyze(auth: Auth, db: DbSession, response: Response) -> None:
    _apply(db, auth, "analyze", response)


def rate_limit_download(auth: Auth, db: DbSession, response: Response) -> None:
    """Download limit, plus the guest-downloads-enabled policy check."""
    if not auth.is_authenticated and not store.get_bool(db, "guest_downloads_enabled"):
        raise GuestDownloadsDisabledError()
    _apply(db, auth, "download", response)


def rate_limit_auth(request: Request, db: DbSession) -> None:
    """Per-IP throttle on credential endpoints, independent of account limits."""
    ip = client_ip(request)
    result = limiter.check(f"auth:ip:{ip}", settings.RATE_LIMIT_AUTH, HOUR)
    if not result.allowed:
        log.warning("authentication rate limit hit")
        raise RateLimitError(
            result.retry_after,
            "Too many sign-in attempts from this address. Please wait and try again.",
        )


RateLimitAnalyze = Annotated[None, Depends(rate_limit_analyze)]
RateLimitDownload = Annotated[None, Depends(rate_limit_download)]
RateLimitAuth = Annotated[None, Depends(rate_limit_auth)]
