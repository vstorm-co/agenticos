"""A person may suppress one of their own memory notes without destroying it.

The product decision before this was erasure only: a person could ask that
everything an agent knew about them be forgotten, and could see none of it. That
is the wrong shape for somebody who has found one note that is wrong, or too
personal, and is not yet sure they want it gone (#1594).

`deactivated_at` is that middle answer. A suppressed note is not listed, not read
and not editable by any tool, so it stops reaching the model; it is still the
person's to look at and to restore. Nullable and unset everywhere, so nothing
changes for a deployment that upgrades into it.

The column is the person's decision and the agent cannot clear it - with one
documented exception, in `app/db/models/memory.py`: writing the same name again
revives the row with new content, because what the person suppressed is then
overwritten rather than resurrected.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0083_memory_deactivation"
down_revision: str | Sequence[str] | None = "0080_audit_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_memory_files",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_memory_files", "deactivated_at")
