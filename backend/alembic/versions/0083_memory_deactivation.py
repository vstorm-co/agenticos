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

`written_at` comes with it, and for the same feature. `updated_at` advances on
any write to the row, so once a person can suppress a note, reading provenance
off it makes the page say the *agent* wrote the note at the moment somebody
silenced it - and moves the note to the top of their listing for having been
silenced. `written_at` is moved by the agent's own writes and by nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0083_memory_deactivation"
down_revision: str | Sequence[str] | None = "0082_portal_account_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_memory_files",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_memory_files",
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=True),
    )
    # What the agent last wrote, for rows that predate the column. `updated_at`
    # is null until a row is edited, so `created_at` is the honest fallback -
    # and nothing has suppressed anything yet, so neither can be wrong.
    op.execute("UPDATE agent_memory_files SET written_at = COALESCE(updated_at, created_at)")


def downgrade() -> None:
    op.drop_column("agent_memory_files", "written_at")
    op.drop_column("agent_memory_files", "deactivated_at")
