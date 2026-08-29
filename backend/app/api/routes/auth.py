"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import (
    Auth,
    DbSession,
    RateLimitAuth,
    RequireUser,
    clear_session_cookies,
    client_ip,
    set_session_cookies,
)
from app.core.config import settings
from app.core.errors import RegistrationDisabledError
from app.core.logging import get_logger, log_security_event
from app.core.security import generate_token
from app.core.settings_store import store
from app.schemas.api import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    SessionResponse,
)
from app.services.auth import (
    authenticate,
    change_password,
    create_session,
    register_user,
    revoke_all_sessions,
    revoke_session,
    user_to_payload,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("slipstream.api.auth")


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    _rate: RateLimitAuth,
) -> dict:
    """Create an account and sign in immediately."""
    if not store.get_bool(db, "registration_enabled"):
        raise RegistrationDisabledError()

    user = register_user(
        db,
        username=payload.username,
        email=payload.email,
        password=payload.password,
    )
    session_row, token = create_session(
        db,
        user,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    csrf = set_session_cookies(response, token)
    log.info("registration completed", user_id=user.id)
    return {"user": user_to_payload(user), "csrf_token": csrf}


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    _rate: RateLimitAuth,
) -> dict:
    user = authenticate(db, identifier=payload.username, password=payload.password)
    session_row, token = create_session(
        db,
        user,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    csrf = set_session_cookies(response, token)
    if user.is_admin:
        log_security_event("admin_login", user_id=user.id)
    return {"user": user_to_payload(user), "csrf_token": csrf}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: Auth, response: Response, db: DbSession) -> Response:
    """Revoke the current session. Safe to call when already signed out."""
    if auth.session is not None:
        revoke_session(db, auth.session)
        db.commit()
    clear_session_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))


@router.get("/me")
def me(auth: Auth, response: Response, request: Request) -> dict:
    """Current session state. Returns ``user: null`` for guests."""
    if auth.user is None:
        return {"user": None, "csrf_token": None}

    # Re-issue the CSRF cookie if the browser lost it but kept the session.
    existing_csrf = request.cookies.get(settings.CSRF_COOKIE_NAME)
    csrf = existing_csrf or generate_token(24)
    if not existing_csrf:
        set_session_cookies(
            response,
            request.cookies.get(settings.SESSION_COOKIE_NAME, ""),
            csrf_token=csrf,
        )

    return {"user": user_to_payload(auth.user), "csrf_token": csrf}


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: ChangePasswordRequest,
    auth: RequireUser,
    db: DbSession,
    response: Response,
) -> Response:
    """Change the signed-in user's password.

    Every other session for the account is revoked; the current one survives so
    the user is not thrown out of the page they are on.
    """
    assert auth.user is not None
    change_password(
        db,
        auth.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_session_id=auth.session.id if auth.session else None,
    )
    db.commit()
    log_security_event("password_changed", user_id=auth.user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_everywhere(auth: RequireUser, db: DbSession, response: Response) -> Response:
    assert auth.user is not None
    revoke_all_sessions(db, auth.user.id)
    db.commit()
    clear_session_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))
