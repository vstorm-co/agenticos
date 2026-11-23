"""A routine answer stored in a private chat reads `pending` until the bot posts it.

Downgrade reads `pending` as `delivered`: that is exactly what the code before
this revision recorded when it stored the answer in the conversation and posted
nothing, so no row is left that the older check would refuse.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0350_trigger_delivery_pending"
down_revision: str | None = "0349_personal_work_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "'delivered', 'unavailable', 'run_log', 'no_answer', 'not_completed'"


def upgrade() -> None:
    op.drop_constraint("ck_trigger_delivery_status", "agent_triggers", type_="check")
    op.create_check_constraint(
        "ck_trigger_delivery_status",
        "agent_triggers",
        f"last_delivery_status IN ({_OLD}, 'pending')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_delivery_status", "agent_triggers", type_="check")
    op.execute(
        "UPDATE agent_triggers SET last_delivery_status = 'delivered' "
        "WHERE last_delivery_status = 'pending'"
    )
    op.create_check_constraint(
        "ck_trigger_delivery_status", "agent_triggers", f"last_delivery_status IN ({_OLD})"
    )
