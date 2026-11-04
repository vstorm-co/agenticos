"""WhatsApp public line: a run that acts as its agent, and requests to bind one (#2076).

Revision ID: 0259_whatsapp_public_line
Revises: 0258_whatsapp_followups
Create Date: 2026-11-04

`agent_runs.runs_as_agent` records that a run acted as its agent with only the grants
its spec gives, and as no member: `user_id` is NULL for it. A run on a line that answers
a customer who never linked an account is one. Existing rows are `false`, which is what
they were.

`channel_binding_requests` holds what a member who may publish an agent but not manage
channels asks of a bot that answers people with no account: to bind the agent, move the
binding to another environment, or turn a paused binding back on. Two notification types
tell the people who decide it, and the one who asked. The notification CHECKs are widened
with them; the downgrade deletes the rows of the new types before narrowing them again.

Later changes to the public line extend this revision rather than adding another.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0259_whatsapp_public_line"
down_revision: str | None = "0258_whatsapp_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'workflow_log_alert'"
)
_NEW_TYPES = ("channel_binding_requested", "channel_binding_decided")
_AFTER = f"{_BEFORE}, " + ", ".join(f"'{event}'" for event in _NEW_TYPES)

_CHECKS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)

_TABLE = "channel_binding_requests"


def _recreate(values: str) -> None:
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("runs_as_agent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        _TABLE,
        sa.Column("id", uuid, nullable=False),
        sa.Column("organization_id", uuid, nullable=False),
        sa.Column("channel_bot_id", uuid, nullable=False),
        sa.Column("agent_id", uuid, nullable=False),
        sa.Column("exposure_id", uuid, nullable=True),
        sa.Column("environment_id", uuid, nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("requester_user_id", uuid, nullable=False),
        sa.Column("requester_membership_id", uuid, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("session_scope", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("void_reason", sa.String(length=32), nullable=True),
        sa.Column("decided_by_user_id", uuid, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('bind', 'environment', 'resume')",
            name=op.f("channel_binding_requests_ck_channel_binding_request_kind_check"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'voided')",
            name=op.f("channel_binding_requests_ck_channel_binding_request_status_check"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 500",
            name=op.f("channel_binding_requests_ck_channel_binding_request_note_check"),
        ),
        sa.CheckConstraint(
            "(kind = 'bind') = (exposure_id IS NULL)",
            name=op.f("channel_binding_requests_ck_channel_binding_request_exposure_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("channel_binding_requests_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_bot_id"],
            ["channel_bots.id"],
            name=op.f("channel_binding_requests_channel_bot_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("channel_binding_requests_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exposure_id"],
            ["agent_exposures.id"],
            name=op.f("channel_binding_requests_exposure_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("channel_binding_requests_environment_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["users.id"],
            name=op.f("channel_binding_requests_requester_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("channel_binding_requests_decided_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("channel_binding_requests_pkey")),
    )
    op.create_index(
        op.f("channel_binding_requests_organization_id_idx"), _TABLE, ["organization_id"]
    )
    op.create_index(op.f("channel_binding_requests_channel_bot_id_idx"), _TABLE, ["channel_bot_id"])
    op.create_index(
        "uq_channel_binding_request_pending",
        _TABLE,
        ["channel_bot_id", "requester_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    _recreate(_AFTER)


def downgrade() -> None:
    for table, _name in _CHECKS:
        op.execute(
            f"DELETE FROM {table} WHERE event_type IN ("
            + ", ".join(f"'{event}'" for event in _NEW_TYPES)
            + ")"
        )
    _recreate(_BEFORE)
    op.drop_index("uq_channel_binding_request_pending", table_name=_TABLE)
    op.drop_index(op.f("channel_binding_requests_channel_bot_id_idx"), table_name=_TABLE)
    op.drop_index(op.f("channel_binding_requests_organization_id_idx"), table_name=_TABLE)
    op.drop_table(_TABLE)
    op.drop_column("agent_runs", "runs_as_agent")
