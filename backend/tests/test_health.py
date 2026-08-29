"""Health, version, public config and error-shape contracts."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.version import VERSION
from app.models.user import User
from tests.conftest import login

# Anything resembling a secret must never appear in a public payload.
FORBIDDEN_SUBSTRINGS = (
    "SECRET_KEY",
    "secret_key",
    "test-only-secret-key",
    "password_hash",
    "argon2",
    "sqlite:///",
    "DATABASE_URL",
    "oleg2017",
)


def assert_no_secrets(payload: object) -> None:
    blob = str(payload)
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in blob, f"leaked {needle!r}"


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def test_health_reports_every_required_component(client: TestClient) -> None:
    response = client.get("/api/health")
    # Healthy or degraded (FFmpeg may be absent) — never a hard failure here.
    assert response.status_code in (200, 503)
    body = response.json()

    assert body["status"] in {"healthy", "degraded", "unhealthy"}
    assert body["version"] == VERSION

    components = body["components"]
    assert set(components) >= {"database", "extractor", "ffmpeg", "queue"}
    assert components["database"]["status"] == "ok"
    assert components["extractor"]["status"] == "ok"
    assert components["extractor"]["name"] == "yt-dlp"
    assert components["extractor"]["version"]
    assert components["ffmpeg"]["status"] in {"ok", "unavailable"}
    assert "workers" in components["queue"]


def test_health_does_not_leak_environment_detail(client: TestClient) -> None:
    assert_no_secrets(client.get("/api/health").json())


def test_health_is_reachable_without_authentication(client: TestClient) -> None:
    assert client.get("/api/health").status_code in (200, 503)
    assert client.get("/api/health/ready").status_code in (200, 503)


def test_readiness_probe(client: TestClient) -> None:
    body = client.get("/api/health/ready").json()
    assert body["ready"] is True


def test_storage_health(client: TestClient) -> None:
    body = client.get("/api/health/storage").json()
    assert body["temp_bytes"] >= 0
    assert body["temp_files"] >= 0
    assert "disk_free_bytes" in body


def test_ffmpeg_absence_is_degraded_not_unhealthy(client: TestClient, monkeypatch) -> None:
    from app.api.routes import health as health_route

    monkeypatch.setattr(
        health_route,
        "ffmpeg_status",
        lambda: {
            "available": False,
            "version": "not found",
            "path": None,
            "ffprobe_available": False,
        },
    )
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["ffmpeg"]["status"] == "unavailable"


def test_database_failure_reports_unhealthy(client: TestClient, monkeypatch) -> None:
    from app.api.routes import health as health_route

    monkeypatch.setattr(health_route, "check_database", lambda: (False, "OperationalError"))
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


# --------------------------------------------------------------------------- #
# Version
# --------------------------------------------------------------------------- #
def test_version_endpoint(client: TestClient) -> None:
    body = client.get("/api/version").json()
    assert body["version"] == VERSION
    assert body["name"] == "Slipstream"
    assert body["extractor"]["name"] == "yt-dlp"
    assert "ffmpeg_available" in body
    assert_no_secrets(body)


# --------------------------------------------------------------------------- #
# Public config
# --------------------------------------------------------------------------- #
def test_public_config_exposes_only_safe_fields(client: TestClient) -> None:
    body = client.get("/api/config").json()

    assert body["app_name"]
    assert body["version"] == VERSION
    assert isinstance(body["registration_enabled"], bool)
    assert isinstance(body["guest_downloads_enabled"], bool)
    assert isinstance(body["maintenance_mode"], bool)
    assert body["max_file_size"] > 0
    assert body["max_video_duration"] > 0
    assert len(body["platforms"]) >= 10

    # Administrative settings must not be visible to an anonymous caller.
    for private_key in (
        "rate_limit_guest",
        "rate_limit_user",
        "max_concurrent_downloads",
        "history_retention_days",
        "temp_file_ttl",
    ):
        assert private_key not in body, private_key
    assert_no_secrets(body)


def test_public_config_tracks_admin_changes(
    client: TestClient, db: Session, admin_user: User
) -> None:
    assert client.get("/api/config").json()["registration_enabled"] is True

    login(client, "rootadmin")
    client.patch("/api/admin/settings", json={"settings": {"registration_enabled": False}})

    guest = TestClient(client.app, raise_server_exceptions=False)
    assert guest.get("/api/config").json()["registration_enabled"] is False


# --------------------------------------------------------------------------- #
# Error contract and security headers
# --------------------------------------------------------------------------- #
def test_errors_use_a_consistent_envelope(client: TestClient) -> None:
    response = client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"})
    body = response.json()

    assert set(body) == {"error"}
    assert set(body["error"]) >= {"code", "message", "retryable"}
    assert isinstance(body["error"]["retryable"], bool)


def test_validation_errors_name_fields_without_echoing_values(client: TestClient) -> None:
    """A rejected payload must not bounce the submitted password back."""
    response = client.post("/api/auth/login", json={"username": "", "password": "SuperSecret123!"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "fields" in body["error"]["meta"]
    assert "SuperSecret123!" not in str(body)


def test_unhandled_server_errors_are_opaque(client: TestClient, monkeypatch) -> None:
    from app.api.routes import health as health_route

    def boom() -> None:
        raise RuntimeError("internal detail that must not escape: /srv/secret/path")

    monkeypatch.setattr(health_route, "temp_usage", boom)

    response = client.get("/api/health/storage")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "internal detail" not in str(body)
    assert "/srv/secret/path" not in str(body)
    assert "Traceback" not in str(body)


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/health")
    headers = response.headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in headers
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"

    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "script-src 'self'" in csp
    # No unsafe-inline / unsafe-eval for scripts.
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "unsafe-eval" not in csp

    # API responses must not be cached by a shared proxy.
    assert headers["Cache-Control"] == "no-store"


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["X-Request-ID"]

    provided = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert provided.headers["X-Request-ID"] == "abc123"


def test_openapi_docs_live_under_api_so_docs_belongs_to_the_spa(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
    schema = client.get("/api/openapi.json").json()
    assert "/api/media/analyze" in schema["paths"]
    assert "/api/admin/stats" in schema["paths"]


def test_method_not_allowed_returns_the_error_envelope(client: TestClient) -> None:
    response = client.put("/api/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
