"""Give routines separate follow-up chats or one read-only history.

Existing destinations map to the new modes without rewriting schedules, source
consent or existing transcripts. Legacy destination columns remain for runs
admitted before the upgrade and allow a downgrade without losing their settings.
"""

import sqlalchemy as sa

from alembic import op

revision = "0351_routine_chat_modes"
down_revision = "0350_run_reporting_credential"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("chat_mode", sa.String(16), nullable=False, server_default="shared"),
    )
    op.execute(
        "UPDATE agent_triggers SET chat_mode = 'per_run' "
        "WHERE answer_to != 'run_log' AND result_mode != 'inbox'"
    )
    op.create_check_constraint(
        "ck_trigger_chat_mode", "agent_triggers", "chat_mode IN ('per_run', 'shared')"
    )
    op.execute(
        "UPDATE conversations SET origin = 'routine' FROM agent_triggers WHERE conversations.id = agent_triggers.conversation_id AND conversations.organization_id = agent_triggers.organization_id AND conversations.user_id IS NULL AND conversations.origin IS NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE conversations SET origin = NULL WHERE origin = 'routine'")
    op.drop_constraint("ck_trigger_chat_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "chat_mode")
