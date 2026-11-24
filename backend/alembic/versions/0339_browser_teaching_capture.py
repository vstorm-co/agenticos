"""Add owner-bound structural browser teaching sessions (#113, slice 1).

Revision ID: 0339_browser_teaching_capture
Revises: 0338_message_reply_excerpt

A teaching session records one person's demonstration in one held browser tab
of one run. It stores only structural steps: an exact HTTPS origin, a role and
a hashed structural fingerprint. The table has no column for a URL path, query,
fragment, typed value, page text, cookie, screenshot or script.

The table is new and empty, so it is created with its constraints in place. A
partial unique index allows one active (recording or paused) session per live
view; the request-key unique constraint makes a repeated start idempotent. A
discarded or expired row must have its payload erased, enforced by a CHECK.

Downgrade drops the table. Its rows are transient demonstrations that expire
after 24 hours, and the feature is disabled by default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0339_browser_teaching_capture"
down_revision: str | None = "0338_message_reply_excerpt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_teaching_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.String(length=200), nullable=False),
        sa.Column("tab_id", sa.String(length=200), nullable=False),
        sa.Column("hold_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("allowed_origins", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "sanitized_events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("capture_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('recording', 'paused', 'review', 'discarded', 'expired')",
            name=op.f("browser_teaching_sessions_state_check"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("browser_teaching_sessions_revision_check")),
        sa.CheckConstraint(
            "jsonb_typeof(sanitized_events) = 'array' AND jsonb_array_length(sanitized_events) <= 500 "
            "AND octet_length(sanitized_events::text) <= 131072",
            name=op.f("browser_teaching_sessions_events_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_origins) = 'array' AND jsonb_array_length(allowed_origins) <= 10",
            name=op.f("browser_teaching_sessions_origins_check"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('discarded', 'expired') OR "
            "(sanitized_events = '[]'::jsonb AND allowed_origins = '[]'::jsonb AND title = '')",
            name=op.f("browser_teaching_sessions_erased_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("browser_teaching_sessions_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("browser_teaching_sessions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("browser_teaching_sessions_owner_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("browser_teaching_sessions_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("browser_teaching_sessions_pkey")),
        sa.UniqueConstraint(
            "organization_id", "owner_user_id", "request_key", name="uq_browser_teaching_request"
        ),
    )
    op.create_index(
        "ix_browser_teaching_owner",
        "browser_teaching_sessions",
        ["organization_id", "owner_user_id", "created_at"],
    )
    op.create_index("ix_browser_teaching_expiry", "browser_teaching_sessions", ["expires_at"])
    op.create_index(
        "uq_browser_teaching_active_view",
        "browser_teaching_sessions",
        ["organization_id", "run_id", "call_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('recording', 'paused')"),
    )


def downgrade() -> None:
    op.drop_index("uq_browser_teaching_active_view", table_name="browser_teaching_sessions")
    op.drop_index("ix_browser_teaching_expiry", table_name="browser_teaching_sessions")
    op.drop_index("ix_browser_teaching_owner", table_name="browser_teaching_sessions")
    op.drop_table("browser_teaching_sessions")
