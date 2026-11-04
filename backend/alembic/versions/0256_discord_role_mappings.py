"""Discord server roles mapped to organization groups (#2569).

- `discord_role_mappings`: one role in one Discord bot's server, mapped to a
  group of the bot's organization and optionally to an organization role.
- `source` on `organization_members` and `group_members` may now be `discord`:
  a row the Discord sync placed, and the only rows it rewrites or removes.

The downgrade hands every `discord` row to an administrator (`manual`) rather
than deleting it: the people the sync placed keep their access, and the
constraint can be restored over them.

Revision ID: 0256_discord_role_mappings
Revises: 0255_run_chat_notice_sent_at
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0256_discord_role_mappings"
down_revision: str | Sequence[str] | None = "0255_run_chat_notice_sent_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORG_CHECK = "organization_members_ck_org_member_source_check"
_GROUP_CHECK = "group_members_ck_group_member_source_check"


def _sources(values: str) -> None:
    op.drop_constraint(op.f(_ORG_CHECK), "organization_members", type_="check")
    op.create_check_constraint(op.f(_ORG_CHECK), "organization_members", f"source IN ({values})")
    op.drop_constraint(op.f(_GROUP_CHECK), "group_members", type_="check")
    op.create_check_constraint(op.f(_GROUP_CHECK), "group_members", f"source IN ({values})")


def upgrade() -> None:
    op.create_unique_constraint("uq_channel_bot_id_org", "channel_bots", ["id", "organization_id"])
    op.create_unique_constraint("uq_group_id_org", "groups", ["id", "organization_id"])
    op.create_table(
        "discord_role_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("channel_bot_id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.String(length=20), nullable=False),
        sa.Column("discord_role_id", sa.String(length=20), nullable=False),
        sa.Column("guild_name", sa.String(length=100), nullable=False),
        sa.Column("discord_role_name", sa.String(length=100), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["channel_bot_id", "organization_id"],
            ["channel_bots.id", "channel_bots.organization_id"],
            name=op.f("discord_role_mappings_channel_bot_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("discord_role_mappings_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "organization_id"],
            ["groups.id", "groups.organization_id"],
            name=op.f("discord_role_mappings_group_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("discord_role_mappings_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("discord_role_mappings_pkey")),
        sa.UniqueConstraint(
            "channel_bot_id", "guild_id", "discord_role_id", name="uq_discord_role_mapping"
        ),
    )
    op.create_index(
        op.f("discord_role_mappings_organization_id_idx"),
        "discord_role_mappings",
        ["organization_id"],
    )
    op.create_index(
        op.f("discord_role_mappings_channel_bot_id_idx"),
        "discord_role_mappings",
        ["channel_bot_id"],
    )
    op.create_index(
        op.f("discord_role_mappings_group_id_idx"), "discord_role_mappings", ["group_id"]
    )
    _sources("'manual', 'directory', 'discord'")


def downgrade() -> None:
    op.execute("UPDATE organization_members SET source = 'manual' WHERE source = 'discord'")
    op.execute("UPDATE group_members SET source = 'manual' WHERE source = 'discord'")
    _sources("'manual', 'directory'")
    op.drop_table("discord_role_mappings")
    op.drop_constraint("uq_group_id_org", "groups", type_="unique")
    op.drop_constraint("uq_channel_bot_id_org", "channel_bots", type_="unique")
