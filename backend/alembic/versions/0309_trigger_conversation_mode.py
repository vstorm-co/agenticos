"""Scheduled runs choose their conversation, and GitHub fires keep their payload.

Two changes in one revision because they share the fire path (#14):

1. `agent_triggers.conversation_mode` - `continue` (the default, today's
   behaviour: every fire appends to the trigger's one run-log conversation) or
   `fresh` (a new conversation per fire, stored nowhere on the trigger). The
   column carries a server default so existing rows read as `continue` without
   a backfill. There is no third mode naming one conversation to keep
   appending to.
2. `routine_device_waits.event_payload` - the full GitHub delivery parked
   beside its rendered `event_context`, so a fire that waits for its computer
   still hands the run the whole payload when it wakes. The direct path
   carries it on the `fire-trigger` job instead; this row is the waiting
   path's carrier. The redaction CHECK is widened to cover it: a settled wait
   clears both.

This revision also joins the chain's two heads. At this base `t3` holds
`0305a_totp_last_counter` and `0306_run_retry_link` with no merge between
them - #67's `0308_merge_0305a_and_0307` is still a draft on its own branch,
not on `t3`, so it is not a head here. If #67 lands first, this revision
re-chains onto `0308_merge_0305a_and_0307` (and #67's `0307` then needs no
second merge).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0309_trigger_conversation_mode"
down_revision: str | None = "0307_failure_learning_phase2"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("conversation_mode", sa.String(16), nullable=False, server_default="continue"),
    )
    op.create_check_constraint(
        "ck_trigger_conversation_mode",
        "agent_triggers",
        "conversation_mode IN ('continue', 'fresh')",
    )
    op.add_column(
        "routine_device_waits",
        sa.Column("event_payload", JSONB(), nullable=True),
    )
    op.drop_constraint("ck_routine_device_wait_redacted", "routine_device_waits", type_="check")
    op.create_check_constraint(
        "ck_routine_device_wait_redacted",
        "routine_device_waits",
        "status IN ('waiting', 'failed') OR (event_context IS NULL AND event_payload IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_routine_device_wait_redacted", "routine_device_waits", type_="check")
    op.create_check_constraint(
        "ck_routine_device_wait_redacted",
        "routine_device_waits",
        "status IN ('waiting', 'failed') OR event_context IS NULL",
    )
    op.drop_column("routine_device_waits", "event_payload")
    op.drop_constraint("ck_trigger_conversation_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "conversation_mode")
