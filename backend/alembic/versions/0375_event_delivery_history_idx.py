"""Index the recent delivery lookup for each event source.

Delivery metadata remains after the retention sweep clears the payload. Match
the tenant and source, then scan the index backward by receipt time and ID so
opening recent deliveries does not sort the source's entire receipt history.

Revision ID: 0375_event_delivery_history_idx
Revises: 0374_case_from_conversation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0375_event_delivery_history_idx"
down_revision: str | None = "0374_case_from_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_event_delivery_history",
        "event_deliveries",
        ["organization_id", "source_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_delivery_history", table_name="event_deliveries")
