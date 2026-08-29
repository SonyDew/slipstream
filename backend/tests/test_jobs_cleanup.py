"""Queue claiming, job lifecycle, cleanup and storage confinement."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.job import DownloadJob, JobStatus
from app.models.records import DownloadHistory
from app.models.user import UserSession
from app.services import storage
from app.services.cleanup import run_cleanup
from app.services.queue.local import LocalJobQueue
from tests.conftest import make_user


def make_job(
    db: Session,
    *,
    status: str = JobStatus.QUEUED.value,
    user_id: int | None = None,
    job_id: str | None = None,
    created_at=None,
    expires_at=None,
    file_path: str | None = None,
    file_size: int | None = None,
) -> DownloadJob:
    import uuid

    job = DownloadJob(
        id=job_id or uuid.uuid4().hex,
        user_id=user_id,
        status=status,
        platform="youtube",
        source_url="https://www.youtube.com/watch?v=abc",
        source_domain="www.youtube.com",
        media_type="video",
        requested_quality="720",
        output_format="mp4",
        file_path=file_path,
        file_size=file_size,
        expires_at=expires_at,
    )
    if created_at is not None:
        job.created_at = created_at
    db.add(job)
    db.commit()
    return job


# --------------------------------------------------------------------------- #
# Storage confinement
# --------------------------------------------------------------------------- #
def test_job_directories_are_isolated_and_removable() -> None:
    first = storage.job_dir("aaaaaaaaaaaaaaaa", create=True)
    second = storage.job_dir("bbbbbbbbbbbbbbbb", create=True)

    assert first.is_dir()
    assert second.is_dir()
    assert first != second

    (first / "one.mp4").write_bytes(b"x" * 100)
    assert storage.remove_job_dir("aaaaaaaaaaaaaaaa") is True
    assert not first.exists()
    assert second.exists()  # unrelated job untouched

    # Removing a missing directory is a no-op, not an error.
    assert storage.remove_job_dir("aaaaaaaaaaaaaaaa") is False


def test_job_dir_rejects_traversal_ids() -> None:
    for bad in ("../escape", "..", "a/../../b", "/abs", "C:\\win"):
        with pytest.raises(ValueError):
            storage.job_dir(bad, create=True)


def test_remove_job_dir_refuses_suspicious_ids() -> None:
    assert storage.remove_job_dir("../../etc") is False


def test_find_output_file_ignores_fragments() -> None:
    work = storage.job_dir("cccccccccccccccc", create=True)
    (work / "video.mp4.part").write_bytes(b"x" * 5000)
    (work / "video.f137.mp4.ytdl").write_bytes(b"x" * 10)
    (work / "video.mp4").write_bytes(b"x" * 200)

    found = storage.find_output_file(work)
    assert found is not None
    assert found.name == "video.mp4"


def test_find_output_file_picks_the_largest_candidate() -> None:
    work = storage.job_dir("dddddddddddddddd", create=True)
    (work / "small.mp4").write_bytes(b"x" * 10)
    (work / "large.mp4").write_bytes(b"x" * 1000)
    assert storage.find_output_file(work).name == "large.mp4"


def test_find_output_file_on_empty_directory() -> None:
    work = storage.job_dir("eeeeeeeeeeeeeeee", create=True)
    assert storage.find_output_file(work) is None


def test_temp_usage_reports_bytes_and_files() -> None:
    work = storage.job_dir("ffffffffffffffff", create=True)
    (work / "a.mp4").write_bytes(b"x" * 1234)

    usage = storage.temp_usage()
    assert usage["files"] >= 1
    assert usage["bytes"] >= 1234


# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #
def test_cleanup_expires_ready_jobs_past_their_ttl(db: Session) -> None:
    job = make_job(
        db,
        status=JobStatus.READY.value,
        expires_at=utcnow() - timedelta(minutes=1),
        file_size=5000,
    )
    work = storage.job_dir(job.id, create=True)
    (work / "out.mp4").write_bytes(b"x" * 5000)
    job.file_path = str(work / "out.mp4")
    db.commit()

    report = run_cleanup()

    assert report.expired_jobs == 1
    assert report.freed_bytes >= 5000
    assert not work.exists()

    db.expire_all()
    refreshed = db.get(DownloadJob, job.id)
    assert refreshed.status == JobStatus.EXPIRED.value
    assert refreshed.file_path is None


def test_cleanup_keeps_ready_jobs_within_their_ttl(db: Session) -> None:
    job = make_job(db, status=JobStatus.READY.value, expires_at=utcnow() + timedelta(hours=1))
    work = storage.job_dir(job.id, create=True)
    (work / "out.mp4").write_bytes(b"x" * 10)

    run_cleanup()

    db.expire_all()
    assert db.get(DownloadJob, job.id).status == JobStatus.READY.value
    assert work.exists()


def test_cleanup_deletes_old_terminal_rows(db: Session) -> None:
    old = make_job(
        db,
        status=JobStatus.FAILED.value,
        created_at=utcnow() - timedelta(hours=24),
    )
    recent = make_job(db, status=JobStatus.FAILED.value)

    report = run_cleanup()

    assert report.deleted_jobs >= 1
    # expunge_all, not expire_all: a deleted row still in the identity map raises
    # ObjectDeletedError when refreshed, rather than returning None.
    db.expunge_all()
    assert db.get(DownloadJob, old.id) is None
    assert db.get(DownloadJob, recent.id) is not None


def test_cleanup_removes_orphaned_directories(db: Session) -> None:
    orphan = storage.job_dir("0123456789abcdef0123", create=True)
    (orphan / "leftover.mp4").write_bytes(b"x" * 100)

    report = run_cleanup()

    assert report.orphan_dirs >= 1
    assert not orphan.exists()


def test_cleanup_removes_expired_and_revoked_sessions(db: Session) -> None:
    from app.core.security import generate_token, hash_token

    user = make_user(db, username="sessions", email="sessions@example.com")

    db.add_all(
        [
            UserSession(
                user_id=user.id,
                token_hash=hash_token(generate_token()),
                expires_at=utcnow() - timedelta(hours=1),
            ),
            UserSession(
                user_id=user.id,
                token_hash=hash_token(generate_token()),
                expires_at=utcnow() + timedelta(hours=1),
                revoked_at=utcnow(),
            ),
            UserSession(
                user_id=user.id,
                token_hash=hash_token(generate_token()),
                expires_at=utcnow() + timedelta(hours=1),
            ),
        ]
    )
    db.commit()

    report = run_cleanup()
    assert report.expired_sessions == 2

    db.expire_all()
    remaining = db.execute(select(UserSession)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].is_valid is True


def test_cleanup_prunes_history_past_the_retention_window(db: Session) -> None:
    from app.core.settings_store import store

    user = make_user(db, username="keeper", email="keeper@example.com")
    store.update(db, {"history_retention_days": 30}, actor="test")
    db.commit()

    old_row = DownloadHistory(
        user_id=user.id,
        platform="youtube",
        source_domain="youtube.com",
        media_type="video",
        status="ready",
    )
    old_row.created_at = utcnow() - timedelta(days=60)
    fresh_row = DownloadHistory(
        user_id=user.id,
        platform="tiktok",
        source_domain="tiktok.com",
        media_type="video",
        status="ready",
    )
    db.add_all([old_row, fresh_row])
    db.commit()

    report = run_cleanup()
    assert report.pruned_history == 1

    db.expire_all()
    remaining = db.execute(select(DownloadHistory)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].platform == "tiktok"


def test_cleanup_is_idempotent(db: Session) -> None:
    make_job(db, status=JobStatus.READY.value, expires_at=utcnow() - timedelta(minutes=1))

    first = run_cleanup()
    second = run_cleanup()

    assert first.expired_jobs == 1
    assert second.expired_jobs == 0


def test_cleanup_on_an_empty_system_does_nothing(db: Session) -> None:
    report = run_cleanup()
    assert report.total_actions == 0


# --------------------------------------------------------------------------- #
# Queue claiming
# --------------------------------------------------------------------------- #
def test_claim_takes_the_oldest_queued_job_exactly_once(db: Session) -> None:
    older = make_job(db, created_at=utcnow() - timedelta(minutes=5))
    newer = make_job(db)

    queue = LocalJobQueue()
    first = queue._claim_next()
    assert first == older.id

    db.expire_all()
    assert db.get(DownloadJob, older.id).status == JobStatus.ANALYZING.value
    assert db.get(DownloadJob, older.id).attempts == 1

    second = queue._claim_next()
    assert second == newer.id

    # Nothing left to claim.
    assert queue._claim_next() is None


def test_claim_is_atomic_under_concurrency(db: Session) -> None:
    """Two workers racing for one job: exactly one wins."""
    job = make_job(db)

    queue_a = LocalJobQueue()
    queue_b = LocalJobQueue()

    winners = [queue_a._claim_next(), queue_b._claim_next()]
    assert winners.count(job.id) == 1
    assert winners.count(None) == 1


def test_requeue_orphans_resets_interrupted_jobs(db: Session) -> None:
    stuck = make_job(db, status=JobStatus.DOWNLOADING.value)
    processing = make_job(db, status=JobStatus.PROCESSING.value)
    finished = make_job(db, status=JobStatus.READY.value)

    LocalJobQueue()._requeue_orphans()

    db.expire_all()
    assert db.get(DownloadJob, stuck.id).status == JobStatus.QUEUED.value
    assert db.get(DownloadJob, processing.id).status == JobStatus.QUEUED.value
    # A finished job must not be resurrected.
    assert db.get(DownloadJob, finished.id).status == JobStatus.READY.value


def test_is_cancelled_reads_the_database_flag(db: Session) -> None:
    job = make_job(db)
    queue = LocalJobQueue()

    assert queue.is_cancelled(job.id) is False

    job.cancel_requested = True
    db.commit()
    assert queue.is_cancelled(job.id) is True


def test_request_cancel_is_remembered_in_process(db: Session) -> None:
    queue = LocalJobQueue()
    queue.request_cancel("some-job-id")
    assert queue.is_cancelled("some-job-id") is True


def test_submit_is_safe_without_a_running_loop() -> None:
    """Producers call submit() from a threadpool; it must never raise."""
    queue = LocalJobQueue()
    queue.submit("anything")  # no loop attached yet


def test_queue_stats_report_backlog(db: Session) -> None:
    make_job(db)
    make_job(db)

    stats = LocalJobQueue().stats()
    assert stats.backend == "local-asyncio"
    assert stats.queued == 2
    assert stats.running is False


async def test_queue_start_and_stop_cleanly(db: Session) -> None:
    queue = LocalJobQueue()
    await queue.start()
    try:
        assert queue.stats().running is True
        assert queue.stats().workers >= 1
    finally:
        await queue.stop(timeout=5.0)
    assert queue.stats().running is False


async def test_worker_processes_a_job_end_to_end(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the real worker loop with the pipeline stubbed out."""
    job = make_job(db)
    processed: list[str] = []

    async def fake_pipeline(job_snapshot, reporter):
        processed.append(job_snapshot["id"])
        from app.services.downloader import _publish

        work = storage.job_dir(job_snapshot["id"], create=True)
        target = work / "out.mp4"
        target.write_bytes(b"x" * 128)
        _publish(
            job_snapshot["id"],
            {"path": target, "filename": "out.mp4", "size": 128, "mime": "video/mp4"},
            ttl_seconds=3600,
        )

    import app.services.downloader as downloader

    monkeypatch.setattr(downloader, "_run_pipeline", fake_pipeline)

    queue = LocalJobQueue()
    await queue.start()
    try:
        for _ in range(100):
            await asyncio.sleep(0.05)
            db.expire_all()
            if db.get(DownloadJob, job.id).status == JobStatus.READY.value:
                break
    finally:
        await queue.stop(timeout=5.0)

    assert processed == [job.id]
    db.expire_all()
    finished = db.get(DownloadJob, job.id)
    assert finished.status == JobStatus.READY.value
    assert finished.progress == 100
    assert finished.file_size == 128
    assert finished.expires_at is not None


async def test_worker_marks_a_failing_job_as_failed(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.errors import MediaUnavailableError

    job = make_job(db)

    async def failing_pipeline(job_snapshot, reporter):
        raise MediaUnavailableError()

    import app.services.downloader as downloader

    monkeypatch.setattr(downloader, "_run_pipeline", failing_pipeline)

    queue = LocalJobQueue()
    await queue.start()
    try:
        for _ in range(100):
            await asyncio.sleep(0.05)
            db.expire_all()
            if db.get(DownloadJob, job.id).status == JobStatus.FAILED.value:
                break
    finally:
        await queue.stop(timeout=5.0)

    db.expire_all()
    failed = db.get(DownloadJob, job.id)
    assert failed.status == JobStatus.FAILED.value
    assert failed.error_code == "media_unavailable"
    # The user-facing message must be the friendly one, not an exception dump.
    assert "unavailable" in (failed.error_message or "").lower()
    assert "Traceback" not in (failed.error_message or "")


# --------------------------------------------------------------------------- #
# fail_job / publish semantics
# --------------------------------------------------------------------------- #
def test_fail_job_removes_bytes_and_is_terminal(db: Session) -> None:
    from app.services.downloader import fail_job

    job = make_job(db, status=JobStatus.DOWNLOADING.value)
    work = storage.job_dir(job.id, create=True)
    (work / "partial.mp4.part").write_bytes(b"x" * 1000)

    fail_job(job.id, code="extractor_failure", message="Could not read the link.")

    db.expire_all()
    refreshed = db.get(DownloadJob, job.id)
    assert refreshed.status == JobStatus.FAILED.value
    assert refreshed.error_code == "extractor_failure"
    assert refreshed.finished_at is not None
    assert not work.exists()


def test_fail_job_does_not_overwrite_a_terminal_status(db: Session) -> None:
    from app.services.downloader import fail_job

    job = make_job(db, status=JobStatus.READY.value)
    fail_job(job.id, code="whatever", message="nope")

    db.expire_all()
    assert db.get(DownloadJob, job.id).status == JobStatus.READY.value


def test_fail_job_on_a_missing_job_is_a_noop() -> None:
    from app.services.downloader import fail_job

    fail_job("does-not-exist", code="x", message="y")  # must not raise


def test_publish_sets_expiry_and_writes_history_for_users(db: Session) -> None:
    from app.services.downloader import _publish

    user = make_user(db, username="publisher", email="publisher@example.com")
    job = make_job(db, status=JobStatus.PROCESSING.value, user_id=user.id)
    job.started_at = utcnow() - timedelta(seconds=5)
    db.commit()

    work = storage.job_dir(job.id, create=True)
    target = work / "final.mp4"
    target.write_bytes(b"x" * 2048)

    _publish(
        job.id,
        {"path": target, "filename": "final.mp4", "size": 2048, "mime": "video/mp4"},
        ttl_seconds=7200,
    )

    db.expire_all()
    refreshed = db.get(DownloadJob, job.id)
    assert refreshed.status == JobStatus.READY.value
    assert refreshed.file_size == 2048
    assert refreshed.mime_type == "video/mp4"
    assert refreshed.progress == 100
    assert refreshed.expires_at > utcnow()
    assert refreshed.duration_ms is not None and refreshed.duration_ms > 0
    assert refreshed.is_downloadable is True

    history = db.execute(select(DownloadHistory)).scalars().all()
    assert len(history) == 1
    assert history[0].status == JobStatus.READY.value
    assert history[0].user_id == user.id


def test_history_is_not_written_when_retention_is_zero(db: Session) -> None:
    from app.core.settings_store import store
    from app.services.downloader import fail_job

    user = make_user(db, username="noretain", email="noretain@example.com")
    store.update(db, {"history_retention_days": 0}, actor="test")
    db.commit()

    job = make_job(db, status=JobStatus.DOWNLOADING.value, user_id=user.id)
    fail_job(job.id, code="x", message="y")

    assert db.execute(select(DownloadHistory)).scalars().all() == []


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_jobs_survive_a_new_session(db: Session) -> None:
    """SQLite persistence: a committed job is visible to a fresh session."""
    from app.db.session import SessionLocal

    job = make_job(db, status=JobStatus.READY.value)
    job_id = job.id

    other = SessionLocal()
    try:
        found = other.get(DownloadJob, job_id)
        assert found is not None
        assert found.status == JobStatus.READY.value
        assert found.platform == "youtube"
    finally:
        other.close()


def test_foreign_key_cascade_is_enforced(db: Session) -> None:
    """Requires PRAGMA foreign_keys=ON, which SQLite defaults to OFF."""
    user = make_user(db, username="cascade", email="cascade@example.com")
    job = make_job(db, user_id=user.id)
    job_id = job.id

    db.delete(user)
    db.commit()

    db.expire_all()
    assert db.get(DownloadJob, job_id) is None


def test_wal_mode_is_active() -> None:
    from app.db.session import engine

    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert str(mode).lower() == "wal"


def test_foreign_keys_pragma_is_on() -> None:
    from app.db.session import engine

    with engine.connect() as conn:
        enabled = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert int(enabled) == 1
