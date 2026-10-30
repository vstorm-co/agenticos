"""Which sign-in registered each push subscription and iPhone (#2305).

`session_id` on `push_subscriptions` and `apns_devices`, so the Devices list can
say which signed-in device receives push. Null for every existing row, and set
null again when the session is removed: the subscription stays, the device
just no longer says it is that sign-in's.

Revision ID: 0175_push_session
Revises: 0174_trigger_local_target
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0175_push_session"
down_revision: str | None = "0174_trigger_local_target"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("push_subscriptions", "apns_devices")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"{table}_session_id_fkey",
            table,
            "sessions",
            ["session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"{table}_session_id_idx", table, ["session_id"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"{table}_session_id_idx", table_name=table)
        op.drop_constraint(f"{table}_session_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "session_id")
