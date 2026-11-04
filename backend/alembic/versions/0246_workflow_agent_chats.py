"""Give workflow agent steps private durable conversations.

Internal threads retain sandbox files and model history across chat turns without
writing intermediate answers into the caller's chat. Tenant-scoped foreign keys
remove these threads with their workflow or source conversation. Downgrade removes
only the internal threads before dropping their ownership columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0246_workflow_agent_chats"
down_revision: str | None = "0245_table_document_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("workflow_id", sa.UUID(), nullable=True))
    op.add_column("conversations", sa.Column("source_conversation_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("conversations_source_conversation_id_idx"),
        "conversations",
        ["source_conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("conversations_workflow_id_idx"), "conversations", ["workflow_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_conversation_org_id", "conversations", ["organization_id", "id"]
    )
    op.create_foreign_key(
        "fk_conversation_source",
        "conversations",
        "conversations",
        ["organization_id", "source_conversation_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_conversation_workflow",
        "conversations",
        "workflows",
        ["organization_id", "workflow_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM conversations WHERE workflow_id IS NOT NULL"))
    op.drop_constraint("fk_conversation_workflow", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversation_source", "conversations", type_="foreignkey")
    op.drop_constraint("uq_conversation_org_id", "conversations", type_="unique")
    op.drop_index(op.f("conversations_workflow_id_idx"), table_name="conversations")
    op.drop_index(op.f("conversations_source_conversation_id_idx"), table_name="conversations")
    op.drop_column("conversations", "source_conversation_id")
    op.drop_column("conversations", "workflow_id")
