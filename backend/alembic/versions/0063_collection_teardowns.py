"""Reserve a collection name while its vector table is torn down (#1362).

The teardown arc drops a collection's `rag_<name>` table only after the request that
removed its knowledge-base rows commits, so the name is free of any row while its
table still lingers, populated. A concurrent claim of the same name would adopt that
table through `CREATE TABLE IF NOT EXISTS` and read another tenant's chunks. A row
here, committed in the same transaction as the delete, reserves the name until the
durable cleanup drops the table and releases it - `CollectionAccessService.claim`
refuses a name that carries one.

The name is deployment-global (the vector namespace has no tenant dimension), so the
name is the primary key and a repeated teardown of one name is idempotent.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0063_collection_teardowns"
down_revision: str | None = "0062_org_chat_approval_waiver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_teardowns",
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("collection_name", name="collection_teardowns_pkey"),
    )


def downgrade() -> None:
    op.drop_table("collection_teardowns")
