"""Check dataset source links after conversation-delete cascades finish.

Revision ID: 0358_defer_dataset_source_links
Revises: 0357_accepted_queued_messages
Create Date: 2026-11-26

A conversation delete removes its messages and clears both source pointers on
surviving dataset cases. PostgreSQL can check a newly written case after one
parent has disappeared but before the other SET NULL action has run. Queue
receipt cross-links exposed this existing dependence on foreign-key trigger
order; arranging metadata creation differently cannot protect upgraded schemas.

Defer the two source checks, as 0305_defer_delete_crosslinks.py does for other
surviving cross-links. SET NULL still runs during deletion and invalid surviving
references fail at commit. ALTER preserves the constraints, actions, indexes and
stored cases. A five-second lock timeout bounds the catalog lock wait. Downgrade
restores immediate checks and their former sensitivity to trigger order.
"""

from alembic import op

revision: str = "0358_defer_dataset_source_links"
down_revision: str = "0357_accepted_queued_messages"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE dataset_cases ALTER CONSTRAINT "
        "dataset_cases_source_conversation_id_fkey DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE dataset_cases ALTER CONSTRAINT "
        "dataset_cases_source_message_id_fkey DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE dataset_cases ALTER CONSTRAINT "
        "dataset_cases_source_message_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE"
    )
    op.execute(
        "ALTER TABLE dataset_cases ALTER CONSTRAINT "
        "dataset_cases_source_conversation_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE"
    )
