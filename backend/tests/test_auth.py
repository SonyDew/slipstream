"""Authentication, password hashing and session behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models.user import User, UserRole, UserSession
from tests.conftest import TEST_PASSWORD, login, make_user


# --------------------------------------------------------------------------- #
# Hashing primitives
# --------------------------------------------------------------------------- #
def test_password_hash_is_argon2id_and_not_plaintext() -> None:
    password = "Sup3rSecret!pass"
    hashed = hash_password(password)

    assert hashed.startswith("$argon2id$")
    assert password not in hashed
    ok, needs_rehash = verify_password(password, hashed)
    assert ok is True
    assert needs_rehash is False
    assert verify_password("wrong-password", hashed)[0] is False


def test_hashes_are_salted_uniquely() -> None:
    assert hash_password("same-password-x1") != hash_password("same-password-x1")


def test_bcrypt_hashes_verify_and_request_upgrade() -> None:
    """Legacy bcrypt hashes keep working and are flagged for rehash."""
    import bcrypt

    password = "LegacyPassw0rd!"
    legacy = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()

    ok, needs_rehash = verify_password(password, legacy)
    assert ok is True
    assert needs_rehash is True
    assert verify_password("nope", legacy)[0] is False


def test_verify_rejects_garbage_hashes() -> None:
    for bad in ("", "not-a-hash", "$unknown$abc", "plaintext"):
        assert verify_password("whatever", bad) == (False, False)


def test_password_strength_policy() -> None:
    assert validate_password_strength("Str0ng&Passphrase").ok is True

    assert validate_password_strength("short").ok is False
    assert validate_password_strength("alllowercaseletters").ok is False
    assert validate_password_strength("password123").ok is False
    # Must not contain the username.
    assert validate_password_strength("alice-Passw0rd", username="alice").ok is False
    assert validate_password_strength("x" * 300).ok is False


def test_stored_admin_password_is_hashed_in_database(db: Session) -> None:
    from app.db.init_db import seed_initial_admin, verify_bootstrap

    admin, used_fallback = seed_initial_admin(db)
    db.commit()

    assert admin is not None
    assert used_fallback is True
    assert admin.password_hash.startswith("$argon2id$")
    assert "oleg2017A!" not in admin.password_hash
    assert admin.must_change_password is True

    # Read the raw column value back to be certain nothing rewrote it.
    raw = db.execute(select(User.password_hash).where(User.id == admin.id)).scalar_one()
    assert raw.startswith("$argon2id$")
    assert raw != "oleg2017A!"

    report = verify_bootstrap()
    assert report["ok"] is True
    assert report["plaintext_stored"] is False
    assert report["hash_algorithm"] == "argon2id"


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def test_register_creates_account_and_session(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": "newbie", "email": "newbie@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["user"]["username"] == "newbie"
    assert body["user"]["role"] == "user"
    assert body["user"]["is_admin"] is False
    assert body["csrf_token"]

    # Session cookie must be HttpOnly; the CSRF cookie must not be.
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("slipstream_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("slipstream_csrf="))
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in session_cookie.lower() or "samesite=lax" in session_cookie.lower()


def test_register_rejects_duplicates(client: TestClient) -> None:
    payload = {"username": "dupe", "email": "dupe@example.com", "password": TEST_PASSWORD}
    assert client.post("/api/auth/register", json=payload).status_code == 201

    again = client.post("/api/auth/register", json=payload)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "duplicate_account"

    # Same email, different username.
    other = client.post(
        "/api/auth/register",
        json={"username": "dupe2", "email": "dupe@example.com", "password": TEST_PASSWORD},
    )
    assert other.status_code == 409


def test_register_rejects_weak_password(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": "weakling", "email": "weak@example.com", "password": "password123"},
    )
    assert response.status_code in (400, 422)


def test_register_rejects_reserved_username(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": "administrator", "email": "a@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_registration_can_be_disabled(client: TestClient, db: Session) -> None:
    from app.core.settings_store import store

    store.update(db, {"registration_enabled": False}, actor="test")
    db.commit()

    response = client.post(
        "/api/auth/register",
        json={"username": "blocked", "email": "b@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "registration_disabled"


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #
def test_login_with_username_and_with_email(client: TestClient, normal_user: User) -> None:
    by_username = client.post(
        "/api/auth/login", json={"username": "alice", "password": TEST_PASSWORD}
    )
    assert by_username.status_code == 200

    by_email = client.post(
        "/api/auth/login", json={"username": "alice@example.com", "password": TEST_PASSWORD}
    )
    assert by_email.status_code == 200
    assert by_email.json()["user"]["username"] == "alice"


def test_login_rejects_bad_password(client: TestClient, normal_user: User) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "alice", "password": "definitely-wrong"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_login_error_does_not_disclose_account_existence(
    client: TestClient, normal_user: User
) -> None:
    unknown = client.post(
        "/api/auth/login", json={"username": "ghost", "password": "whatever12345"}
    )
    wrong = client.post("/api/auth/login", json={"username": "alice", "password": "whatever12345"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_disabled_account_cannot_log_in(client: TestClient, db: Session) -> None:
    make_user(db, username="banned", email="banned@example.com", is_active=False)

    response = client.post(
        "/api/auth/login", json={"username": "banned", "password": TEST_PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


def test_me_returns_null_for_guest(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["user"] is None


def test_me_returns_user_when_signed_in(client: TestClient, normal_user: User) -> None:
    login(client, "alice")
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "alice"


def test_logout_revokes_the_session(client: TestClient, normal_user: User, db: Session) -> None:
    login(client, "alice")
    assert client.get("/api/auth/me").json()["user"] is not None

    assert client.post("/api/auth/logout").status_code == 204

    # Cookie cleared client-side, and the row is revoked server-side.
    assert client.get("/api/auth/me").json()["user"] is None
    rows = (
        db.execute(select(UserSession).where(UserSession.user_id == normal_user.id)).scalars().all()
    )
    assert rows and all(row.revoked_at is not None for row in rows)


def test_expired_session_is_not_accepted(
    client: TestClient, db: Session, normal_user: User
) -> None:
    from datetime import timedelta

    from app.db.base import utcnow

    login(client, "alice")
    row = (
        db.execute(select(UserSession).where(UserSession.user_id == normal_user.id))
        .scalars()
        .first()
    )
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert client.get("/api/auth/me").json()["user"] is None


def test_session_token_is_stored_hashed(client: TestClient, db: Session, normal_user: User) -> None:
    payload = login(client, "alice")
    raw_cookie = client.cookies.get("slipstream_session")
    assert raw_cookie

    row = (
        db.execute(select(UserSession).where(UserSession.user_id == normal_user.id))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.token_hash != raw_cookie
    assert len(row.token_hash) == 64  # sha256 hex

    from app.core.security import hash_token

    assert row.token_hash == hash_token(raw_cookie)
    assert payload["csrf_token"]


# --------------------------------------------------------------------------- #
# Password change
# --------------------------------------------------------------------------- #
def test_change_password_requires_current_password(client: TestClient, normal_user: User) -> None:
    login(client, "alice")
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong-one", "new_password": "BrandNewPass!9"},
    )
    assert response.status_code == 401


def test_change_password_succeeds_and_invalidates_other_sessions(
    client: TestClient, db: Session, normal_user: User
) -> None:
    # A second, independent browser session.
    other = TestClient(client.app, raise_server_exceptions=False)
    login(other, "alice")
    assert other.get("/api/auth/me").json()["user"] is not None

    login(client, "alice")
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "BrandNewPass!9"},
    )
    assert response.status_code == 204

    # Current session survives; the other one is revoked.
    assert client.get("/api/auth/me").json()["user"] is not None
    assert other.get("/api/auth/me").json()["user"] is None

    # Old credential no longer works, new one does.
    fresh = TestClient(client.app, raise_server_exceptions=False)
    assert (
        fresh.post(
            "/api/auth/login", json={"username": "alice", "password": TEST_PASSWORD}
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/api/auth/login", json={"username": "alice", "password": "BrandNewPass!9"}
        ).status_code
        == 200
    )


def test_change_password_rejects_reuse_and_weak_values(
    client: TestClient, normal_user: User
) -> None:
    login(client, "alice")

    same = client.post(
        "/api/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
    )
    assert same.status_code == 400

    weak = client.post(
        "/api/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "password123"},
    )
    assert weak.status_code in (400, 422)


def test_change_password_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "x" * 12, "new_password": "BrandNewPass!9"},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #
def test_csrf_header_required_for_authenticated_writes(
    client: TestClient, normal_user: User
) -> None:
    login(client, "alice")
    client.headers.pop("X-CSRF-Token", None)

    response = client.delete("/api/history")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_csrf_rejects_mismatched_token(client: TestClient, normal_user: User) -> None:
    login(client, "alice")
    client.headers["X-CSRF-Token"] = "not-the-right-token"

    response = client.delete("/api/history")
    assert response.status_code == 403


def test_guest_writes_do_not_require_csrf(client: TestClient) -> None:
    """A guest has no session, so there is no cross-site authority to protect."""
    response = client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"})
    # Rejected for being a blocked target, not for CSRF.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "blocked_target"


# --------------------------------------------------------------------------- #
# Admin invariants at the service level
# --------------------------------------------------------------------------- #
def test_last_admin_cannot_be_demoted_or_disabled(db: Session) -> None:
    from app.core.errors import LastAdminError
    from app.services.auth import assert_not_last_admin, count_active_admins

    only_admin = make_user(db, username="solo", email="solo@example.com", role=UserRole.ADMIN.value)
    assert count_active_admins(db) == 1

    with pytest.raises(LastAdminError):
        assert_not_last_admin(db, only_admin, action="disable this account")

    second = make_user(db, username="second", email="second@example.com", role=UserRole.ADMIN.value)
    assert count_active_admins(db) == 2
    # With two admins, either may be changed.
    assert_not_last_admin(db, only_admin, action="disable this account")

    second.is_active = False
    db.commit()
    with pytest.raises(LastAdminError):
        assert_not_last_admin(db, only_admin, action="disable this account")
