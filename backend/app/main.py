"""FastAPI application factory.

Serves one origin: ``/api/*`` is the JSON API, everything else is the compiled
single-page frontend with history fallback. There is no separate API hostname and
no per-platform subdomain — path-based routing throughout.

Note that the interactive OpenAPI docs live at ``/api/docs``, because ``/docs``
belongs to the user-facing documentation page in the SPA.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import admin as admin_routes
from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import media as media_routes
from app.core.config import REPO_ROOT, settings
from app.core.errors import AppError, RateLimitError, ValidationError
from app.core.logging import get_logger, setup_logging
from app.core.version import VERSION
from app.middleware.http import (
    CSRFMiddleware,
    MaintenanceModeMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)

log = get_logger("slipstream.app")

FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST") or (REPO_ROOT / "frontend" / "dist")).resolve()

# Client-side routes the SPA owns. Anything else that is not a file and not /api
# still falls through to index.html, but listing these documents the contract.
SPA_ROUTES = (
    "/",
    "/login",
    "/register",
    "/account",
    "/history",
    "/docs",
    "/admin",
    "/about",
    "/legal",
    "/privacy",
)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop background machinery."""
    setup_logging()
    settings.ensure_directories()

    log.info(
        "starting %s",
        settings.APP_NAME,
        version=VERSION,
        environment=settings.ENVIRONMENT,
    )

    # Schema + initial admin. Kept in-process so a bare `uvicorn app.main:app`
    # on Windows works with no extra steps.
    if os.getenv("SLIPSTREAM_SKIP_INIT", "").lower() not in {"1", "true", "yes"}:
        from app.db.init_db import init_database

        try:
            await asyncio.to_thread(init_database)
        except Exception as exc:
            log.error("database initialisation failed: %s", exc, exc_info=True)
            raise

    from app.services.extractor import extractor_status, ffmpeg_status
    from app.services.queue import get_queue

    extractor = extractor_status()
    ffmpeg = ffmpeg_status()
    log.info(
        "toolchain",
        extractor=f"{extractor.get('name')} {extractor.get('version')}",
        ffmpeg=ffmpeg["version"] if ffmpeg["available"] else "NOT AVAILABLE",
    )
    if not ffmpeg["available"]:
        log.warning(
            "FFmpeg was not found. MP3 conversion and high-quality video merging "
            "will be unavailable until it is installed."
        )

    queue = get_queue()
    await queue.start()

    stop_cleanup = asyncio.Event()
    from app.services.cleanup import cleanup_loop

    cleanup_task = asyncio.create_task(cleanup_loop(stop_cleanup), name="cleanup-loop")

    app.state.queue = queue
    app.state.ready = True

    try:
        yield
    finally:
        app.state.ready = False
        log.info("shutting down")
        stop_cleanup.set()
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await cleanup_task
        await queue.stop()

        from app.db.session import checkpoint_wal, engine

        await asyncio.to_thread(checkpoint_wal)
        engine.dispose()
        log.info("shutdown complete")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version=VERSION,
        description=(
            "Self-hosted universal media downloader. Processes only publicly " "accessible media."
        ),
        lifespan=lifespan,
        # /docs belongs to the SPA documentation page.
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    _install_middleware(app)
    _install_exception_handlers(app)

    api_prefix = "/api"
    app.include_router(health_routes.router, prefix=api_prefix)
    app.include_router(auth_routes.router, prefix=api_prefix)
    app.include_router(media_routes.router, prefix=api_prefix)
    app.include_router(admin_routes.router, prefix=api_prefix)

    _install_frontend(app)
    return app


def _install_middleware(app: FastAPI) -> None:
    # Starlette applies middleware bottom-up, so the last added runs first.
    # Desired order per request: context -> security headers -> maintenance -> CSRF.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(MaintenanceModeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    origins = settings.cors_origin_list
    if origins:
        # Only needed when the dev frontend runs on a different port, or when an
        # operator deliberately splits the origins. Same-origin needs no CORS.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
            expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
            max_age=600,
        )


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.detail:
            log.info(
                "handled error: %s",
                exc.code,
                request_id=getattr(request.state, "request_id", None),
                detail=exc.detail[:300],
            )
        headers = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(exc.to_payload(), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Report which fields failed, but never echo the submitted values —
        # a password or pasted URL must not bounce back in an error body.
        fields: dict[str, str] = {}
        for error in exc.errors()[:12]:
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            fields[location or "body"] = str(error.get("msg", "Invalid value"))[:200]

        error = ValidationError(meta={"fields": fields})
        return JSONResponse(error.to_payload(), status_code=error.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> Response:
        # A 404 on a non-API path is the SPA deep-link case. /assets is excluded:
        # those filenames are content-hashed, so a miss means a stale reference,
        # and answering it with index.html would make the browser try to parse
        # HTML as JavaScript instead of reporting the real problem.
        if (
            exc.status_code == 404
            and not request.url.path.startswith("/api")
            and not request.url.path.startswith("/assets/")
        ):
            index = FRONTEND_DIST / "index.html"
            if index.is_file():
                return FileResponse(index, status_code=200)
        return JSONResponse(
            {
                "error": {
                    "code": _http_code_name(exc.status_code),
                    "message": str(exc.detail) if exc.detail else "Request failed.",
                    "retryable": exc.status_code >= 500,
                }
            },
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log with a stack trace server-side; return an opaque body to the client.
        log.error(
            "unhandled exception: %s",
            type(exc).__name__,
            request_id=getattr(request.state, "request_id", None),
            exc_info=True,
        )
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected server error occurred.",
                    "retryable": True,
                }
            },
            status_code=500,
        )


def _http_code_name(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "not_authenticated",
        403: "permission_denied",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
        503: "service_unavailable",
    }.get(status_code, "error")


def _install_frontend(app: FastAPI) -> None:
    """Serve the built SPA when it exists.

    In development the frontend runs under Vite on its own port and proxies /api
    here, so a missing dist directory is normal and must not be fatal.
    """
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        log.info(
            "frontend bundle not found at %s — running API-only "
            "(this is expected during development)",
            FRONTEND_DIST,
        )

        @app.get("/", include_in_schema=False)
        async def dev_root() -> JSONResponse:
            return JSONResponse(
                {
                    "app": settings.APP_NAME,
                    "version": VERSION,
                    "status": "api-only",
                    "message": (
                        "The frontend has not been built. Run 'npm run build' in "
                        "frontend/, or use the Vite dev server."
                    ),
                    "docs": "/api/docs",
                    "health": "/api/health",
                }
            )

        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        # Hashed filenames, so these are safe to cache aggressively.
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        # /api is matched by the routers above; anything reaching here is either
        # a real static file or a client-side route.
        candidate = (FRONTEND_DIST / full_path).resolve() if full_path else index
        if (
            full_path
            and candidate.is_file()
            # Confine to the bundle directory: a crafted path must not escape.
            and (candidate == FRONTEND_DIST or FRONTEND_DIST in candidate.parents)
        ):
            return FileResponse(candidate)
        return FileResponse(index)

    log.info("serving frontend from %s", FRONTEND_DIST)


app = create_app()
