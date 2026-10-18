"""Voice conversations: the call row, and runs that say how they were held (#54).

`voice_calls` is what a hang-up needs without the session. A call over WebRTC
is the provider's, not ours: the browser holds the audio, and closing our
sideband leaves it talking and billing. So each connection writes a row at
setup carrying the provider's call id, the key, the worker holding it and a
heartbeat; the reaper hangs up any row whose heartbeat went stale or whose end
was recorded without a confirmed hang-up. Each reconnect is its own row linked
by `resume_of`, so minutes and budgets carry over the chain. Monthly minutes
are summed from these rows, never from run durations.

`agent_runs.modality` (`text` default, `voice`) rather than a new
`RunSurface` member: where a run came from and how it was held are two
questions, and a call in the widget is still the widget. Existing runs take
the server default `text`.

Revision ID: 0142_voice_calls
Revises: 0141_org_voice_settings
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0142_voice_calls"
down_revision: str | None = "0141_org_voice_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("modality", sa.String(length=8), server_default="text", nullable=False),
    )
    op.create_check_constraint(
        op.f("agent_runs_ck_agent_runs_modality_check"),
        "agent_runs",
        "modality IN ('text', 'voice')",
    )
    op.create_table(
        "voice_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("embed_id", sa.UUID(), nullable=True),
        sa.Column("surface", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("transport", sa.String(length=8), nullable=False),
        sa.Column("provider_call_id", sa.String(length=128), nullable=True),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("resume_of", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=16), nullable=True),
        sa.Column("hung_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("guardrail_hits", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('user', 'time_limit', 'budget', 'minutes', 'disconnected', 'revoked', 'guardrail', 'error', 'shutdown', 'reaped', 'abandoned')",
            name=op.f("voice_calls_ck_voice_calls_end_reason_check"),
        ),
        sa.CheckConstraint(
            "surface IN ('web', 'embed')", name=op.f("voice_calls_ck_voice_calls_surface_check")
        ),
        sa.CheckConstraint(
            "transport IN ('webrtc', 'relay')",
            name=op.f("voice_calls_ck_voice_calls_transport_check"),
        ),
        sa.CheckConstraint("seconds >= 0", name=op.f("voice_calls_ck_voice_calls_seconds_check")),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("voice_calls_agent_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("voice_calls_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["embed_id"],
            ["agent_embeds.id"],
            name=op.f("voice_calls_embed_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("voice_calls_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_of"],
            ["voice_calls.id"],
            name=op.f("voice_calls_resume_of_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("voice_calls_run_id_fkey"),
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["organization_secrets.id"],
            name=op.f("voice_calls_secret_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("voice_calls_user_id_fkey"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("voice_calls_pkey")),
    )
    op.create_index(
        "ix_voice_calls_org_started", "voice_calls", ["organization_id", "started_at"], unique=False
    )
    op.create_index(
        "ix_voice_calls_unhung",
        "voice_calls",
        ["heartbeat_at"],
        unique=False,
        postgresql_where=sa.text("hung_up_at IS NULL"),
    )
    op.create_index(op.f("voice_calls_run_id_idx"), "voice_calls", ["run_id"], unique=False)
    op.create_index(op.f("voice_calls_user_id_idx"), "voice_calls", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("voice_calls_user_id_idx"), table_name="voice_calls")
    op.drop_index(op.f("voice_calls_run_id_idx"), table_name="voice_calls")
    op.drop_index(
        "ix_voice_calls_unhung",
        table_name="voice_calls",
        postgresql_where=sa.text("hung_up_at IS NULL"),
    )
    op.drop_index("ix_voice_calls_org_started", table_name="voice_calls")
    op.drop_table("voice_calls")
    op.drop_constraint(op.f("agent_runs_ck_agent_runs_modality_check"), "agent_runs", type_="check")
    op.drop_column("agent_runs", "modality")
