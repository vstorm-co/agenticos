"""Schemas for mapping a Discord bot's server roles to an organization's groups (#2569)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.organization import InvitableRole

Snowflake = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
"""A Discord id: a decimal string of up to twenty digits."""


class DiscordRoleMappingCreate(BaseSchema):
    """Map a role in one of the bot's servers to a group, and optionally a role, here."""

    guild_id: Snowflake = Field(description="The server the role belongs to.")
    discord_role_id: Snowflake = Field(description="The role, by its Discord id.")
    group_id: UUID = Field(description="The group of this organization a holder is placed in.")
    role: InvitableRole | None = Field(
        default=None,
        description=(
            "The organization role a linked holder who is not yet a member is admitted "
            "with. Never owner. Null places existing members in the group and admits nobody."
        ),
    )


class DiscordRoleMappingRead(BaseSchema):
    id: UUID
    channel_bot_id: UUID
    guild_id: str
    guild_name: str
    discord_role_id: str
    discord_role_name: str
    group_id: UUID
    group_name: str | None = None
    role: str | None = None
    created_at: datetime


class DiscordRoleMappingList(BaseSchema):
    items: list[DiscordRoleMappingRead]
    total: int


class DiscordServerRoleRead(BaseSchema):
    id: str
    name: str


class DiscordServerRead(BaseSchema):
    """A server the bot is in, with the roles a mapping may name - not `@everyone`, not a bot's."""

    id: str
    name: str
    roles: list[DiscordServerRoleRead]


class DiscordServerList(BaseSchema):
    items: list[DiscordServerRead]
    total: int
