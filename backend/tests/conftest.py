"""Shared pytest fixtures.

The environment is configured *before* ``app`` is imported, because settings are
resolved once at import time. Every test therefore runs against a throwaway
SQLite file, an isolated temp directory and a queue that never executes work.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator

# --------------------------------------------------------------------------- #
# Environment — must precede any `app.*` import
# --------------------------------------------------------------------------- #
_TMP_ROOT = tempfile.mkdtemp(prefix="slipstream-tests-")

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-only-secret-key-not-used-anywhere-else-000000",
        "DATA_DIR": _TMP_ROOT,
        "DATABASE_URL": f"sqlite:///{_TMP_ROOT}/test.db".replace("\\", "/"),
        "TEMP_DIR": os.path.join(_TMP_ROOT, "temp"),
        "LOG_DIR": os.path.join(_TMP_ROOT, "logs"),
        # The lifespan must not run migrations or seed; fixtures own the schema.
        "SLIPSTREAM_SKIP_INIT": "1",
        "LOG_LEVEL": "WARNING",
        "COOKIE_SECURE": "false",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_EMAIL": "admin@slipstream.local",
        "INITIAL_ADMIN_PASSWORD": "oleg2017A!",
        "REGISTRATION_ENABLED": "true",
        "GUEST_DOWNLOADS_ENABLED": "true",
        "MAINTENANCE_MODE": "false",
        # Generous so ordinary tests never trip a limiter; the rate-limit tests
        # set their own values.
        "RATE_LIMIT_GUEST": "1000",
        "RATE_LIMIT_GUEST_DOWNLOAD": "1000",
        "RATE_LIMIT_USER": "1000",
        "RATE_LIMIT_USER_DOWNLOAD": "1000",
        "RATE_LIMIT_ADMIN": "10000",
        "RATE_LIMIT_AUTH": "1000",
        "FRONTEND_DIST": os.path.join(_TMP_ROOT, "no-frontend"),
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.ratelimit import limiter  # noqa: E402
from app.core.settings_store import store  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.analyze import cache as analysis_cache  # noqa: E402
from app.services.queue import set_queue  # noqa: E402
from app.services.queue.base import JobQueue, QueueStats  # noqa: E402

TEST_PASSWORD = "TestPassw0rd!x"
ADMIN_TEMP_PASSWORD = "oleg2017A!"


class FakeQueue(JobQueue):
    """Records submissions without executing them."""

    backend = "fake"

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: set[str] = set()
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self, *, timeout: float = 10.0) -> None:
        self.started = False

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def request_cancel(self, job_id: str) -> None:
        self.cancelled.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self.cancelled

    def stats(self) -> QueueStats:
        return QueueStats(
            backend=self.backend,
            running=self.started,
            workers=0,
            active=0,
            queued=len(self.submitted),
            capacity=100,
            processed=0,
            failed=0,
        )


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp() -> Iterator[None]:
    yield
    engine.dispose()
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_database() -> Iterator[None]:
    """Recreate the schema before each test and reset process-wide caches."""
    import app.models  # noqa: F401  - register mappers

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    limiter.reset()
    store.invalidate()
    analysis_cache.clear()

    from app.core.config import settings

    settings.ensure_directories()

    yield

    limiter.reset()
    store.invalidate()
    analysis_cache.clear()


@pytest.fixture
def queue() -> Iterator[FakeQueue]:
    fake = FakeQueue()
    set_queue(fake)
    yield fake
    set_queue(None)


@pytest.fixture
def db(fresh_database: None) -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(queue: FakeQueue) -> Iterator[TestClient]:
    """TestClient without lifespan.

    The lifespan would start the real worker pool and cleanup scheduler; tests
    exercise those directly instead.
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# User helpers
# --------------------------------------------------------------------------- #
def make_user(
    db: Session,
    *,
    username: str = "tester",
    email: str | None = None,
    password: str = TEST_PASSWORD,
    role: str = UserRole.USER.value,
    is_active: bool = True,
    must_change_password: bool = False,
) -> User:
    from app.services.auth import register_user

    user = register_user(
        db,
        username=username,
        email=email or f"{username}@example.com",
        password=password,
        role=role,
        enforce_settings=False,
        must_change_password=must_change_password,
    )
    user.is_active = is_active
    db.commit()
    return user


@pytest.fixture
def normal_user(db: Session) -> User:
    return make_user(db, username="alice", email="alice@example.com")


@pytest.fixture
def admin_user(db: Session) -> User:
    """An administrator who has already rotated the bootstrap password."""
    return make_user(
        db,
        username="rootadmin",
        email="rootadmin@example.com",
        role=UserRole.ADMIN.value,
    )


@pytest.fixture
def bootstrap_admin(db: Session) -> User:
    """An administrator still on the temporary password."""
    return make_user(
        db,
        username="tempadmin",
        email="tempadmin@example.com",
        password=ADMIN_TEMP_PASSWORD,
        role=UserRole.ADMIN.value,
        must_change_password=True,
    )


def login(client: TestClient, username: str, password: str = TEST_PASSWORD) -> dict:
    """Sign in and install the CSRF header on the client for later writes."""
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    payload = response.json()
    client.headers["X-CSRF-Token"] = payload["csrf_token"]
    return payload


def _set_ffmpeg(monkeypatch, available: bool) -> None:
    """Force the FFmpeg probe across every module that consults it.

    Tests must not depend on whether the machine running them happens to have
    FFmpeg installed, so the ladder logic is pinned explicitly instead.
    """
    from app.services import analyze as analyze_module
    from app.services import downloader as downloader_module
    from app.services import jobs as jobs_module

    for module in (analyze_module, jobs_module, downloader_module):
        monkeypatch.setattr(module, "ffmpeg_available", lambda: available)


@pytest.fixture
def with_ffmpeg(monkeypatch) -> None:
    """Behave as though FFmpeg is installed."""
    _set_ffmpeg(monkeypatch, True)


@pytest.fixture
def without_ffmpeg(monkeypatch) -> None:
    """Behave as though FFmpeg is missing."""
    _set_ffmpeg(monkeypatch, False)


@pytest.fixture
def sample_media():
    """A NormalizedMedia with a realistic multi-rung format ladder."""
    from app.providers.models import MediaFormat, NormalizedMedia

    return NormalizedMedia(
        platform="youtube",
        platform_label="YouTube",
        original_url="https://www.youtube.com/watch?v=test12345",
        media_id="test12345",
        title="A Test Video",
        author="Test Channel",
        thumbnail="https://i.ytimg.com/vi/test12345/hq.jpg",
        duration=213,
        media_type="video",
        audio_available=True,
        formats=[
            MediaFormat(
                format_id="313",
                ext="webm",
                height=2160,
                width=3840,
                vcodec="vp9",
                has_video=True,
                needs_merge=True,
                filesize=900_000_000,
                tbr=20000,
            ),
            MediaFormat(
                format_id="137",
                ext="mp4",
                height=1080,
                width=1920,
                vcodec="avc1",
                has_video=True,
                needs_merge=True,
                filesize=120_000_000,
                tbr=4400,
            ),
            MediaFormat(
                format_id="22",
                ext="mp4",
                height=720,
                width=1280,
                vcodec="avc1",
                acodec="mp4a",
                has_video=True,
                has_audio=True,
                filesize=60_000_000,
                tbr=1800,
            ),
            MediaFormat(
                format_id="18",
                ext="mp4",
                height=360,
                width=640,
                vcodec="avc1",
                acodec="mp4a",
                has_video=True,
                has_audio=True,
                filesize=18_000_000,
                tbr=700,
            ),
            MediaFormat(
                format_id="140",
                ext="m4a",
                acodec="mp4a",
                has_audio=True,
                abr=128,
                filesize=3_400_000,
            ),
        ],
    )
