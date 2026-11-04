"""Discord role mappings - an organization deciding what a role in its bot's server means (#2569).

A mapping places people in a group, and when it names a role it admits them,
so it takes the authority doing those things by hand takes: `members:manage`
always, and `roles:manage` with a role the requester's own strictly outranks
(`assignable_roles`) when it names one. It is the same bargain a directory
group mapping strikes, so a mapping is never a way to hand out more than the
person who wrote it could. The routes add `channels:manage`, which every
endpoint about a bot takes.

The server and the role are checked against what the bot itself reads from
Discord when the mapping is made: an id typed by hand that the bot cannot see
would match nobody, and one in a server the bot is not in would match only
once somebody added it there.
"""

import asyncio
import logging
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, assignable_roles
from app.db.models.channel_bot import ChannelBot
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.repositories import (
    channel_bot_repo,
    discord_role_mapping_repo,
    group_repo,
    organization_repo,
)
from app.schemas.discord_role_mapping import DiscordRoleMappingCreate
from app.services import rate_limit
from app.services.channel_bot import unseal_bot_token
from app.services.channels.discord_protocol import Server
from app.services.channels.discord_roles import PLATFORM, discord_adapter

logger = logging.getLogger(__name__)

_SERVER_DISCOVERY_TIMEOUT_SECONDS = 10


class DiscordRoleMappingService:
    """List, create and delete one Discord bot's server role mappings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _bot(self, ctx: AuthContext, bot_id: UUID) -> ChannelBot:
        """One of the organization's Discord bots, for somebody who may manage who is in groups."""
        if not ctx.has(Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="You cannot manage Discord role mappings here")
        bot = await channel_bot_repo.get_for_org(
            self.db, bot_id, organization_id=ctx.organization_id
        )
        if bot is None:
            raise NotFoundError(message="Channel bot not found", details={"bot_id": bot_id})
        if bot.platform != PLATFORM:
            raise BadRequestError(
                message="Only a Discord bot maps server roles", details={"bot_id": bot_id}
            )
        return bot

    @staticmethod
    def _may_assign(ctx: AuthContext, role: str | None, *, removing: bool) -> None:
        """Refuse a mapping that admits with a role the requester could not hand out by hand.

        Removing one takes the same ceiling as making it: it demotes everybody it
        admitted, and an Admin cannot remove the mapping that makes their peers
        Admins, as they could not demote one.
        """
        if role is None:
            return
        if not ctx.has(Perm.ROLES_MANAGE):
            raise AuthorizationError(message="You cannot assign roles in this organization")
        if role not in assignable_roles(ctx.role):
            raise AuthorizationError(
                message=(
                    "You cannot remove a mapping to a role your own does not outrank"
                    if removing
                    else "You cannot map a Discord role to a role your own does not outrank"
                ),
                details={"role": role},
            )

    async def _servers(self, bot: ChannelBot, guild_id: str | None = None) -> list[Server]:
        """Every server the bot is in, or only `guild_id` when one is named (empty if not in it)."""
        token = unseal_bot_token(bot)
        try:
            async with asyncio.timeout(_SERVER_DISCOVERY_TIMEOUT_SECONDS):
                if guild_id is None:
                    servers = await discord_adapter().servers(token)
                else:
                    server = await discord_adapter().server(token, guild_id)
                    servers = [] if server is None else [server]
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning(
                "discord_servers_unreadable", exc_info=True, extra={"bot_id": str(bot.id)}
            )
            raise ExternalServiceError(
                message="Discord did not say which servers and roles the bot can see. Try again.",
                details={"bot_id": bot.id},
            ) from exc
        return servers

    async def servers(self, ctx: AuthContext, bot_id: UUID) -> list[Server]:
        """The servers the bot is in and the roles in each a mapping may name, read live."""
        bot = await self._bot(ctx, bot_id)
        async with rate_limit.one_in_flight(
            "discord-server-discovery",
            str(ctx.organization_id),
            ttl_seconds=15,
            message="Discord servers are already being read for this organization. Try again shortly.",
        ):
            return await self._servers(bot)

    async def list_mappings(
        self, ctx: AuthContext, bot_id: UUID
    ) -> list[tuple[DiscordRoleMapping, str | None]]:
        """Every mapping of the bot, with the name of the group it places people in."""
        bot = await self._bot(ctx, bot_id)
        mappings = await discord_role_mapping_repo.list_for_bot(self.db, channel_bot_id=bot.id)
        names = await group_repo.get_names(
            self.db,
            organization_id=ctx.organization_id,
            group_ids=[mapping.group_id for mapping in mappings],
        )
        return [(mapping, names.get(mapping.group_id)) for mapping in mappings]

    async def create(
        self, ctx: AuthContext, bot_id: UUID, data: DiscordRoleMappingCreate
    ) -> tuple[DiscordRoleMapping, str]:
        """Map a role in one of the bot's servers to a group, and optionally a role, here.

        The people already holding it are placed at their next turn with any of
        the organization's bots: without the privileged Server Members Intent a
        bot cannot list who holds a role.

        Raises:
            AuthorizationError: The requester lacks `members:manage`, or names a
                role without `roles:manage` or one their own does not outrank.
            BadRequestError: The organization is personal, the group is not one
                of its own, or the bot cannot see that server or role.
            ExternalServiceError: Discord could not be asked.
            AlreadyExistsError: The role is already mapped for this bot.
            ConcurrentChangeError: The bot was given a new token while Discord
                was being asked; the server and role were checked with the old one.
            NotFoundError: The bot or the group was deleted while this ran.
        """
        bot = await self._bot(ctx, bot_id)
        self._may_assign(ctx, data.role, removing=False)
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is not None and organization.is_personal:
            raise BadRequestError(message="A personal organization cannot take Discord members")
        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=data.group_id
        )
        if group is None:
            raise refused_field("group_id", "That group is not one of this organization's")
        if await discord_role_mapping_repo.get_by_role(
            self.db,
            channel_bot_id=bot.id,
            guild_id=data.guild_id,
            discord_role_id=data.discord_role_id,
        ):
            raise AlreadyExistsError(
                message="That Discord role is already mapped for this bot",
                details={"guild_id": data.guild_id, "discord_role_id": data.discord_role_id},
            )
        checked_with = bot.token_encrypted
        server = next(iter(await self._servers(bot, data.guild_id)), None)
        if server is None:
            raise refused_field("guild_id", "The bot is not in that Discord server")
        discord_role = next((r for r in server.roles if r.id == data.discord_role_id), None)
        if discord_role is None:
            raise refused_field(
                "discord_role_id",
                "That is not a role of the server a mapping can name - not @everyone, "
                "and not one Discord manages for a bot",
            )
        # Locked until this commits, and re-read: a new token takes what deleting
        # the mappings takes, and its check counts them under this same lock, so
        # it either sees this mapping or is seen here having changed the token
        # the server and role were just checked with.
        locked = await channel_bot_repo.get_for_org(
            self.db, bot_id, organization_id=ctx.organization_id, for_update=True
        )
        if locked is None:
            raise NotFoundError(message="Channel bot not found", details={"bot_id": bot_id})
        if locked.token_encrypted != checked_with:
            raise ConcurrentChangeError(
                message="The bot was given a new token while the mapping was being made. "
                "Try again.",
                details={"bot_id": bot_id},
            )
        try:
            async with self.db.begin_nested():
                mapping = await discord_role_mapping_repo.create(
                    self.db,
                    organization_id=ctx.organization_id,
                    channel_bot_id=bot.id,
                    guild_id=server.id,
                    discord_role_id=discord_role.id,
                    guild_name=server.name[:100],
                    discord_role_name=discord_role.name[:100],
                    group_id=group.id,
                    role=data.role,
                    created_by_user_id=ctx.user_id,
                )
        except IntegrityError as exc:
            # The insert also fails when the group was deleted while it waited on
            # the lock that delete holds; that is not a duplicate. The bot is
            # locked above, so it cannot have gone.
            if (
                await group_repo.get(
                    self.db, organization_id=ctx.organization_id, group_id=data.group_id
                )
                is None
            ):
                raise NotFoundError(
                    message="The group was deleted while the mapping was being made",
                    details={"group_id": data.group_id},
                ) from exc
            raise AlreadyExistsError(
                message="That Discord role is already mapped for this bot",
                details={"guild_id": data.guild_id, "discord_role_id": data.discord_role_id},
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="discord.mapping_created",
            target_type="discord_role_mapping",
            target_id=str(mapping.id),
            details={
                "bot_id": str(bot.id),
                "guild_id": mapping.guild_id,
                "discord_role_id": mapping.discord_role_id,
                "group_id": str(mapping.group_id),
                "role": mapping.role,
            },
        )
        return mapping, group.name

    async def delete(self, ctx: AuthContext, bot_id: UUID, mapping_id: UUID) -> None:
        """Delete a mapping.

        The people it placed keep what it gave them until the next
        `sync-discord-roles` sweep or their next turn, which removes what no
        other mapping still earns them.
        """
        bot = await self._bot(ctx, bot_id)
        mapping = await discord_role_mapping_repo.get(
            self.db, channel_bot_id=bot.id, mapping_id=mapping_id
        )
        if mapping is None:
            raise NotFoundError(
                message="Discord role mapping not found", details={"mapping_id": mapping_id}
            )
        self._may_assign(ctx, mapping.role, removing=True)
        details = {
            "bot_id": str(bot.id),
            "guild_id": mapping.guild_id,
            "discord_role_id": mapping.discord_role_id,
        }
        await discord_role_mapping_repo.delete_mapping(self.db, mapping)
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="discord.mapping_deleted",
            target_type="discord_role_mapping",
            target_id=str(mapping_id),
            details=details,
        )
