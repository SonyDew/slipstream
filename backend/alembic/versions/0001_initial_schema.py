"""Initial schema: users, sessions, jobs, history, audit log, settings

Revision ID: e51e0b196f5e
Revises:
Create Date: 2026-08-24 20:52:16.879503
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base  # custom UTCDateTime / JSONEncodedDict column types

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', app.db.base.JSONEncodedDict(), nullable=True),
    sa.Column('value_type', sa.String(length=16), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('display_username', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('password_changed_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_users_email'),
    sa.UniqueConstraint('username', name='uq_users_username')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=False)
        batch_op.create_index('ix_users_role_active', ['role', 'is_active'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=False)

    op.create_table('admin_audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('admin_user_id', sa.Integer(), nullable=True),
    sa.Column('admin_username', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('target_label', sa.String(length=255), nullable=True),
    sa.Column('meta', app.db.base.JSONEncodedDict(), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('admin_audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_admin_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_admin_audit_log_admin_user_id'), ['admin_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_admin_audit_log_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_audit_action', ['action'], unique=False)
        batch_op.create_index('ix_audit_admin_created', ['admin_user_id', 'created_at'], unique=False)
        batch_op.create_index('ix_audit_created', ['created_at'], unique=False)

    op.create_table('download_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('job_id', sa.String(length=36), nullable=True),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('source_domain', sa.String(length=255), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('author', sa.String(length=255), nullable=True),
    sa.Column('thumbnail', sa.Text(), nullable=True),
    sa.Column('media_type', sa.String(length=16), nullable=False),
    sa.Column('quality', sa.String(length=32), nullable=True),
    sa.Column('output_format', sa.String(length=16), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('download_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_download_history_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_history_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_history_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_history_user_id'), ['user_id'], unique=False)
        batch_op.create_index('ix_history_created', ['created_at'], unique=False)
        batch_op.create_index('ix_history_platform', ['platform'], unique=False)
        batch_op.create_index('ix_history_user_created', ['user_id', 'created_at'], unique=False)

    op.create_table('download_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('guest_key', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('source_domain', sa.String(length=255), nullable=False),
    sa.Column('media_id', sa.String(length=255), nullable=True),
    sa.Column('media_type', sa.String(length=16), nullable=False),
    sa.Column('requested_quality', sa.String(length=32), nullable=False),
    sa.Column('output_format', sa.String(length=16), nullable=False),
    sa.Column('selected_images', app.db.base.JSONEncodedDict(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('author', sa.String(length=255), nullable=True),
    sa.Column('thumbnail', sa.Text(), nullable=True),
    sa.Column('duration', sa.Integer(), nullable=True),
    sa.Column('extractor', sa.String(length=64), nullable=True),
    sa.Column('file_path', sa.Text(), nullable=True),
    sa.Column('file_name', sa.Text(), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('mime_type', sa.String(length=128), nullable=True),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('progress_label', sa.String(length=128), nullable=True),
    sa.Column('eta_seconds', sa.Integer(), nullable=True),
    sa.Column('speed_bps', sa.Integer(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('finished_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('expires_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('delivered_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('download_jobs', schema=None) as batch_op:
        batch_op.create_index('ix_download_jobs_claim', ['status', 'id'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_jobs_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_download_jobs_expires', ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_jobs_guest_key'), ['guest_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_jobs_platform'), ['platform'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_jobs_status'), ['status'], unique=False)
        batch_op.create_index('ix_download_jobs_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index('ix_download_jobs_user_created', ['user_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_jobs_user_id'), ['user_id'], unique=False)

    op.create_table('sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('expires_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('last_seen_at', app.db.base.UTCDateTime(), nullable=False),
    sa.Column('revoked_at', app.db.base.UTCDateTime(), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=256), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash', name='uq_sessions_token_hash')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_token_hash'), ['token_hash'], unique=False)
        batch_op.create_index('ix_sessions_user_expires', ['user_id', 'expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index('ix_sessions_user_expires')
        batch_op.drop_index(batch_op.f('ix_sessions_token_hash'))
        batch_op.drop_index(batch_op.f('ix_sessions_expires_at'))

    op.drop_table('sessions')
    with op.batch_alter_table('download_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_download_jobs_user_id'))
        batch_op.drop_index('ix_download_jobs_user_created')
        batch_op.drop_index('ix_download_jobs_status_created')
        batch_op.drop_index(batch_op.f('ix_download_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_download_jobs_platform'))
        batch_op.drop_index(batch_op.f('ix_download_jobs_guest_key'))
        batch_op.drop_index('ix_download_jobs_expires')
        batch_op.drop_index(batch_op.f('ix_download_jobs_created_at'))
        batch_op.drop_index('ix_download_jobs_claim')

    op.drop_table('download_jobs')
    with op.batch_alter_table('download_history', schema=None) as batch_op:
        batch_op.drop_index('ix_history_user_created')
        batch_op.drop_index('ix_history_platform')
        batch_op.drop_index('ix_history_created')
        batch_op.drop_index(batch_op.f('ix_download_history_user_id'))
        batch_op.drop_index(batch_op.f('ix_download_history_status'))
        batch_op.drop_index(batch_op.f('ix_download_history_job_id'))
        batch_op.drop_index(batch_op.f('ix_download_history_created_at'))

    op.drop_table('download_history')
    with op.batch_alter_table('admin_audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_created')
        batch_op.drop_index('ix_audit_admin_created')
        batch_op.drop_index('ix_audit_action')
        batch_op.drop_index(batch_op.f('ix_admin_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_log_admin_user_id'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_log_action'))

    op.drop_table('admin_audit_log')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))
        batch_op.drop_index('ix_users_role_active')
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_index(batch_op.f('ix_users_created_at'))

    op.drop_table('users')
    op.drop_table('app_settings')
