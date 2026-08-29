"""Authentication service: registration, login, sessions, password changes."""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AccountDisabledError,
    AuthenticationError,
    DuplicateAccountError,
    LastAdminError,
    RegistrationDisabledError,
    ValidationError,
    WeakPasswordError,
)
from app.core.logging import get_logger, log_security_event
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from app.core.settings_store import store
from app.db.base import utcnow
from app.models.user import User, UserRole, UserSession

log = get_logger("slipstream.auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{1,30}[A-Za-z0-9])$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

RESERVED_USERNAMES = frozenset(
    {"admin", "administrator", "root", "system", "slipstream", "api", "support", "me", "null"}
)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def normalize_username(raw: str) -> str:
    return (raw or "").strip()


def validate_username(username: str, *, allow_reserved: bool = False) -> str:
    cleaned = normalize_username(username)
    if not USERNAME_RE.match(cleaned):
        raise ValidationError(
            "Usernames must be 3-32 characters using letters, numbers, dot, dash or underscore.",
            meta={"fields": {"username": "Invalid format."}},
        )
    if not allow_reserved and cleaned.lower() in RESERVED_USERNAMES:
        raise ValidationError(
            "That username is reserved.", meta={"fields": {"username": "Reserved."}}
        )
    return cleaned


def validate_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if len(cleaned) > 320 or not EMAIL_RE.match(cleaned):
        raise ValidationError(
            "Enter a valid email address.", meta={"fields": {"email": "Invalid email."}}
        )
    return cleaned


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register_user(
    db: Session,
    *,
    username: str,
    email: str,
    password: str,
    role: str = UserRole.USER.value,
    enforce_settings: bool = True,
    must_change_password: bool = False,
) -> User:
    if enforce_settings and not store.get_bool(db, "registration_enabled"):
        raise RegistrationDisabledError()

    clean_username = validate_username(username, allow_reserved=not enforce_settings)
    clean_email = validate_email(email)

    check = validate_password_strength(password, username=clean_username)
    if not check.ok:
        raise WeakPasswordError(check.reason)

    existing = db.execute(
        select(User.id).where(
            (func.lower(User.username) == clean_username.lower())
            | (func.lower(User.email) == clean_email)
        )
    ).first()
    if existing:
        raise DuplicateAccountError()

    user = User(
        username=clean_username.lower(),
        display_username=clean_username,
        email=clean_email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=must_change_password,
        password_changed_at=utcnow(),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration of the same name
        db.rollback()
        raise DuplicateAccountError() from exc

    log.info("user registered", user_id=user.id, role=user.role)
    return user


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def authenticate(db: Session, *, identifier: str, password: str) -> User:
    """Verify credentials. Raises on any failure, without revealing which part."""
    lookup = (identifier or "").strip().lower()
    user = db.execute(
        select(User).where((User.username == lookup) | (User.email == lookup))
    ).scalar_one_or_none()

    if user is None:
        # Spend comparable time so response timing does not disclose whether the
        # account exists.
        verify_password(password, _DUMMY_HASH)
        log_security_event("login_failed_unknown_user", identifier_len=len(lookup))
        raise AuthenticationError()

    ok, needs_rehash = verify_password(password, user.password_hash)
    if not ok:
        user.failed_login_count += 1
        db.flush()
        log_security_event("login_failed", user_id=user.id)
        raise AuthenticationError()

    if not user.is_active:
        log_security_event("login_blocked_disabled", user_id=user.id)
        raise AccountDisabledError()

    if needs_rehash:
        # Transparent upgrade from bcrypt or weaker Argon2 parameters.
        user.password_hash = hash_password(password)
        log.info("password hash upgraded", user_id=user.id)

    user.last_login_at = utcnow()
    user.failed_login_count = 0
    db.flush()
    return user


# A real Argon2 hash of a random value, so failed lookups do comparable work.
_DUMMY_HASH = hash_password(generate_token(16))


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def create_session(
    db: Session,
    user: User,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
    lifetime_seconds: int | None = None,
) -> tuple[UserSession, str]:
    """Create a session row and return it with the *plaintext* token.

    The plaintext is returned once, to be placed in an HttpOnly cookie. Only its
    hash is stored.
    """
    token = generate_token(32)
    lifetime = lifetime_seconds or settings.SESSION_LIFETIME

    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(seconds=lifetime),
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:256] or None,
    )
    db.add(session)
    db.flush()
    log.info("session created", user_id=user.id)
    return session, token


def resolve_session(db: Session, token: str) -> tuple[User, UserSession] | None:
    """Look up a live session by its plaintext token."""
    if not token:
        return None
    row = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or not row.is_valid:
        return None

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    # Touch at most once a minute to avoid a write on every request.
    if (utcnow() - row.last_seen_at).total_seconds() > 60:
        row.last_seen_at = utcnow()
        db.flush()
    return user, row


def revoke_session(db: Session, session_row: UserSession) -> None:
    session_row.revoked_at = utcnow()
    db.flush()


def revoke_all_sessions(db: Session, user_id: int, *, keep_id: int | None = None) -> int:
    rows = (
        db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for row in rows:
        if keep_id is not None and row.id == keep_id:
            continue
        row.revoked_at = utcnow()
        count += 1
    db.flush()
    return count


# --------------------------------------------------------------------------- #
# Password change
# --------------------------------------------------------------------------- #
def change_password(
    db: Session,
    user: User,
    *,
    current_password: str,
    new_password: str,
    current_session_id: int | None = None,
) -> None:
    ok, _ = verify_password(current_password, user.password_hash)
    if not ok:
        log_security_event("password_change_rejected", user_id=user.id)
        raise AuthenticationError("Your current password is incorrect.")

    if current_password == new_password:
        raise WeakPasswordError("The new password must be different from the current one.")

    check = validate_password_strength(new_password, username=user.display_username)
    if not check.ok:
        raise WeakPasswordError(check.reason)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    db.flush()

    # Any other session may belong to whoever knew the old password.
    revoked = revoke_all_sessions(db, user.id, keep_id=current_session_id)
    log.info("password changed", user_id=user.id, revoked_sessions=revoked)


def admin_set_password(db: Session, target: User, new_password: str) -> None:
    """Administrative reset: forces the user to choose their own on next login."""
    check = validate_password_strength(new_password, username=target.display_username)
    if not check.ok:
        raise WeakPasswordError(check.reason)
    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    target.password_changed_at = utcnow()
    revoke_all_sessions(db, target.id)
    db.flush()


# --------------------------------------------------------------------------- #
# Admin invariants
# --------------------------------------------------------------------------- #
def count_active_admins(db: Session, *, exclude_user_id: int | None = None) -> int:
    query = (
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN.value, User.is_active.is_(True))
    )
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return int(db.execute(query).scalar() or 0)


def assert_not_last_admin(db: Session, target: User, *, action: str) -> None:
    """Guard the "there must always be one usable admin" invariant."""
    if not target.is_admin or not target.is_active:
        return
    if count_active_admins(db, exclude_user_id=target.id) == 0:
        raise LastAdminError(f"Cannot {action}: this is the only active administrator account.")


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def guest_key_for(ip: str) -> str:
    """Stable pseudonymous identifier for a guest.

    Salted with SECRET_KEY so the stored value cannot be reversed to an IP by
    anyone holding only the database.
    """
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()
    return digest[:32]


def user_to_payload(user: User, *, include_email: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": user.id,
        "username": user.display_username,
        "role": user.role,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }
    if include_email:
        payload["email"] = user.email
    return payload
