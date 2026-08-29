"""Rate limiting: the limiter itself and its enforcement in the API."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.ratelimit import InMemoryRateLimiter, client_identity, limiter
from app.models.user import User
from tests.conftest import login


# --------------------------------------------------------------------------- #
# Limiter unit behaviour
# --------------------------------------------------------------------------- #
def test_limiter_allows_up_to_the_limit_then_blocks() -> None:
    rl = InMemoryRateLimiter()

    for index in range(5):
        result = rl.check("k", 5, 60)
        assert result.allowed is True
        assert result.remaining == 4 - index

    blocked = rl.check("k", 5, 60)
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after >= 1


def test_limiter_keys_are_independent() -> None:
    rl = InMemoryRateLimiter()
    assert rl.check("a", 1, 60).allowed is True
    assert rl.check("a", 1, 60).allowed is False
    assert rl.check("b", 1, 60).allowed is True


def test_limiter_window_slides() -> None:
    rl = InMemoryRateLimiter()
    # A 1-second window so the test does not need to sleep long.
    assert rl.check("k", 1, 1).allowed is True
    assert rl.check("k", 1, 1).allowed is False
    time.sleep(1.05)
    assert rl.check("k", 1, 1).allowed is True


def test_zero_or_negative_limit_means_unlimited() -> None:
    rl = InMemoryRateLimiter()
    for _ in range(50):
        assert rl.check("k", 0, 60).allowed is True
    assert rl.check("k", -1, 60).allowed is True


def test_peek_does_not_consume() -> None:
    rl = InMemoryRateLimiter()
    rl.check("k", 2, 60)

    first = rl.peek("k", 2, 60)
    second = rl.peek("k", 2, 60)
    assert first.remaining == second.remaining == 1

    assert rl.check("k", 2, 60).allowed is True
    assert rl.check("k", 2, 60).allowed is False


def test_reset_clears_one_key_or_everything() -> None:
    rl = InMemoryRateLimiter()
    rl.check("a", 1, 60)
    rl.check("b", 1, 60)

    rl.reset("a")
    assert rl.check("a", 1, 60).allowed is True
    assert rl.check("b", 1, 60).allowed is False

    rl.reset()
    assert rl.check("b", 1, 60).allowed is True


def test_stale_keys_are_pruned() -> None:
    """Memory must not grow without bound across many distinct clients."""
    rl = InMemoryRateLimiter(prune_interval=0.0, max_keys=10)
    for index in range(200):
        rl.check(f"ip:{index}", 5, 60)
    # Pruning runs on every call with a zero interval, so the map stays bounded.
    assert len(rl._hits) <= 20


def test_client_identity_prefers_the_account() -> None:
    assert client_identity("1.2.3.4", None) == "ip:1.2.3.4"
    assert client_identity("1.2.3.4", 42) == "user:42"
    # A rotating IP must not reset an authenticated user's counter.
    assert client_identity("9.9.9.9", 42) == client_identity("1.2.3.4", 42)


# --------------------------------------------------------------------------- #
# API enforcement
# --------------------------------------------------------------------------- #
def test_analyze_is_rate_limited_for_guests(client: TestClient, db: Session) -> None:
    from app.core.settings_store import store

    store.update(db, {"rate_limit_guest": 3}, actor="test")
    db.commit()
    limiter.reset()

    # Blocked URLs still consume quota: the limiter runs before extraction, which
    # is what stops a flood of junk links from being free.
    for _ in range(3):
        response = client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"})
        assert response.status_code == 400

    limited = client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"})
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["retryable"] is True
    assert body["error"]["meta"]["retry_after"] >= 1
    assert "Retry-After" in limited.headers


def test_rate_limit_headers_are_exposed(client: TestClient, db: Session, monkeypatch) -> None:
    """Budget headers ride along on successful responses.

    They are attached to the injected Response, so they appear on a normal 200 —
    an error response is rebuilt by the exception handler and carries the
    dedicated Retry-After header instead.
    """
    from app.core.settings_store import store
    from app.providers.base import YtDlpProvider
    from app.providers.models import MediaFormat, NormalizedMedia

    async def fake_analyze(self, url: str) -> NormalizedMedia:
        return NormalizedMedia(
            platform="youtube",
            original_url=url,
            title="X",
            formats=[
                MediaFormat(format_id="18", ext="mp4", height=360, has_video=True, has_audio=True)
            ],
        )

    monkeypatch.setattr(YtDlpProvider, "analyze", fake_analyze)
    store.update(db, {"rate_limit_guest": 10}, actor="test")
    db.commit()
    limiter.reset()

    response = client.post(
        "/api/media/analyze", json={"url": "https://www.youtube.com/watch?v=abc"}
    )
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert int(response.headers["X-RateLimit-Remaining"]) == 9


def test_authenticated_users_get_a_separate_higher_limit(
    client: TestClient, db: Session, normal_user: User
) -> None:
    from app.core.settings_store import store

    store.update(db, {"rate_limit_guest": 1, "rate_limit_user": 5}, actor="test")
    db.commit()
    limiter.reset()

    # Exhaust the guest allowance.
    guest = TestClient(client.app, raise_server_exceptions=False)
    assert guest.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 400
    assert guest.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 429

    # A signed-in user is tracked by account and has its own budget.
    login(client, "alice")
    for _ in range(5):
        assert (
            client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 400
        )
    assert client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 429


def test_download_limit_is_tracked_separately_from_analyze(client: TestClient, db: Session) -> None:
    from app.core.settings_store import store

    store.update(db, {"rate_limit_guest": 50, "rate_limit_guest_download": 1}, actor="test")
    db.commit()
    limiter.reset()

    # Analyse quota is untouched by download attempts.
    first = client.post("/api/download", json={"url": "http://127.0.0.1/", "quality": "best"})
    assert first.status_code == 400  # blocked target, but quota consumed

    second = client.post("/api/download", json={"url": "http://127.0.0.1/", "quality": "best"})
    assert second.status_code == 429

    assert client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 400


def test_login_attempts_are_rate_limited_per_ip(
    client: TestClient, monkeypatch, normal_user: User
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH", 3)
    limiter.reset()

    for _ in range(3):
        response = client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-password"}
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong-password"}
    )
    assert blocked.status_code == 429

    # Even the *correct* password is refused while throttled, which is the point.
    from tests.conftest import TEST_PASSWORD

    still_blocked = client.post(
        "/api/auth/login", json={"username": "alice", "password": TEST_PASSWORD}
    )
    assert still_blocked.status_code == 429


def test_admin_limit_is_configurable_and_high(
    client: TestClient, db: Session, admin_user: User
) -> None:
    from app.core.settings_store import store

    store.update(db, {"rate_limit_guest": 1, "rate_limit_admin": 20}, actor="test")
    db.commit()
    limiter.reset()

    login(client, "rootadmin")
    for _ in range(10):
        assert (
            client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"}).status_code == 400
        )


def test_forged_forwarded_header_cannot_reset_the_limit(client: TestClient, db: Session) -> None:
    """With TRUSTED_PROXY_COUNT=0, X-Forwarded-For must be ignored."""
    from app.core.config import settings
    from app.core.settings_store import store

    assert settings.TRUSTED_PROXY_COUNT == 0
    store.update(db, {"rate_limit_guest": 2}, actor="test")
    db.commit()
    limiter.reset()

    for _ in range(2):
        client.post("/api/media/analyze", json={"url": "http://127.0.0.1/"})

    spoofed = client.post(
        "/api/media/analyze",
        json={"url": "http://127.0.0.1/"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert spoofed.status_code == 429


def test_trusted_proxy_count_honours_forwarded_header(monkeypatch) -> None:
    """X-Forwarded-For is only trusted for exactly TRUSTED_PROXY_COUNT hops.

    XFF grows left-to-right: ``client, proxy1, proxy2``. Each proxy appends the
    peer that connected to *it*, so with N trusted proxies the real client sits
    at ``len(chain) - N``. Anything further left was supplied by an untrusted
    upstream — possibly forged by the client — and must be ignored.
    """
    from starlette.datastructures import Headers

    from app.core.config import settings
    from app.middleware.http import _client_ip

    def request_with(xff: str | None, peer: str = "10.0.0.5"):
        class FakeClient:
            host = peer

        class FakeRequest:
            client = FakeClient()
            headers = Headers({"x-forwarded-for": xff} if xff else {})

        return FakeRequest()

    # No trusted proxies: only the socket peer counts.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    assert _client_ip(request_with("203.0.113.7")) == "10.0.0.5"

    # One trusted proxy (nginx) that set XFF to the real client.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert _client_ip(request_with("203.0.113.7")) == "203.0.113.7"

    # One trusted proxy, but the client forged a leading entry. The forged value
    # must NOT win — only the hop our own proxy appended is trustworthy.
    assert _client_ip(request_with("1.2.3.4, 203.0.113.7")) == "203.0.113.7"

    # Two trusted proxies (CDN + nginx): the client is two entries from the right.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
    assert _client_ip(request_with("203.0.113.7, 198.51.100.1")) == "203.0.113.7"

    # Missing header falls back to the peer.
    assert _client_ip(request_with(None)) == "10.0.0.5"
