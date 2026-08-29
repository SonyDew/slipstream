"""Administrator API.

Read endpoints require an admin session. Every *mutating* endpoint additionally
requires that the admin is not still using the bootstrap password
(:data:`RequireAdminVerified`), and writes an audit record.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import Select, delete, func, or_, select

from app.api.deps import DbSession, RequireAdmin, RequireAdminVerified, client_ip
from app.core.errors import JobNotFoundError, LastAdminError, PermissionDeniedError
from app.core.logging import get_logger, log_security_event
from app.core.settings_store import store
from app.core.version import build_info
from app.db.base import utcnow
from app.db.init_db import database_file_size
from app.db.session import check_database
from app.models.job import DownloadJob, JobStatus
from app.models.records import AdminAuditLog, AuditAction, DownloadHistory
from app.models.user import User, UserRole
from app.schemas.api import CreateUserRequest, UpdateSettingsRequest, UpdateUserRequest
from app.services.auth import admin_set_password, assert_not_last_admin, revoke_all_sessions
from app.services.extractor import extractor_status, ffmpeg_status
from app.services.queue import get_queue
from app.services.storage import disk_free_bytes, temp_usage

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("slipstream.api.admin")


# --------------------------------------------------------------------------- #
# Audit helper
# --------------------------------------------------------------------------- #
def record_audit(
    db: Any,
    *,
    admin: User,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit row.

    ``meta`` is caller-supplied and must never contain credentials; the callers
    below pass only field names and non-secret values.
    """
    db.add(
        AdminAuditLog(
            admin_user_id=admin.id,
            admin_username=admin.display_username,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            target_label=target_label,
            meta=meta,
            ip_address=ip,
        )
    )
    log.info("admin action", event=action, user_id=admin.id, target=str(target_id))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/stats")
def stats(auth: RequireAdmin, db: DbSession) -> dict:
    """Aggregate counters, distributions and time series for the dashboard."""
    now = utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def count(model: Any, *conditions: Any) -> int:
        query: Select = select(func.count()).select_from(model)
        for condition in conditions:
            query = query.where(condition)
        return int(db.execute(query).scalar() or 0)

    total_users = count(User)
    active_users = count(User, User.is_active.is_(True))
    admin_users = count(User, User.role == UserRole.ADMIN.value)

    # Job rows are pruned, so history is the authoritative long-term ledger and
    # jobs cover the live window. Downloads are counted from history.
    downloads_total = count(DownloadHistory)
    downloads_today = count(DownloadHistory, DownloadHistory.created_at >= day_ago)
    downloads_week = count(DownloadHistory, DownloadHistory.created_at >= week_ago)
    downloads_month = count(DownloadHistory, DownloadHistory.created_at >= month_ago)
    downloads_ok = count(DownloadHistory, DownloadHistory.status == JobStatus.READY.value)
    downloads_failed = count(DownloadHistory, DownloadHistory.status == JobStatus.FAILED.value)

    platform_rows = db.execute(
        select(DownloadHistory.platform, func.count().label("n"))
        .group_by(DownloadHistory.platform)
        .order_by(func.count().desc())
        .limit(12)
    ).all()

    media_rows = db.execute(
        select(DownloadHistory.media_type, func.count().label("n"))
        .group_by(DownloadHistory.media_type)
        .order_by(func.count().desc())
    ).all()

    status_rows = db.execute(
        select(DownloadHistory.status, func.count().label("n")).group_by(DownloadHistory.status)
    ).all()

    recent_users = (
        db.execute(select(User).order_by(User.created_at.desc()).limit(8)).scalars().all()
    )
    recent_downloads = (
        db.execute(select(DownloadHistory).order_by(DownloadHistory.created_at.desc()).limit(10))
        .scalars()
        .all()
    )

    queue_stats = get_queue().stats()
    db_ok, db_detail = check_database()
    usage = temp_usage()

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "disabled": total_users - active_users,
            "admins": admin_users,
            "new_this_week": count(User, User.created_at >= week_ago),
        },
        "downloads": {
            "total": downloads_total,
            "today": downloads_today,
            "week": downloads_week,
            "month": downloads_month,
            "successful": downloads_ok,
            "failed": downloads_failed,
            "success_rate": round(downloads_ok / downloads_total * 100, 1)
            if downloads_total
            else 0.0,
        },
        "platforms": [{"platform": row[0], "count": row[1]} for row in platform_rows],
        "media_types": [{"media_type": row[0], "count": row[1]} for row in media_rows],
        "statuses": [{"status": row[0], "count": row[1]} for row in status_rows],
        "daily": _daily_series(db, days=14),
        "recent_users": [
            {
                "id": u.id,
                "username": u.display_username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at,
            }
            for u in recent_users
        ],
        "recent_downloads": [
            {
                "id": h.id,
                "platform": h.platform,
                "title": h.title,
                "media_type": h.media_type,
                "status": h.status,
                "created_at": h.created_at,
                "user_id": h.user_id,
            }
            for h in recent_downloads
        ],
        "system": {
            "version": build_info()["version"],
            "database": {"status": "ok" if db_ok else "error", "detail": db_detail},
            "database_size_bytes": database_file_size(),
            "extractor": extractor_status(),
            "ffmpeg": ffmpeg_status(),
            "queue": {
                "backend": queue_stats.backend,
                "running": queue_stats.running,
                "workers": queue_stats.workers,
                "active": queue_stats.active,
                "queued": queue_stats.queued,
                "processed": queue_stats.processed,
                "failed": queue_stats.failed,
            },
            "storage": {
                "temp_bytes": usage["bytes"],
                "temp_files": usage["files"],
                "disk_free_bytes": disk_free_bytes(),
            },
            "active_jobs": int(
                db.execute(
                    select(func.count())
                    .select_from(DownloadJob)
                    .where(DownloadJob.status.in_(sorted(JobStatus.active())))
                ).scalar()
                or 0
            ),
        },
    }


def _daily_series(db: Any, *, days: int) -> list[dict[str, Any]]:
    """Per-day download counts, split by outcome.

    Grouped in Python rather than with a dialect-specific date function so the
    same code works on SQLite and PostgreSQL.
    """
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(DownloadHistory.created_at, DownloadHistory.status).where(
            DownloadHistory.created_at >= since
        )
    ).all()

    buckets: dict[str, dict[str, int]] = {}
    for created_at, row_status in rows:
        key = created_at.date().isoformat()
        bucket = buckets.setdefault(key, {"total": 0, "successful": 0, "failed": 0})
        bucket["total"] += 1
        if row_status == JobStatus.READY.value:
            bucket["successful"] += 1
        elif row_status == JobStatus.FAILED.value:
            bucket["failed"] += 1

    out: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = (utcnow() - timedelta(days=offset)).date().isoformat()
        bucket = buckets.get(day, {"total": 0, "successful": 0, "failed": 0})
        out.append({"date": day, **bucket})
    return out


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
@router.get("/users")
def list_users(
    auth: RequireAdmin,
    db: DbSession,
    q: str = Query(default="", max_length=128),
    role: str = Query(default="", max_length=16),
    active: str = Query(default="", max_length=8),
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=25, ge=1, le=100),
) -> dict:
    query: Select = select(User)
    conditions = []

    if q:
        needle = f"%{q.strip().lower()}%"
        conditions.append(or_(User.username.like(needle), User.email.like(needle)))
    if role in {UserRole.USER.value, UserRole.ADMIN.value}:
        conditions.append(User.role == role)
    if active in {"true", "false"}:
        conditions.append(User.is_active.is_(active == "true"))

    for condition in conditions:
        query = query.where(condition)

    count_query: Select = select(func.count()).select_from(User)
    for condition in conditions:
        count_query = count_query.where(condition)
    total = int(db.execute(count_query).scalar() or 0)

    rows = (
        db.execute(
            query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
        )
        .scalars()
        .all()
    )

    # One grouped query for download counts rather than N per-user queries.
    counts: dict[int, int] = {
        int(row[0]): int(row[1])
        for row in db.execute(
            select(DownloadHistory.user_id, func.count())
            .where(DownloadHistory.user_id.in_([u.id for u in rows] or [-1]))
            .group_by(DownloadHistory.user_id)
        ).all()
        if row[0] is not None
    }

    return {
        "items": [
            {
                **_user_summary(user),
                "download_count": int(counts.get(user.id, 0)),
            }
            for user in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/users/{user_id}")
def get_user(user_id: int, auth: RequireAdmin, db: DbSession) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise JobNotFoundError("That user does not exist.")

    downloads = int(
        db.execute(
            select(func.count())
            .select_from(DownloadHistory)
            .where(DownloadHistory.user_id == user.id)
        ).scalar()
        or 0
    )
    recent = (
        db.execute(
            select(DownloadHistory)
            .where(DownloadHistory.user_id == user.id)
            .order_by(DownloadHistory.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )

    return {
        **_user_summary(user),
        "download_count": downloads,
        "recent_activity": [
            {
                "id": row.id,
                "platform": row.platform,
                "title": row.title,
                "media_type": row.media_type,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in recent
        ],
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    """Enable/disable, change role, or reset a password."""
    assert auth.user is not None
    admin = auth.user
    target = db.get(User, user_id)
    if target is None:
        raise JobNotFoundError("That user does not exist.")

    ip = client_ip(request)
    changes: list[str] = []

    if payload.is_active is not None and payload.is_active != target.is_active:
        if not payload.is_active:
            if target.id == admin.id:
                raise PermissionDeniedError("You cannot disable your own account.")
            assert_not_last_admin(db, target, action="disable this account")
        target.is_active = payload.is_active
        if not payload.is_active:
            # A disabled account must lose its live sessions immediately.
            revoke_all_sessions(db, target.id)
        changes.append("is_active")
        record_audit(
            db,
            admin=admin,
            action=AuditAction.USER_ENABLED if payload.is_active else AuditAction.USER_DISABLED,
            target_type="user",
            target_id=str(target.id),
            target_label=target.display_username,
            ip=ip,
        )

    if payload.role is not None and payload.role != target.role:
        if payload.role != UserRole.ADMIN.value:
            if target.id == admin.id:
                raise PermissionDeniedError("You cannot remove your own administrator role.")
            assert_not_last_admin(db, target, action="remove administrator from this account")
        previous = target.role
        target.role = payload.role
        changes.append("role")
        record_audit(
            db,
            admin=admin,
            action=AuditAction.ROLE_CHANGED,
            target_type="user",
            target_id=str(target.id),
            target_label=target.display_username,
            meta={"from": previous, "to": payload.role},
            ip=ip,
        )

    if payload.new_password:
        admin_set_password(db, target, payload.new_password)
        changes.append("password")
        # Only the fact of the reset is recorded — never the value.
        record_audit(
            db,
            admin=admin,
            action=AuditAction.PASSWORD_RESET,
            target_type="user",
            target_id=str(target.id),
            target_label=target.display_username,
            meta={"forced_change": True},
            ip=ip,
        )
        log_security_event("admin_password_reset", user_id=admin.id, target_id=target.id)

    if not changes:
        return {"updated": False, **_user_summary(target)}

    db.commit()
    return {"updated": True, "changed": changes, **_user_summary(target)}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    assert auth.user is not None
    admin = auth.user
    target = db.get(User, user_id)
    if target is None:
        raise JobNotFoundError("That user does not exist.")
    if target.id == admin.id:
        raise PermissionDeniedError("You cannot delete your own account.")

    # Guard the invariant even when the target is currently disabled.
    if target.is_admin:
        remaining = int(
            db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == UserRole.ADMIN.value,
                    User.id != target.id,
                    User.is_active.is_(True),
                )
            ).scalar()
            or 0
        )
        if remaining == 0:
            raise LastAdminError("Cannot delete the last administrator account.")

    label = target.display_username
    record_audit(
        db,
        admin=admin,
        action=AuditAction.USER_DELETED,
        target_type="user",
        target_id=str(target.id),
        target_label=label,
        ip=client_ip(request),
    )
    # Sessions, jobs and history cascade via the FK rules; the audit row keeps
    # its denormalised username because admin_user_id is SET NULL, not CASCADE.
    db.delete(target)
    db.commit()
    log_security_event("admin_user_deleted", user_id=admin.id, target_id=user_id)
    return {"deleted": True}


def _user_summary(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.display_username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "failed_login_count": user.failed_login_count,
    }


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #
@router.get("/downloads")
def list_downloads(
    auth: RequireAdmin,
    db: DbSession,
    q: str = Query(default="", max_length=128),
    platform: str = Query(default="", max_length=32),
    job_status: str = Query(default="", alias="status", max_length=16),
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=25, ge=1, le=100),
) -> dict:
    """Download ledger.

    Shows the source *domain* rather than the full URL: a pasted link can carry
    tracking parameters or share tokens that should not be rendered in an admin
    console.
    """
    conditions = []
    if q:
        needle = f"%{q.strip()}%"
        conditions.append(
            or_(DownloadHistory.title.like(needle), DownloadHistory.author.like(needle))
        )
    if platform:
        conditions.append(DownloadHistory.platform == platform)
    if job_status:
        conditions.append(DownloadHistory.status == job_status)

    query: Select = select(DownloadHistory)
    count_query: Select = select(func.count()).select_from(DownloadHistory)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = int(db.execute(count_query).scalar() or 0)
    rows = (
        db.execute(
            query.order_by(DownloadHistory.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .scalars()
        .all()
    )

    usernames: dict[int, str] = {
        int(row[0]): str(row[1])
        for row in db.execute(
            select(User.id, User.display_username).where(
                User.id.in_([r.user_id for r in rows if r.user_id] or [-1])
            )
        ).all()
    }

    return {
        "items": [
            {
                "id": row.id,
                "job_id": row.job_id,
                "user_id": row.user_id,
                "username": usernames.get(row.user_id) if row.user_id else None,
                "is_guest": row.user_id is None,
                "platform": row.platform,
                "source_domain": row.source_domain,
                "title": row.title,
                "author": row.author,
                "media_type": row.media_type,
                "quality": row.quality,
                "output_format": row.output_format,
                "file_size": row.file_size,
                "status": row.status,
                "error_code": row.error_code,
                "duration_ms": row.duration_ms,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/jobs")
def list_active_jobs(auth: RequireAdmin, db: DbSession) -> dict:
    """Live queue contents."""
    rows = (
        db.execute(
            select(DownloadJob)
            .where(DownloadJob.status.in_(sorted(JobStatus.active())))
            .order_by(DownloadJob.created_at)
            .limit(100)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": job.id,
                "status": job.status,
                "platform": job.platform,
                "source_domain": job.source_domain,
                "title": job.title,
                "media_type": job.media_type,
                "quality": job.requested_quality,
                "progress": job.progress,
                "progress_label": job.progress_label,
                "user_id": job.user_id,
                "is_guest": job.user_id is None,
                "created_at": job.created_at,
                "started_at": job.started_at,
            }
            for job in rows
        ]
    }


@router.delete("/jobs/{job_id}")
def admin_cancel_job(
    job_id: str,
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    from app.services.jobs import cancel_job

    assert auth.user is not None
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise JobNotFoundError()

    cancelled = cancel_job(db, job)
    record_audit(
        db,
        admin=auth.user,
        action=AuditAction.JOB_CANCELLED,
        target_type="job",
        target_id=job.id,
        target_label=job.platform,
        ip=client_ip(request),
    )
    db.commit()
    return {"cancelled": cancelled, "status": job.status}


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
@router.get("/audit")
def list_audit(
    auth: RequireAdmin,
    db: DbSession,
    action: str = Query(default="", max_length=48),
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    conditions = []
    if action:
        conditions.append(AdminAuditLog.action == action)

    query: Select = select(AdminAuditLog)
    count_query: Select = select(func.count()).select_from(AdminAuditLog)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = int(db.execute(count_query).scalar() or 0)
    rows = (
        db.execute(
            query.order_by(AdminAuditLog.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .scalars()
        .all()
    )

    return {
        "items": [
            {
                "id": row.id,
                "admin_username": row.admin_username,
                "admin_user_id": row.admin_user_id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "target_label": row.target_label,
                "meta": row.meta,
                "ip_address": row.ip_address,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "actions": sorted(
            {
                value
                for key, value in vars(AuditAction).items()
                if not key.startswith("_") and isinstance(value, str)
            }
        ),
    }


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.get("/settings")
def get_settings(auth: RequireAdmin, db: DbSession) -> dict:
    return {"settings": store.describe(db)}


@router.patch("/settings")
def update_settings(
    payload: UpdateSettingsRequest,
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    assert auth.user is not None
    previous = store.all(db)
    applied = store.update(db, payload.settings, actor=auth.user.display_username)

    changed = {
        key: {"from": previous.get(key), "to": value}
        for key, value in applied.items()
        if previous.get(key) != value
    }

    record_audit(
        db,
        admin=auth.user,
        action=AuditAction.SETTINGS_UPDATED,
        target_type="settings",
        target_id=",".join(sorted(applied)),
        meta={"changed": changed} if changed else None,
        ip=client_ip(request),
    )

    # Maintenance mode is significant enough for its own audit entry.
    if "maintenance_mode" in changed:
        record_audit(
            db,
            admin=auth.user,
            action=AuditAction.MAINTENANCE_ENABLED
            if applied["maintenance_mode"]
            else AuditAction.MAINTENANCE_DISABLED,
            target_type="settings",
            target_id="maintenance_mode",
            ip=client_ip(request),
        )

    db.commit()
    store.invalidate()
    return {"settings": store.describe(db), "changed": sorted(changed)}


# --------------------------------------------------------------------------- #
# Maintenance operations
# --------------------------------------------------------------------------- #
@router.post("/cleanup", status_code=status.HTTP_200_OK)
def trigger_cleanup(
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    """Run a cleanup sweep now."""
    from app.services.cleanup import run_cleanup

    assert auth.user is not None
    report = run_cleanup()
    record_audit(
        db,
        admin=auth.user,
        action=AuditAction.CLEANUP_TRIGGERED,
        target_type="system",
        meta=report.as_dict(),
        ip=client_ip(request),
    )
    db.commit()
    return {"report": report.as_dict()}


@router.delete("/history", status_code=status.HTTP_200_OK)
def purge_history(
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
    older_than_days: int = Query(default=0, ge=0, le=3650),
) -> dict:
    """Delete history rows, optionally only those older than N days."""
    assert auth.user is not None
    statement = delete(DownloadHistory)
    if older_than_days > 0:
        statement = statement.where(
            DownloadHistory.created_at <= utcnow() - timedelta(days=older_than_days)
        )
    result = db.execute(statement)

    record_audit(
        db,
        admin=auth.user,
        action=AuditAction.HISTORY_CLEARED,
        target_type="history",
        meta={"older_than_days": older_than_days, "removed": int(result.rowcount or 0)},
        ip=client_ip(request),
    )
    db.commit()
    return {"deleted": int(result.rowcount or 0)}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    auth: RequireAdminVerified,
    db: DbSession,
    request: Request,
) -> dict:
    """Create an account directly, bypassing the registration toggle.

    The new account is flagged ``must_change_password`` so the operator-chosen
    password is only ever a one-time handover value.
    """
    from app.services.auth import register_user

    assert auth.user is not None
    user = register_user(
        db,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        role=payload.role,
        enforce_settings=False,
        must_change_password=True,
    )
    record_audit(
        db,
        admin=auth.user,
        action=AuditAction.USER_CREATED,
        target_type="user",
        target_id=str(user.id),
        target_label=user.display_username,
        # Only the role is recorded; the password is never referenced.
        meta={"role": payload.role},
        ip=client_ip(request),
    )
    db.commit()
    return _user_summary(user)
