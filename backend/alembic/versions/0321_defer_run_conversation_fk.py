"""Check a run's conversation link after all of an account's delete cascades finish.

Deleting an account deletes the person's conversations and clears the person on
their runs. The erasure has already written those runs in the same transaction,
so PostgreSQL rechecks every foreign key on them when the SET NULL updates the
row. If that update is checked after the conversation cascade, it sees the
conversation already gone and the delete fails on
`agent_runs_conversation_id_fkey`. Which action runs first follows the RI
trigger names, which end in their OID, so the outcome differs between databases.

Defer the run-to-conversation check, as 0305_defer_delete_crosslinks.py does for
two other cross-links. SET NULL still runs during the delete; a reference left
dangling fails at commit. ALTER keeps the constraint, its action and existing
rows. Downgrade restores the immediate check and the ordering sensitivity.
"""

from alembic import op

revision: str = "0321_defer_run_conversation_fk"
down_revision: str = "0320_record_batch_receipts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_runs ALTER CONSTRAINT "
        "agent_runs_conversation_id_fkey DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_runs ALTER CONSTRAINT "
        "agent_runs_conversation_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE"
    )
