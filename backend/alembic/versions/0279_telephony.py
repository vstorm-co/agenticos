"""telephony

Revision ID: 0279_telephony
Revises: 0278_decision_episodes
Create Date: 2026-11-04 12:51:45.717962

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0279_telephony"
down_revision: str | None = "0278_decision_episodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phone_contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("identity_generation", sa.UUID(), nullable=False),
        sa.Column("allow_calls", sa.Boolean(), nullable=False),
        sa.Column("allow_reports", sa.Boolean(), nullable=False),
        sa.Column("allow_transfers", sa.Boolean(), nullable=False),
        sa.Column("report_language", sa.String(length=8), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("quiet_start_hour", sa.Integer(), nullable=False),
        sa.Column("quiet_end_hour", sa.Integer(), nullable=False),
        sa.Column("calls_per_day", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["channel_identities.id"],
            name=op.f("phone_contacts_identity_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("phone_contacts_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("phone_contacts_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("phone_contacts_pkey")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_phone_contact_member"),
    )
    op.create_table(
        "phone_endpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("bot_id", sa.UUID(), nullable=False),
        sa.Column("bot_generation", sa.UUID(), nullable=False),
        sa.Column("generation", sa.UUID(), nullable=False),
        sa.Column("inbound_embed_id", sa.UUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_call_seconds", sa.Integer(), nullable=False),
        sa.Column("calls_per_hour", sa.Integer(), nullable=False),
        sa.Column("calls_per_day", sa.Integer(), nullable=False),
        sa.Column("max_concurrent", sa.Integer(), nullable=False),
        sa.Column("daily_budget_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("price_per_minute_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("transfer_contact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["channel_bots.id"],
            name=op.f("phone_endpoints_bot_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_embed_id"],
            ["agent_embeds.id"],
            name=op.f("phone_endpoints_inbound_embed_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("phone_endpoints_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("phone_endpoints_pkey")),
        sa.UniqueConstraint("bot_id", name=op.f("phone_endpoints_bot_id_key")),
    )
    op.create_index(
        op.f("phone_endpoints_organization_id_idx"),
        "phone_endpoints",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "phone_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("endpoint_generation", sa.UUID(), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("contact_hash", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column(
            "agent_version_id",
            sa.UUID(),
            sa.ForeignKey("agent_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_context_required", sa.Boolean(), nullable=False),
        sa.Column("source_required", sa.Boolean(), nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("voice_call_id", sa.UUID(), nullable=True),
        sa.Column("account_sid", sa.String(length=34), nullable=False),
        sa.Column("provider_sid", sa.String(length=34), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
        sa.Column("destination", sa.String(length=20), nullable=True),
        sa.Column("report_language", sa.String(length=8), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("cap_seconds", sa.Integer(), nullable=False),
        sa.Column("price_per_minute_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stream_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transferred_contact_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("phone_calls_agent_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["phone_contacts.id"],
            name=op.f("phone_calls_contact_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("phone_calls_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["phone_endpoints.id"],
            name=op.f("phone_calls_endpoint_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("phone_calls_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversations.id"],
            name=op.f("phone_calls_source_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("phone_calls_source_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transferred_contact_id"],
            ["phone_contacts.id"],
            name=op.f("phone_calls_transferred_contact_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("phone_calls_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["voice_call_id"],
            ["voice_calls.id"],
            name=op.f("phone_calls_voice_call_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("phone_calls_pkey")),
        sa.UniqueConstraint("organization_id", "request_key", name="uq_phone_call_request"),
        sa.UniqueConstraint("provider_sid", name=op.f("phone_calls_provider_sid_key")),
    )
    op.create_index(
        op.f("phone_calls_endpoint_id_idx"), "phone_calls", ["endpoint_id"], unique=False
    )
    op.create_index(op.f("phone_calls_expires_at_idx"), "phone_calls", ["expires_at"], unique=False)
    op.create_index(
        op.f("phone_calls_organization_id_idx"), "phone_calls", ["organization_id"], unique=False
    )
    op.create_index(op.f("phone_calls_user_id_idx"), "phone_calls", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("phone_calls_user_id_idx"), table_name="phone_calls")
    op.drop_index(op.f("phone_calls_organization_id_idx"), table_name="phone_calls")
    op.drop_index(op.f("phone_calls_expires_at_idx"), table_name="phone_calls")
    op.drop_index(op.f("phone_calls_endpoint_id_idx"), table_name="phone_calls")
    op.drop_table("phone_calls")
    op.drop_index(op.f("phone_endpoints_organization_id_idx"), table_name="phone_endpoints")
    op.drop_table("phone_endpoints")
    op.drop_table("phone_contacts")
