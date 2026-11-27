"""Add audience-scoped memory identities and prospective knowledge history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0365_memory_objects_and_history"
down_revision: str = "0364_merge_routine_and_kb"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "memory_mail_sources",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("grant_id", sa.Uuid(), sa.ForeignKey("mcp_connections.id", ondelete="SET NULL")),
        sa.Column("authorization_generation", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("sender", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("commitment", sa.String(160), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("admitted_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_outcome", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "memory_mail_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("memory_mail_sources.organization_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(200), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quote", sa.String(64), nullable=False),
        sa.Column(
            "admitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "grant_id",
            "delivery_id",
            name="uq_memory_mail_events_delivery",
        ),
    )
    op.create_index(
        "ix_memory_mail_events_date", "memory_mail_events", ["organization_id", "admitted_at"]
    )
    op.add_column("memory_claims", sa.Column("mail_event_id", sa.Uuid()))
    op.create_foreign_key(
        "memory_claims_mail_event_id_fkey",
        "memory_claims",
        "memory_mail_events",
        ["mail_event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("memory_claims_mail_event_id_idx", "memory_claims", ["mail_event_id"])
    op.create_table(
        "memory_objects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("identity_key", sa.String(300), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id",
            "scope_key",
            "kind",
            "identity_key",
            name="uq_memory_objects_identity",
        ),
    )
    op.create_index(
        "ix_memory_objects_browse", "memory_objects", ["organization_id", "scope_key", "kind", "id"]
    )
    op.add_column("memory_claims", sa.Column("object_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "memory_claims_object_id_fkey",
        "memory_claims",
        "memory_objects",
        ["object_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_memory_claims_object", "memory_claims", ["object_id", "observed_at", "id"])
    op.create_table(
        "memory_claim_revisions",
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("memory_claims.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("known_from", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("memory_claims", sa.Column("value", postgresql.JSONB(none_as_null=True)))
    op.create_table(
        "memory_claim_evidence",
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("memory_claims.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("quote", sa.String(300), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("memory_claim_evidence_message_id_idx", "memory_claim_evidence", ["message_id"])
    op.create_table(
        "shared_memory_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("agent_memory_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id", "scope_key", name="uq_shared_memory_note_source"),
    )
    op.create_index(
        "ix_shared_memory_notes_scope",
        "shared_memory_notes",
        ["organization_id", "scope_key", "id"],
    )


def downgrade() -> None:
    op.drop_table("memory_claim_evidence")
    op.drop_column("memory_claims", "value")
    op.drop_table("shared_memory_notes")
    op.drop_table("memory_claim_revisions")
    op.drop_index("ix_memory_claims_object", table_name="memory_claims")
    op.drop_constraint("memory_claims_object_id_fkey", "memory_claims", type_="foreignkey")
    op.drop_column("memory_claims", "object_id")
    op.drop_table("memory_objects")
    op.drop_index("memory_claims_mail_event_id_idx", table_name="memory_claims")
    op.drop_constraint("memory_claims_mail_event_id_fkey", "memory_claims", type_="foreignkey")
    op.drop_column("memory_claims", "mail_event_id")
    op.drop_table("memory_mail_events")
    op.drop_table("memory_mail_sources")
