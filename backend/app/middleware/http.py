"""HTTP middleware: request context, security headers, CSRF and maintenance mode."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.errors import CSRFError, MaintenanceModeError
from app.core.logging import get_logger
from app.core.security import constant_time_compare

log = get_logger("slipstream.http")

# State-changing methods require CSRF validation when the caller authenticated
# with a cookie. Safe methods do not.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoints reachable before a CSRF cookie can exist.
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/register",
        "/api/health",
        "/api/health/ready",
    }
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, resolve the real client IP, and log the outcome."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        request.state.client_ip = _client_ip(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log.error(
                "%s %s -> unhandled exception in %.1fms",
                request.method,
                request.url.path,
                elapsed,
                request_id=request_id,
            )
            raise

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id

        # One structured line per API request. Query strings are omitted: they
        # can carry the media URL a user pasted.
        if request.url.path.startswith("/api"):
            level_log = log.warning if response.status_code >= 500 else log.info
            level_log(
                "%s %s -> %s in %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
                request_id=request_id,
            )
        return response


def _client_ip(request: Request) -> str:
    """Determine the client IP, honouring exactly TRUSTED_PROXY_COUNT hops.

    Blindly trusting ``X-Forwarded-For`` lets any caller forge an IP and defeat
    rate limiting, so the number of trusted proxies must be configured
    explicitly. With 0, only the socket peer is used.
    """
    direct = request.client.host if request.client else "unknown"
    hops = settings.TRUSTED_PROXY_COUNT
    if hops <= 0:
        return direct

    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return direct

    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return direct
    # The right-most entries were added by our own proxies; step back over them.
    index = max(0, len(chain) - hops)
    return chain[index] if index < len(chain) else chain[0]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply defensive response headers.

    The CSP is deliberately strict. The frontend is a compiled Vite bundle with
    no inline scripts, so ``script-src 'self'`` holds. Media/images come from
    third-party CDNs (thumbnails), which is why those directives are wider.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._csp = "; ".join(
            [
                "default-src 'self'",
                "base-uri 'self'",
                "object-src 'none'",
                "frame-ancestors 'none'",
                "form-action 'self'",
                "script-src 'self'",
                # Tailwind ships a stylesheet, but Vite injects a style tag for
                # HMR in dev and some components set CSS variables inline.
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: blob: https:",
                "media-src 'self' blob: https:",
                "font-src 'self' data:",
                "connect-src 'self'",
                "worker-src 'self' blob:",
                "manifest-src 'self'",
                "upgrade-insecure-requests" if settings.is_production else "",
            ]
        ).strip("; ")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # Do not apply the document CSP to file downloads.
        if not request.url.path.startswith("/api/jobs/") or not request.url.path.endswith("/file"):
            headers.setdefault("Content-Security-Policy", self._csp)

        if settings.is_production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        # Authenticated API responses must never be cached by a shared proxy.
        if request.url.path.startswith("/api") and "cache-control" not in headers:
            headers["Cache-Control"] = "no-store"
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    The session cookie is ``SameSite=Lax``, which already blocks cross-site form
    posts in current browsers. This adds the explicit header check so protection
    does not rest on SameSite alone.

    Requests carrying no session cookie are exempt: a guest download has no
    authority to abuse.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if not session_cookie:
            return await call_next(request)

        cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
        header_token = request.headers.get("x-csrf-token", "")

        if (
            not cookie_token
            or not header_token
            or not constant_time_compare(cookie_token, header_token)
        ):
            log.warning(
                "csrf validation failed",
                request_id=getattr(request.state, "request_id", None),
                path=request.url.path,
            )
            error = CSRFError()
            return JSONResponse(error.to_payload(), status_code=error.status_code)

        return await call_next(request)


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """Serve a maintenance notice to everyone except admins.

    Auth and health endpoints stay open so an administrator can still sign in and
    turn maintenance back off.
    """

    ALWAYS_ALLOWED = (
        "/api/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/admin",
        "/api/config",
    )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if not path.startswith("/api") or path.startswith(self.ALWAYS_ALLOWED):
            return await call_next(request)

        try:
            from app.core.settings_store import store
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                enabled = store.get_bool(db, "maintenance_mode")
            finally:
                db.close()
        except Exception:
            return await call_next(request)

        if not enabled:
            return await call_next(request)

        error = MaintenanceModeError()
        return JSONResponse(error.to_payload(), status_code=error.status_code)
