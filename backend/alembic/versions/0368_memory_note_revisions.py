"""Make maintenance opt-in per existing note, with restorable prior content."""

import sqlalchemy as sa

from alembic import op

revision: str = "0368_memory_note_revisions"
down_revision: str = "0367_memory_workflow_sources"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    notes = "agent_memory_files"
    revisions = "memory_note_revisions"
    op.add_column(
        notes, sa.Column("auto_update", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        notes,
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("memory_objects.id", ondelete="SET NULL")),
    )
    op.create_index("agent_memory_files_object_id_idx", notes, ["object_id"])
    op.add_column(notes, sa.Column("maintenance_source_at", sa.DateTime(timezone=True)))
    op.add_column(
        notes,
        sa.Column(
            "maintenance_source_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
    )
    op.create_unique_constraint("uq_agent_memory_files_org_id", notes, ["organization_id", "id"])
    op.create_index(
        "ix_agent_memory_files_auto_update",
        notes,
        ["organization_id", "agent_id", "owner_key"],
        postgresql_where=sa.text("auto_update IS true AND deactivated_at IS NULL"),
    )
    op.create_table(
        revisions,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(16), nullable=False),
        sa.Column(
            "replaced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "source_message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "note_id"],
            ["agent_memory_files.organization_id", "agent_memory_files.id"],
            name="fk_memory_note_revisions_note",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "changed_by IN ('agent', 'person', 'maintenance', 'restore')",
            name="memory_note_revision_changed_by",
        ),
    )
    op.create_index(
        "ix_memory_note_revisions_order",
        revisions,
        ["organization_id", "note_id", "replaced_at", "id"],
    )


def downgrade() -> None:
    # Current notes are retained. Earlier versions and automatic update preferences are removed.
    op.drop_table("memory_note_revisions")
    op.drop_index("ix_agent_memory_files_auto_update", table_name="agent_memory_files")
    op.drop_constraint("uq_agent_memory_files_org_id", "agent_memory_files", type_="unique")
    op.drop_index("agent_memory_files_object_id_idx", table_name="agent_memory_files")
    op.drop_column("agent_memory_files", "object_id")
    op.drop_column("agent_memory_files", "maintenance_source_message_id")
    op.drop_column("agent_memory_files", "maintenance_source_at")
    op.drop_column("agent_memory_files", "auto_update")
