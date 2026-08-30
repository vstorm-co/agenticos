"""An outbox for what a purged tenant leaves outside the database (#1269).

`OrganizationService.purge` commits an organization's relational teardown and
hands the external side effects - unlinking stored uploads, dropping vector
tables - to a Prefect flow. #1274 made the *run* durable, so a worker that dies
mid-cleanup no longer loses it.

The window that leaves is between the commit and the dispatch. A crash there
loses the cleanup with nothing left to reconstruct it: the committed delete has
already removed the document paths and collection names a retry would need to
find. So the intent is committed *with* the delete, and the dispatch becomes an
optimisation rather than the only chance.

The row is the record and its absence is the completion - the flow deletes it
once the work is done, so an empty table means nothing is outstanding, and a
sweep re-dispatches whatever is left.

No backfill: an organization purged before this has no intent, and there is
nothing in the database that names what it left. Those are the orphans #1269
describes, and they need the manual archaeology it warns about.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0064_teardown_intents"
down_revision: str | None = "0063_mcp_connection_is_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teardown_intents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("teardown_intents_pkey")),
    )
    op.create_index(
        "ix_teardown_intents_sweep",
        "teardown_intents",
        ["dispatched_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_teardown_intents_sweep", table_name="teardown_intents")
    op.drop_table("teardown_intents")
