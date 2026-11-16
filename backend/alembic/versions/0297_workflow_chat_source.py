"""Keep chat refusal provenance separate from workflow input and reply delivery.

A retry must not send another reply to the original chat, and a called workflow
has its own input. Both still need to mark the exact source turn if an agent
refuses it. Nullable references preserve that identity without retaining deleted
conversations or messages. A durable flag fails closed after source deletion.
Existing runs without a known source remain unlinked.
A refusal revision fences concurrent compactors; pre-existing cached summaries
are rebuilt once because they predate that fence. The transcript is retained.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0297_workflow_chat_source"
down_revision: str = "0296_tool_identity"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("guardrail_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    # Older summaries have no refusal revision; rebuild them from guarded rows.
    op.execute(
        "UPDATE conversations SET summary_messages = NULL, summary_ordinal = NULL WHERE summary_messages IS NOT NULL OR summary_ordinal IS NOT NULL"
    )
    # Legacy parked histories have no revision and may resume only at revision 0.
    op.execute(
        "UPDATE conversations SET guardrail_revision = 1 WHERE EXISTS (SELECT 1 FROM messages WHERE messages.conversation_id = conversations.id AND messages.guardrail_refused IS TRUE)"
    )
    op.add_column(
        "workflow_runs",
        sa.Column("has_chat_source", sa.Boolean(), nullable=False, server_default="false"),
    )
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
    # The previous API forbids unknown fields in this stored JSON model.
    op.execute(
        "UPDATE agent_runs SET paused_state = paused_state - 'guardrail_revision' WHERE paused_state ? 'guardrail_revision'"
    )
    op.drop_index("workflow_runs_source_message_id_idx", table_name="workflow_runs")
    op.drop_index("workflow_runs_source_conversation_id_idx", table_name="workflow_runs")
    op.drop_column("workflow_runs", "has_chat_source")
    op.drop_column("workflow_runs", "source_message_id")
    op.drop_column("workflow_runs", "source_conversation_id")
    op.drop_column("conversations", "guardrail_revision")
