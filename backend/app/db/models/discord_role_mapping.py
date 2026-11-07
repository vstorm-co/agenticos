"""DiscordRoleMapping - what a role in a Discord bot's server means inside its organization.

An organization that runs its team on Discord already says who is in Finance
by giving them `@Finance`. A mapping lets it take that answer instead of keeping
a second copy by hand: a member who linked their Discord account (`/link`) and
holds the role joins `group_id`, and - when `role` is named - becomes a member
of the organization with that role (#2569). It is the Discord counterpart of a
`DirectoryGroupMapping`, kept apart from it on purpose: a directory mapping
matches whatever an identity provider reports at sign-in, so a group claim that
happened to read `discord:<server>:<role>` would match one stored there.

A mapping belongs to one bot, because the bot's token is the only thing that
can read who holds the role, and a role id only means something in the server
it came from. A role in another bot's server does not match, even in the same
organization.
"""

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DiscordRoleMapping(Base, TimestampMixin):
    """One Discord server role, mapped to a group and optionally a role in one organization."""

    __tablename__ = "discord_role_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    # Discord snowflakes: decimal strings of up to twenty digits.
    guild_id: Mapped[str] = mapped_column(String(20), nullable=False)
    discord_role_id: Mapped[str] = mapped_column(String(20), nullable=False)
    # What Discord called them when the mapping was made, for the list and the
    # audit trail. The ids are what match; a renamed role still matches.
    guild_name: Mapped[str] = mapped_column(String(100), nullable=False)
    discord_role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    # The organization role a holder is admitted with. `None` places existing
    # members in the group and admits nobody.
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["channel_bot_id", "organization_id"],
            ["channel_bots.id", "channel_bots.organization_id"],
            name="discord_role_mappings_channel_bot_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["group_id", "organization_id"],
            ["groups.id", "groups.organization_id"],
            name="discord_role_mappings_group_id_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "channel_bot_id", "guild_id", "discord_role_id", name="uq_discord_role_mapping"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DiscordRoleMapping(bot={self.channel_bot_id}, guild={self.guild_id}, "
            f"role={self.discord_role_id}, group={self.group_id})>"
        )
