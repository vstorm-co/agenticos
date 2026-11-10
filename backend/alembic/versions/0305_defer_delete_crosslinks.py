"""Check surviving cross-links after all parent-delete cascades finish (#2841).

Deleting a routine creator deletes their conversations and clears the creator on
their routines. Deleting an agent deletes its environments and clears the agent
on its artifacts. In either diamond, an immediate FK check can see the child
already gone before its SET NULL action runs. PostgreSQL's internal trigger order
depends on constraint creation order, including the unordered cyclic FKs from
metadata.create_all. The recheck occurs when the surviving row was written in the
same transaction. This also reproduces on a migrated schema after reordering its
constraints, so changing only test setup would leave the defect in the schema.

Defer just the two cross-link checks, as voice_calls.run_id already does. SET NULL
still runs during the delete; invalid surviving references fail at commit. ALTER
preserves the constraints, their actions, and existing rows without rebuilding
them. Downgrade restores immediate checks and the previous ordering sensitivity.
"""

from alembic import op

revision: str = "0305_defer_delete_crosslinks"
down_revision: str = "0304_merge_evals_platform"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_triggers ALTER CONSTRAINT "
        "agent_triggers_delivery_conversation_id_fkey DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE artifacts ALTER CONSTRAINT "
        "artifacts_environment_id_fkey DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE artifacts ALTER CONSTRAINT "
        "artifacts_environment_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE"
    )
    op.execute(
        "ALTER TABLE agent_triggers ALTER CONSTRAINT "
        "agent_triggers_delivery_conversation_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE"
    )
