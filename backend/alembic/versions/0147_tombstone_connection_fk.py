"""A sandbox tombstone holds its connection rather than going with it (#2250).

Deleting a connection counted its pending destroys and found none; a
conversation deleted at the same moment then wrote one, and the connection's
`ON DELETE CASCADE` erased it - the only record of a sandbox the provider still
bills for. NO ACTION makes that delete fail instead, and the service answers it
with the same refusal the count gives.

Revision ID: 0147_tombstone_connection_fk
Revises: 0146_trigger_overlap
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0147_tombstone_connection_fk"
down_revision: str | None = "0146_trigger_overlap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "pending_sandbox_destroys_connection_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "pending_sandbox_destroys", type_="foreignkey")
    op.create_foreign_key(
        _FK, "pending_sandbox_destroys", "sandbox_connections", ["connection_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "pending_sandbox_destroys", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "pending_sandbox_destroys",
        "sandbox_connections",
        ["connection_id"],
        ["id"],
        ondelete="CASCADE",
    )
