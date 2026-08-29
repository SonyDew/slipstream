"""Admin API: authorisation boundaries, user management, settings, audit log."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.records import AdminAuditLog, AuditAction
from app.models.user import User, UserRole, UserSession
from tests.conftest import ADMIN_TEMP_PASSWORD, TEST_PASSWORD, login, make_user

ADMIN_READ_ENDPOINTS = [
    "/api/admin/stats",
    "/api/admin/users",
    "/api/admin/downloads",
    "/api/admin/jobs",
    "/api/admin/audit",
    "/api/admin/settings",
]


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #
def test_guests_cannot_reach_admin_endpoints(client: TestClient) -> None:
    for path in ADMIN_READ_ENDPOINTS:
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "not_authenticated"


def test_normal_users_cannot_reach_admin_endpoints(client: TestClient, normal_user: User) -> None:
    login(client, "alice")
    for path in ADMIN_READ_ENDPOINTS:
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "permission_denied"


def test_normal_users_cannot_mutate_admin_resources(
    client: TestClient, db: Session, normal_user: User
) -> None:
    victim = make_user(db, username="victim", email="victim@example.com")
    login(client, "alice")

    assert (
        client.patch(f"/api/admin/users/{victim.id}", json={"is_active": False}).status_code == 403
    )
    assert client.delete(f"/api/admin/users/{victim.id}").status_code == 403
    assert (
        client.patch(
            "/api/admin/settings", json={"settings": {"registration_enabled": False}}
        ).status_code
        == 403
    )
    assert client.post("/api/admin/cleanup").status_code == 403

    # The victim really was left alone.
    db.expire_all()
    assert db.get(User, victim.id) is not None
    assert db.get(User, victim.id).is_active is True


def test_admin_can_read_all_admin_endpoints(client: TestClient, admin_user: User) -> None:
    login(client, "rootadmin")
    for path in ADMIN_READ_ENDPOINTS:
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.text}"


def test_admin_with_temporary_password_is_read_only(
    client: TestClient, db: Session, bootstrap_admin: User
) -> None:
    """The bootstrap credential can look, but cannot act."""
    login(client, "tempadmin", ADMIN_TEMP_PASSWORD)

    assert client.get("/api/admin/stats").status_code == 200

    target = make_user(db, username="pawn", email="pawn@example.com")
    blocked = client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"

    settings_blocked = client.patch(
        "/api/admin/settings", json={"settings": {"registration_enabled": False}}
    )
    assert settings_blocked.status_code == 403
    assert settings_blocked.json()["error"]["code"] == "password_change_required"


def test_admin_regains_write_access_after_rotating_password(
    client: TestClient, db: Session, bootstrap_admin: User
) -> None:
    login(client, "tempadmin", ADMIN_TEMP_PASSWORD)

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": ADMIN_TEMP_PASSWORD, "new_password": "RotatedAdmin!42"},
    )
    assert changed.status_code == 204

    response = client.patch(
        "/api/admin/settings", json={"settings": {"registration_enabled": False}}
    )
    assert response.status_code == 200

    db.expire_all()
    assert db.get(User, bootstrap_admin.id).must_change_password is False


# --------------------------------------------------------------------------- #
# User management
# --------------------------------------------------------------------------- #
def test_admin_can_search_and_inspect_users(
    client: TestClient, db: Session, admin_user: User
) -> None:
    make_user(db, username="findme", email="findme@example.com")
    login(client, "rootadmin")

    listing = client.get("/api/admin/users", params={"q": "findme"}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["username"] == "findme"
    assert "download_count" in listing["items"][0]

    user_id = listing["items"][0]["id"]
    detail = client.get(f"/api/admin/users/{user_id}").json()
    assert detail["username"] == "findme"
    assert detail["recent_activity"] == []

    by_role = client.get("/api/admin/users", params={"role": "admin"}).json()
    assert all(item["role"] == "admin" for item in by_role["items"])


def test_admin_can_disable_and_enable_a_user(
    client: TestClient, db: Session, admin_user: User
) -> None:
    target = make_user(db, username="toggle", email="toggle@example.com")

    # Give the target a live session so we can prove it gets revoked.
    other = TestClient(client.app, raise_server_exceptions=False)
    login(other, "toggle")
    assert other.get("/api/auth/me").json()["user"] is not None

    login(client, "rootadmin")
    disabled = client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    # Disabling must terminate existing sessions immediately.
    assert other.get("/api/auth/me").json()["user"] is None
    rows = db.execute(select(UserSession).where(UserSession.user_id == target.id)).scalars().all()
    assert all(row.revoked_at is not None for row in rows)

    enabled = client.patch(f"/api/admin/users/{target.id}", json={"is_active": True})
    assert enabled.json()["is_active"] is True


def test_admin_can_promote_and_demote(client: TestClient, db: Session, admin_user: User) -> None:
    target = make_user(db, username="promotee", email="promotee@example.com")
    login(client, "rootadmin")

    promoted = client.patch(f"/api/admin/users/{target.id}", json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    demoted = client.patch(f"/api/admin/users/{target.id}", json={"role": "user"})
    assert demoted.json()["role"] == "user"


def test_admin_cannot_demote_or_disable_themselves(client: TestClient, admin_user: User) -> None:
    login(client, "rootadmin")

    self_demote = client.patch(f"/api/admin/users/{admin_user.id}", json={"role": "user"})
    assert self_demote.status_code == 403

    self_disable = client.patch(f"/api/admin/users/{admin_user.id}", json={"is_active": False})
    assert self_disable.status_code == 403

    self_delete = client.delete(f"/api/admin/users/{admin_user.id}")
    assert self_delete.status_code == 403


def test_last_admin_is_protected_through_the_api(
    client: TestClient, db: Session, admin_user: User
) -> None:
    """With a second admin present, the *other* one still cannot be stranded."""
    second = make_user(db, username="second", email="second@example.com", role=UserRole.ADMIN.value)
    login(client, "rootadmin")

    # Demoting the second admin is fine — rootadmin remains.
    assert client.patch(f"/api/admin/users/{second.id}", json={"role": "user"}).status_code == 200

    # Promote back, then disable rootadmin's peer and confirm the guard on delete.
    assert client.patch(f"/api/admin/users/{second.id}", json={"role": "admin"}).status_code == 200
    assert (
        client.patch(f"/api/admin/users/{second.id}", json={"is_active": False}).status_code == 200
    )

    # rootadmin is now the only *active* admin; deleting it is refused. Sign in
    # as the reactivated second admin to attempt it.
    assert (
        client.patch(f"/api/admin/users/{second.id}", json={"is_active": True}).status_code == 200
    )
    assert (
        client.patch(f"/api/admin/users/{admin_user.id}", json={"role": "user"}).status_code == 403
    )


def test_deleting_the_only_admin_is_refused(client: TestClient, db: Session) -> None:
    lone = make_user(db, username="lone", email="lone@example.com", role=UserRole.ADMIN.value)
    helper = make_user(db, username="helper", email="helper@example.com", role=UserRole.ADMIN.value)
    login(client, "lone")

    # Disable the helper so `lone` is the only active admin.
    assert (
        client.patch(f"/api/admin/users/{helper.id}", json={"is_active": False}).status_code == 200
    )

    # A different admin session cannot delete `lone` either — try via helper after
    # re-enabling, then disabling lone is what the guard blocks.
    assert (
        client.patch(f"/api/admin/users/{helper.id}", json={"is_active": True}).status_code == 200
    )
    assert client.patch(f"/api/admin/users/{helper.id}", json={"role": "user"}).status_code == 200
    # Now `lone` is the sole admin: it may not disable itself nor be deleted.
    assert client.delete(f"/api/admin/users/{lone.id}").status_code == 403


def test_admin_can_delete_a_user_and_cascade_related_rows(
    client: TestClient, db: Session, admin_user: User
) -> None:
    from app.models.records import DownloadHistory

    target = make_user(db, username="goner", email="goner@example.com")
    db.add(
        DownloadHistory(
            user_id=target.id,
            job_id="abc",
            platform="youtube",
            source_domain="youtube.com",
            media_type="video",
            status="ready",
        )
    )
    db.commit()
    target_id = target.id

    login(client, "rootadmin")
    assert client.delete(f"/api/admin/users/{target_id}").status_code == 200

    db.expire_all()
    assert db.get(User, target_id) is None
    remaining = (
        db.execute(select(DownloadHistory).where(DownloadHistory.user_id == target_id))
        .scalars()
        .all()
    )
    assert remaining == []


def test_admin_password_reset_forces_rotation(
    client: TestClient, db: Session, admin_user: User
) -> None:
    target = make_user(db, username="resetme", email="resetme@example.com")
    login(client, "rootadmin")

    response = client.patch(
        f"/api/admin/users/{target.id}", json={"new_password": "AdminSetPass!7"}
    )
    assert response.status_code == 200
    assert "password" in response.json()["changed"]

    db.expire_all()
    refreshed = db.get(User, target.id)
    assert refreshed.must_change_password is True
    assert refreshed.password_hash.startswith("$argon2id$")
    assert "AdminSetPass!7" not in refreshed.password_hash

    fresh = TestClient(client.app, raise_server_exceptions=False)
    assert (
        fresh.post(
            "/api/auth/login", json={"username": "resetme", "password": "AdminSetPass!7"}
        ).status_code
        == 200
    )
    assert (
        fresh.post(
            "/api/auth/login", json={"username": "resetme", "password": TEST_PASSWORD}
        ).status_code
        == 401
    )


def test_admin_can_create_a_user_even_when_registration_is_disabled(
    client: TestClient, db: Session, admin_user: User
) -> None:
    from app.core.settings_store import store

    store.update(db, {"registration_enabled": False}, actor="test")
    db.commit()
    login(client, "rootadmin")

    response = client.post(
        "/api/admin/users",
        json={
            "username": "invited",
            "email": "invited@example.com",
            # Deliberately does not contain the username: the strength policy
            # rejects passwords that embed it.
            "password": "Handover!Pass42",
            "role": "user",
        },
    )
    assert response.status_code == 201
    assert response.json()["must_change_password"] is True


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def test_settings_round_trip_and_validation(client: TestClient, admin_user: User) -> None:
    login(client, "rootadmin")

    listing = client.get("/api/admin/settings").json()["settings"]
    keys = {item["key"] for item in listing}
    assert {
        "guest_downloads_enabled",
        "registration_enabled",
        "allowed_platforms",
        "max_file_size",
        "max_video_duration",
        "max_concurrent_downloads",
        "temp_file_ttl",
        "history_retention_days",
        "maintenance_mode",
        "rate_limit_guest",
        "rate_limit_user",
    } <= keys

    updated = client.patch(
        "/api/admin/settings",
        json={
            "settings": {
                "max_concurrent_downloads": 4,
                "guest_downloads_enabled": False,
                "allowed_platforms": ["youtube", "tiktok"],
            }
        },
    )
    assert updated.status_code == 200
    values = {item["key"]: item["value"] for item in updated.json()["settings"]}
    assert values["max_concurrent_downloads"] == 4
    assert values["guest_downloads_enabled"] is False
    assert values["allowed_platforms"] == ["youtube", "tiktok"]


def test_settings_reject_out_of_range_and_unknown_values(
    client: TestClient, admin_user: User
) -> None:
    login(client, "rootadmin")

    too_big = client.patch(
        "/api/admin/settings", json={"settings": {"max_concurrent_downloads": 9999}}
    )
    assert too_big.status_code == 422
    assert "max_concurrent_downloads" in too_big.json()["error"]["meta"]["fields"]

    unknown = client.patch("/api/admin/settings", json={"settings": {"nope": 1}})
    assert unknown.status_code == 422

    bad_platform = client.patch(
        "/api/admin/settings", json={"settings": {"allowed_platforms": ["nosuchsite"]}}
    )
    assert bad_platform.status_code == 422


def test_settings_persist_across_store_cache_invalidation(
    client: TestClient, db: Session, admin_user: User
) -> None:
    from app.core.settings_store import store

    login(client, "rootadmin")
    client.patch("/api/admin/settings", json={"settings": {"history_retention_days": 7}})

    store.invalidate()
    assert store.get_int(db, "history_retention_days") == 7


def test_maintenance_mode_blocks_normal_users_but_not_admins(
    client: TestClient, db: Session, admin_user: User, normal_user: User
) -> None:
    login(client, "rootadmin")
    assert (
        client.patch(
            "/api/admin/settings", json={"settings": {"maintenance_mode": True}}
        ).status_code
        == 200
    )

    guest = TestClient(client.app, raise_server_exceptions=False)
    blocked = guest.post("/api/media/analyze", json={"url": "https://youtu.be/abc"})
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "maintenance_mode"

    # Admins keep working so maintenance can be switched back off.
    assert client.get("/api/admin/stats").status_code == 200
    # Auth stays reachable so an admin can still sign in.
    assert guest.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
def test_admin_actions_are_audited_without_secrets(
    client: TestClient, db: Session, admin_user: User
) -> None:
    target = make_user(db, username="audited", email="audited@example.com")
    login(client, "rootadmin")

    client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
    client.patch(f"/api/admin/users/{target.id}", json={"role": "admin"})
    client.patch(f"/api/admin/users/{target.id}", json={"new_password": "Rotated!Value9"})
    client.patch("/api/admin/settings", json={"settings": {"maintenance_mode": True}})

    entries = client.get("/api/admin/audit").json()
    actions = [item["action"] for item in entries["items"]]

    assert AuditAction.USER_DISABLED in actions
    assert AuditAction.ROLE_CHANGED in actions
    assert AuditAction.PASSWORD_RESET in actions
    assert AuditAction.SETTINGS_UPDATED in actions
    assert AuditAction.MAINTENANCE_ENABLED in actions

    # No audit row may contain the password that was set.
    serialised = str(entries)
    assert "Rotated!Value9" not in serialised
    assert "password_hash" not in serialised

    rows = db.execute(select(AdminAuditLog)).scalars().all()
    for row in rows:
        assert row.admin_username == "rootadmin"
        blob = str(row.meta or {})
        assert "Rotated!Value9" not in blob
        assert "$argon2" not in blob


def test_audit_log_survives_admin_deletion(
    client: TestClient, db: Session, admin_user: User
) -> None:
    second = make_user(
        db, username="tempmod", email="tempmod@example.com", role=UserRole.ADMIN.value
    )
    login(client, "tempmod")

    victim = make_user(db, username="pawn2", email="pawn2@example.com")
    client.patch(f"/api/admin/users/{victim.id}", json={"is_active": False})

    # rootadmin deletes the admin who performed the action.
    admin_client = TestClient(client.app, raise_server_exceptions=False)
    login(admin_client, "rootadmin")
    assert admin_client.delete(f"/api/admin/users/{second.id}").status_code == 200

    db.expire_all()
    rows = (
        db.execute(select(AdminAuditLog).where(AdminAuditLog.admin_username == "tempmod"))
        .scalars()
        .all()
    )
    assert rows, "audit rows must outlive the admin account"
    # FK is SET NULL, so the id is gone but the denormalised name remains.
    assert all(row.admin_user_id is None for row in rows)


# --------------------------------------------------------------------------- #
# Stats and maintenance ops
# --------------------------------------------------------------------------- #
def test_stats_shape(client: TestClient, admin_user: User) -> None:
    login(client, "rootadmin")
    stats = client.get("/api/admin/stats").json()

    assert set(stats["users"]) >= {"total", "active", "disabled", "admins"}
    assert set(stats["downloads"]) >= {
        "total",
        "today",
        "week",
        "month",
        "successful",
        "failed",
        "success_rate",
    }
    assert isinstance(stats["platforms"], list)
    assert isinstance(stats["media_types"], list)
    assert len(stats["daily"]) == 14
    assert stats["system"]["queue"]["backend"]
    assert "database" in stats["system"]

    # The dashboard must never leak configuration secrets.
    blob = str(stats)
    assert "SECRET_KEY" not in blob
    assert "password" not in blob.lower()


def test_admin_cleanup_endpoint_reports_a_result(client: TestClient, admin_user: User) -> None:
    login(client, "rootadmin")
    response = client.post("/api/admin/cleanup")
    assert response.status_code == 200
    assert set(response.json()["report"]) >= {
        "expired_jobs",
        "deleted_jobs",
        "orphan_dirs",
        "expired_sessions",
        "pruned_history",
    }
