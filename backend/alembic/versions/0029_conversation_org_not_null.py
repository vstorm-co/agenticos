"""conversations.organization_id: CHECK -> NOT NULL

Revision ID: 0029_conv_org_not_null
Revises: 0028_channel_bot_org
Create Date: 2026-07-26

0027 could only assert "a user-owned conversation has an org", because channel
conversations had no tenant to inherit. 0028 gave channel bots an organization
and the router now stamps it, so every writer of ``conversations`` supplies one
and the column can carry the invariant itself.

Rows left over from before 0028 (channel conversations opened while bots were
org-less) are backfilled from their bot via channel_sessions. Anything still
NULL afterwards stops the migration rather than being quietly deleted — an
orphan conversation is a fact about the data that an operator should see.

The foreign key moves from ON DELETE SET NULL to CASCADE: with a NOT NULL
column, blanking the org on delete would violate the very constraint this
migration adds. Deleting an organization now deletes its conversations, which
is also what tenant deletion should mean.
"""

import sqlalchemy as sa

from alembic import op

revision = "0029_conv_org_not_null"
down_revision = "0028_channel_bot_org"
branch_labels = None
depends_on = None

CONVERSATION_ORG_CHECK = "ck_conversations_user_rows_have_org"
CONVERSATION_ORG_FK = "conversations_organization_id_fkey"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("""
        UPDATE conversations c
        SET organization_id = b.organization_id
        FROM channel_sessions s
        JOIN channel_bots b ON b.id = s.bot_id
        WHERE s.conversation_id = c.id
          AND c.organization_id IS NULL
    """)
    )

    orphans = conn.execute(
        sa.text("SELECT count(*) FROM conversations WHERE organization_id IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"{orphans} conversation(s) have no organization and no channel session to inherit "
            "one from. Assign conversations.organization_id by hand (or delete the rows), then "
            "re-run this migration."
        )

    op.drop_constraint(CONVERSATION_ORG_CHECK, "conversations", type_="check")
    op.alter_column("conversations", "organization_id", nullable=False)

    op.drop_constraint(CONVERSATION_ORG_FK, "conversations", type_="foreignkey")
    op.create_foreign_key(
        CONVERSATION_ORG_FK,
        "conversations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(CONVERSATION_ORG_FK, "conversations", type_="foreignkey")
    op.create_foreign_key(
        CONVERSATION_ORG_FK,
        "conversations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("conversations", "organization_id", nullable=True)
    op.create_check_constraint(
        CONVERSATION_ORG_CHECK,
        "conversations",
        "user_id IS NULL OR organization_id IS NOT NULL",
    )
