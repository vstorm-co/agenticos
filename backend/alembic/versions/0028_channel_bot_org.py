"""channel_bots: add organization_id (NOT NULL)

Revision ID: 0028_channel_bot_org
Revises: 0027_enforce_org_scope
Create Date: 2026-07-26

Channel bots were app-admin resources with no tenant. That made every
conversation they opened org-less, which in turn blocked
``conversations.organization_id`` from becoming NOT NULL (see 0027).

Backfill assigns existing bots to the only organization in the database. With
more than one organization there is no defensible automatic answer — which
tenant owns a given Slack workspace is a business fact, not something a
migration may guess — so the migration stops and asks for a manual assignment
rather than silently handing one tenant's bot to another.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0028_channel_bot_org"
down_revision = "0027_enforce_org_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "channel_bots",
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=True),
    )

    bot_count = conn.execute(sa.text("SELECT count(*) FROM channel_bots")).scalar_one()
    if bot_count:
        org_ids = conn.execute(sa.text("SELECT id FROM organizations LIMIT 2")).scalars().all()
        if len(org_ids) != 1:
            raise RuntimeError(
                f"{bot_count} channel bot(s) cannot be assigned automatically: the database "
                f"holds {len(org_ids)} organizations. Set channel_bots.organization_id by hand, "
                "then re-run this migration."
            )
        conn.execute(
            sa.text("UPDATE channel_bots SET organization_id = :org_id"),
            {"org_id": org_ids[0]},
        )

    op.alter_column("channel_bots", "organization_id", nullable=False)
    op.create_foreign_key(
        "channel_bots_organization_id_fkey",
        "channel_bots",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_channel_bots_organization_id", "channel_bots", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_bots_organization_id", table_name="channel_bots")
    op.drop_constraint("channel_bots_organization_id_fkey", "channel_bots", type_="foreignkey")
    op.drop_column("channel_bots", "organization_id")
