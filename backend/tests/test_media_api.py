"""Media analysis, download jobs and history — with the extractor mocked.

No test here touches a real platform: the extractor boundary is patched so the
suite stays deterministic and offline. The live smoke test
(``scripts/test_extractors.py``) is the opt-in counterpart.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import DownloadJob, JobStatus
from app.models.records import DownloadHistory
from app.models.user import User
from app.providers.models import MediaImage, NormalizedMedia
from tests.conftest import login, make_user

YT_URL = "https://www.youtube.com/watch?v=test12345"
TIKTOK_PHOTO_URL = "https://www.tiktok.com/@someone/photo/7300000000000000000"


@pytest.fixture
def mock_analysis(monkeypatch: pytest.MonkeyPatch, sample_media: NormalizedMedia):
    """Patch the provider layer so ``analyze_url`` returns a fixed result."""

    async def fake_analyze(self: Any, url: str) -> NormalizedMedia:
        media = sample_media.model_copy(deep=True)
        media.original_url = url
        return media

    from app.providers.base import YtDlpProvider

    monkeypatch.setattr(YtDlpProvider, "analyze", fake_analyze)
    return sample_media


@pytest.fixture
def mock_slideshow(monkeypatch: pytest.MonkeyPatch):
    """Patch the provider layer to return a TikTok-style photo post."""
    media = NormalizedMedia(
        platform="tiktok",
        platform_label="TikTok",
        original_url=TIKTOK_PHOTO_URL,
        media_id="7300000000000000000",
        title="A photo post 图片",
        author="someone",
        media_type="image_set",
        audio_available=True,
        images=[
            MediaImage(
                index=i, url=f"https://p16.tiktokcdn.com/img{i}.jpeg", width=1080, height=1350
            )
            for i in range(4)
        ],
        formats=[],
    )
    media.formats = []

    async def fake_analyze(self: Any, url: str) -> NormalizedMedia:
        return media.model_copy(deep=True)

    from app.providers.base import YtDlpProvider
    from app.providers.tiktok import TikTokProvider

    monkeypatch.setattr(YtDlpProvider, "analyze", fake_analyze)
    monkeypatch.setattr(TikTokProvider, "analyze", fake_analyze)
    return media


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
def test_analyze_returns_only_existing_qualities(
    client: TestClient, mock_analysis: NormalizedMedia, with_ffmpeg: None
) -> None:
    response = client.post("/api/media/analyze", json={"url": YT_URL})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["platform"] == "youtube"
    assert body["platform_label"] == "YouTube"
    assert body["title"] == "A Test Video"
    assert body["author"] == "Test Channel"
    assert body["duration"] == 213
    assert body["duration_label"] == "3:33"
    assert body["media_type"] == "video"

    qualities = [option["quality"] for option in body["video_options"]]
    # The fixture has 2160/1080/720/360 — 1440 and 480 must NOT appear.
    assert qualities[0] == "best"
    assert "2160" in qualities
    assert "1080" in qualities
    assert "720" in qualities
    assert "360" in qualities
    assert "1440" not in qualities
    assert "480" not in qualities
    assert "144" not in qualities


def test_analyze_marks_formats_needing_merge(
    client: TestClient, mock_analysis: NormalizedMedia, with_ffmpeg: None
) -> None:
    body = client.post("/api/media/analyze", json={"url": YT_URL}).json()
    options = {option["quality"]: option for option in body["video_options"]}

    # 1080p is video-only in the fixture, so it needs muxing; 720p is progressive.
    assert options["1080"]["needs_merge"] is True
    assert options["720"]["needs_merge"] is False
    # Size for a merged rung includes the audio track.
    assert options["1080"]["filesize"] == 120_000_000 + 3_400_000


def test_analyze_without_ffmpeg_hides_unservable_rungs(
    client: TestClient, mock_analysis: NormalizedMedia, without_ffmpeg: None
) -> None:
    """Only progressive rungs survive; the rest would be silent video."""
    body = client.post("/api/media/analyze", json={"url": YT_URL}).json()
    qualities = [o["quality"] for o in body["video_options"]]

    # The fixture has progressive 720p and 360p, plus adaptive 2160p/1080p.
    assert qualities == ["best", "720", "360"]
    assert all(o["needs_merge"] is False for o in body["video_options"])
    # "Best available" must not claim 2160p when 2160p cannot be delivered.
    assert body["video_options"][0]["height"] == 720
    assert any("FFmpeg" in warning for warning in body["warnings"])

    # And a request for a hidden rung is refused rather than silently downgraded.
    refused = client.post("/api/download", json={"url": YT_URL, "quality": "2160"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "no_suitable_format"


def test_analyze_rejects_blocked_and_invalid_urls(client: TestClient) -> None:
    blocked = client.post("/api/media/analyze", json={"url": "http://169.254.169.254/"})
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "blocked_target"

    invalid = client.post("/api/media/analyze", json={"url": "nonsense"})
    assert invalid.status_code in (400, 422)


def test_analyze_respects_platform_allow_list(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    from app.core.settings_store import store

    store.update(db, {"allowed_platforms": ["tiktok"]}, actor="test")
    db.commit()

    response = client.post("/api/media/analyze", json={"url": YT_URL})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "platform_disabled"


def test_analyze_result_is_cached(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, sample_media: NormalizedMedia
) -> None:
    calls = 0

    async def counting_analyze(self: Any, url: str) -> NormalizedMedia:
        nonlocal calls
        calls += 1
        return sample_media.model_copy(deep=True)

    from app.providers.base import YtDlpProvider

    monkeypatch.setattr(YtDlpProvider, "analyze", counting_analyze)

    assert client.post("/api/media/analyze", json={"url": YT_URL}).status_code == 200
    assert client.post("/api/media/analyze", json={"url": YT_URL}).status_code == 200
    assert calls == 1


def test_platforms_endpoint_lists_providers(client: TestClient) -> None:
    body = client.get("/api/media/platforms").json()
    names = {item["platform"] for item in body["platforms"]}
    assert {
        "youtube",
        "tiktok",
        "douyin",
        "instagram",
        "twitter",
        "facebook",
        "reddit",
        "vimeo",
        "soundcloud",
    } <= names


# --------------------------------------------------------------------------- #
# Slideshow
# --------------------------------------------------------------------------- #
def test_slideshow_analysis_exposes_images(
    client: TestClient, mock_slideshow: NormalizedMedia
) -> None:
    body = client.post("/api/media/analyze", json={"url": TIKTOK_PHOTO_URL}).json()

    assert body["platform"] == "tiktok"
    assert body["media_type"] == "image_set"
    assert body["is_slideshow"] is True
    assert len(body["images"]) == 4
    assert body["images"][0]["url"].startswith("https://")
    assert body["video_options"] == []


def test_slideshow_download_job_defaults_to_zip(
    client: TestClient, db: Session, mock_slideshow: NormalizedMedia
) -> None:
    response = client.post("/api/download", json={"url": TIKTOK_PHOTO_URL, "mode": "image"})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    job = db.get(DownloadJob, job_id)
    assert job is not None
    assert job.media_type == "image_set"
    assert job.output_format == "zip"
    assert job.platform == "tiktok"


def test_slideshow_download_can_select_specific_images(
    client: TestClient, db: Session, mock_slideshow: NormalizedMedia
) -> None:
    response = client.post(
        "/api/download",
        json={"url": TIKTOK_PHOTO_URL, "mode": "image", "image_indexes": [0, 2]},
    )
    assert response.status_code == 202
    job = db.get(DownloadJob, response.json()["job_id"])
    assert job.selected_images == {"indexes": [0, 2]}


# --------------------------------------------------------------------------- #
# Download job creation
# --------------------------------------------------------------------------- #
def test_download_creates_queued_job_and_notifies_queue(
    client: TestClient, db: Session, queue: Any, mock_analysis: NormalizedMedia
) -> None:
    response = client.post("/api/download", json={"url": YT_URL, "mode": "video", "quality": "720"})
    assert response.status_code == 202, response.text
    body = response.json()

    assert body["status"] == "queued"
    assert body["poll_url"] == f"/api/jobs/{body['job_id']}"
    assert queue.submitted == [body["job_id"]]

    job = db.get(DownloadJob, body["job_id"])
    assert job is not None
    assert job.status == JobStatus.QUEUED.value
    assert job.requested_quality == "720"
    assert job.output_format == "mp4"
    assert job.platform == "youtube"
    assert job.source_domain == "www.youtube.com"
    assert job.user_id is None  # guest
    assert job.guest_key  # pseudonymous, not an IP
    assert "." not in (job.guest_key or "")


def test_download_rejects_unavailable_quality(
    client: TestClient, mock_analysis: NormalizedMedia
) -> None:
    response = client.post(
        "/api/download", json={"url": YT_URL, "mode": "video", "quality": "1440"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_suitable_format"


def test_download_rejects_malformed_quality_token(
    client: TestClient, mock_analysis: NormalizedMedia
) -> None:
    """A crafted quality value must never reach the extractor selector."""
    for bad in ("bestvideo+bestaudio", "1080p", "../../etc/passwd", "best/best", ""):
        response = client.post(
            "/api/download", json={"url": YT_URL, "mode": "video", "quality": bad}
        )
        assert response.status_code in (400, 422), bad


def test_audio_download_requires_ffmpeg(
    client: TestClient, mock_analysis: NormalizedMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without FFmpeg the API must refuse MP3 rather than fail mid-job."""
    import app.services.formats as formats_module
    from app.services import analyze as analyze_module
    from app.services import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "ffmpeg_available", lambda: False)
    monkeypatch.setattr(analyze_module, "ffmpeg_available", lambda: False)

    body = client.post("/api/media/analyze", json={"url": YT_URL}).json()
    assert body["audio_options"] == []
    assert body["ffmpeg_available"] is False

    response = client.post(
        "/api/download", json={"url": YT_URL, "mode": "audio", "quality": "192", "container": "mp3"}
    )
    assert response.status_code == 400
    assert formats_module  # imported for clarity of intent


def test_audio_download_with_ffmpeg_available(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import analyze as analyze_module
    from app.services import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(analyze_module, "ffmpeg_available", lambda: True)

    body = client.post("/api/media/analyze", json={"url": YT_URL}).json()
    bitrates = [option["quality"] for option in body["audio_options"]]
    # Source audio is 128 kbps, so 320/256/192 must not be offered as real rungs.
    assert bitrates[0] == "best"
    assert "128" in bitrates
    assert "320" not in bitrates
    assert "256" not in bitrates

    response = client.post(
        "/api/download", json={"url": YT_URL, "mode": "audio", "quality": "128", "container": "mp3"}
    )
    assert response.status_code == 202
    job = db.get(DownloadJob, response.json()["job_id"])
    assert job.output_format == "mp3"
    assert job.media_type == "audio"


def test_guest_downloads_can_be_disabled(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    from app.core.settings_store import store

    store.update(db, {"guest_downloads_enabled": False}, actor="test")
    db.commit()

    response = client.post("/api/download", json={"url": YT_URL, "quality": "720"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "guest_downloads_disabled"


def test_authenticated_download_is_attributed_to_the_user(
    client: TestClient, db: Session, normal_user: User, mock_analysis: NormalizedMedia
) -> None:
    login(client, "alice")
    response = client.post("/api/download", json={"url": YT_URL, "quality": "720"})
    assert response.status_code == 202

    job = db.get(DownloadJob, response.json()["job_id"])
    assert job.user_id == normal_user.id
    assert job.guest_key is None


def test_queue_capacity_is_enforced(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, mock_analysis: NormalizedMedia
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "JOB_QUEUE_SIZE", 1)

    first = client.post("/api/download", json={"url": YT_URL, "quality": "720"})
    assert first.status_code == 202

    second = client.post("/api/download", json={"url": YT_URL, "quality": "360"})
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "queue_full"


# --------------------------------------------------------------------------- #
# Job polling, ownership and cancellation
# --------------------------------------------------------------------------- #
def test_job_polling_returns_progress_fields(
    client: TestClient, mock_analysis: NormalizedMedia
) -> None:
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["id"] == job_id
    assert body["status"] == "queued"
    assert body["progress"] == 0
    assert body["is_downloadable"] is False
    assert body["download_url"] is None
    assert set(body) >= {"progress_label", "eta_seconds", "speed_bps", "error_code"}


def test_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get("/api/jobs/deadbeefdeadbeefdeadbeefdeadbeef")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_user_cannot_poll_another_users_job(
    client: TestClient, db: Session, normal_user: User, mock_analysis: NormalizedMedia
) -> None:
    make_user(db, username="bob", email="bob@example.com")

    login(client, "alice")
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    other = TestClient(client.app, raise_server_exceptions=False)
    login(other, "bob")
    # Deliberately a 404, not a 403: existence is not confirmed.
    assert other.get(f"/api/jobs/{job_id}").status_code == 404
    assert other.delete(f"/api/jobs/{job_id}").status_code == 404


def test_admin_can_inspect_any_job(
    client: TestClient,
    db: Session,
    normal_user: User,
    admin_user: User,
    mock_analysis: NormalizedMedia,
) -> None:
    login(client, "alice")
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    admin_client = TestClient(client.app, raise_server_exceptions=False)
    login(admin_client, "rootadmin")
    assert admin_client.get(f"/api/jobs/{job_id}").status_code == 200


def test_cancelling_a_queued_job_finalises_it(
    client: TestClient, db: Session, queue: Any, mock_analysis: NormalizedMedia
) -> None:
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True, "status": "cancelled"}
    assert job_id in queue.cancelled

    db.expire_all()
    job = db.get(DownloadJob, job_id)
    assert job.status == JobStatus.CANCELLED.value
    assert job.cancel_requested is True
    assert job.finished_at is not None


def test_file_endpoint_refuses_unfinished_and_expired_jobs(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    not_ready = client.get(f"/api/jobs/{job_id}/file")
    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "job_not_ready"

    job = db.get(DownloadJob, job_id)
    job.status = JobStatus.EXPIRED.value
    db.commit()

    expired = client.get(f"/api/jobs/{job_id}/file")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "download_expired"


def test_file_endpoint_streams_a_ready_job_with_unicode_name(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    from datetime import timedelta

    from app.db.base import utcnow
    from app.services import storage

    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]

    work_dir = storage.job_dir(job_id, create=True)
    payload = b"fake-media-bytes" * 64
    target = work_dir / "output.mp4"
    target.write_bytes(payload)

    job = db.get(DownloadJob, job_id)
    job.status = JobStatus.READY.value
    job.file_path = str(target)
    job.file_name = "测试视频 - Test 720p.mp4"
    job.file_size = len(payload)
    job.mime_type = "video/mp4"
    job.expires_at = utcnow() + timedelta(hours=1)
    db.commit()

    response = client.get(f"/api/jobs/{job_id}/file")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "video/mp4"

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    # A Unicode filename must be delivered via RFC 5987 filename*.
    assert "filename*=UTF-8''" in disposition
    assert "%E6%B5%8B%E8%AF%95" in disposition  # 测试
    assert "no-store" in response.headers["cache-control"]

    db.expire_all()
    assert db.get(DownloadJob, job_id).delivered_at is not None


def test_file_endpoint_expires_job_when_bytes_are_missing(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    from datetime import timedelta

    from app.db.base import utcnow

    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]
    job = db.get(DownloadJob, job_id)
    job.status = JobStatus.READY.value
    job.file_path = str(job_id) + "-does-not-exist.mp4"
    job.expires_at = utcnow() + timedelta(hours=1)
    db.commit()

    response = client.get(f"/api/jobs/{job_id}/file")
    assert response.status_code == 410

    db.expire_all()
    assert db.get(DownloadJob, job_id).status == JobStatus.EXPIRED.value


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def test_history_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/history").status_code == 401


def test_history_lists_only_the_callers_rows(
    client: TestClient, db: Session, normal_user: User
) -> None:
    bob = make_user(db, username="bob", email="bob@example.com")
    for owner, title in ((normal_user, "alice item"), (bob, "bob item")):
        db.add(
            DownloadHistory(
                user_id=owner.id,
                job_id=f"job-{owner.id}",
                platform="youtube",
                source_domain="youtube.com",
                title=title,
                media_type="video",
                status="ready",
            )
        )
    db.commit()

    login(client, "alice")
    body = client.get("/api/history").json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "alice item"


def test_history_can_be_cleared_by_its_owner(
    client: TestClient, db: Session, normal_user: User
) -> None:
    bob = make_user(db, username="bob", email="bob@example.com")
    db.add_all(
        [
            DownloadHistory(
                user_id=normal_user.id,
                platform="youtube",
                source_domain="youtube.com",
                media_type="video",
                status="ready",
            ),
            DownloadHistory(
                user_id=bob.id,
                platform="tiktok",
                source_domain="tiktok.com",
                media_type="video",
                status="ready",
            ),
        ]
    )
    db.commit()

    login(client, "alice")
    response = client.delete("/api/history")
    assert response.status_code == 200
    assert response.json()["deleted"] == 1

    # Bob's history is untouched.
    remaining = db.execute(select(DownloadHistory)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].user_id == bob.id


def test_guest_downloads_leave_no_history(
    client: TestClient, db: Session, mock_analysis: NormalizedMedia
) -> None:
    """Privacy: an anonymous download must not create a durable record."""
    from app.services.downloader import fail_job

    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]
    fail_job(job_id, code="extractor_failure", message="Test failure")

    rows = db.execute(select(DownloadHistory)).scalars().all()
    assert rows == []


def test_authenticated_failure_is_recorded_in_history(
    client: TestClient, db: Session, normal_user: User, mock_analysis: NormalizedMedia
) -> None:
    from app.services.downloader import fail_job

    login(client, "alice")
    job_id = client.post("/api/download", json={"url": YT_URL, "quality": "720"}).json()["job_id"]
    fail_job(job_id, code="media_unavailable", message="Gone")

    db.expire_all()
    rows = db.execute(select(DownloadHistory)).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == JobStatus.FAILED.value
    assert rows[0].error_code == "media_unavailable"
    assert rows[0].user_id == normal_user.id
