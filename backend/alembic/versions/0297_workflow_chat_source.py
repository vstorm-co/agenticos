"""Keep chat refusal provenance separate from workflow input and reply delivery.

A retry must not send another reply to the original chat, and a called workflow
has its own input. Both still need to mark the exact source turn if an agent
refuses it. Nullable references preserve that identity without retaining deleted
conversations or messages. Existing runs without a known source remain unlinked.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0297_workflow_chat_source"
down_revision: str = "0296_tool_identity"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("source_conversation_id", sa.UUID(), nullable=True))
    op.add_column("workflow_runs", sa.Column("source_message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "workflow_runs_source_conversation_id_fkey",
        "workflow_runs",
        "conversations",
        ["source_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "workflow_runs_source_message_id_fkey",
        "workflow_runs",
        "messages",
        ["source_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "workflow_runs_source_conversation_id_idx", "workflow_runs", ["source_conversation_id"]
    )
    op.create_index("workflow_runs_source_message_id_idx", "workflow_runs", ["source_message_id"])


def downgrade() -> None:
    op.drop_index("workflow_runs_source_message_id_idx", table_name="workflow_runs")
    op.drop_index("workflow_runs_source_conversation_id_idx", table_name="workflow_runs")
    op.drop_column("workflow_runs", "source_message_id")
    op.drop_column("workflow_runs", "source_conversation_id")
