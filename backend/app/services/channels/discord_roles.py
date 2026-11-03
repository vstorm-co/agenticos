"""Reconciling a linked Discord member's memberships with the roles they hold (#2569).

An organization's Discord role mappings are read against the roles each of its
bots reports for the person's linked Discord accounts, and the person's
*Discord-managed* memberships are made to match: admitted with the mapped role
where a mapping names one, put in the mapped groups, and taken out again where
no mapping matches any more. The directory sync's rules hold here unchanged:

- **Only a linked account counts.** An unlinked Discord user is nobody on the
  deployment, so no role of theirs can make them a member.
- **The sync touches only rows it made** (`source = discord`). A membership an
  administrator made or took over keeps its role, and a group membership added
  by hand stays when the role is taken away. Directory rows are the directory
  sync's.
- **An owner is never demoted or removed by it**, and no mapping can name
  `owner`.
- **A personal organization is never joined** - `list_for_org` excludes them.
- **Not knowing is not losing.** When Discord cannot be asked - a revoked
  token, an outage - nothing changes. Only Discord's own answer that the account
  is not in the server, or the bot no longer is, takes the roles away.

It runs at two moments: before each turn the person takes with a bot of the
organization, in that turn's transaction, so somebody given `@Finance` a moment
ago is answered as Finance; and from the periodic `sync-discord-roles` sweep,
which looks again at everybody it placed, because whoever left the server stops
talking to the bot and their next turn never comes. Discord can push a member's
role changes as they happen, but only to a bot holding the privileged Server
Members Intent, which a bot here does not request.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.permissions import OrgRoleName
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.db.models.organization import MembershipSource
from app.repositories import (
    channel_bot_repo,
    channel_identity_repo,
    discord_role_mapping_repo,
    group_repo,
    member_repo,
    user_repo,
)
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, register_adapter
from app.services.channels.discord_protocol import payload_roles
from app.services.directory import winning_role
from app.services.member import end_membership
from app.services.proactive import ProactiveService

if TYPE_CHECKING:
    from app.services.channels.discord import DiscordAdapter

logger = logging.getLogger(__name__)

PLATFORM = "discord"

Seen = dict[tuple[UUID, str, str], frozenset[str]]
"""Roles already in hand, by `(bot id, server id, Discord user id)`: a guild message carries its sender's."""


def discord_adapter() -> DiscordAdapter:
    """The registered adapter, or one registered now - the sweep, in a worker.

    The API registers it at startup; the job worker never does, and the sweep
    still has to read roles over REST. One registered here opens no Gateway
    connection: that is `start_polling`, which only the API calls.
    """
    # Imported here: the adapter module reaches the router through the worker's
    # channel handoff, and the router imports this module.
    from app.services.channels.discord import DiscordAdapter

    try:
        adapter = get_adapter(PLATFORM)
    except KeyError:
        adapter = DiscordAdapter()
        register_adapter(adapter)
    if not isinstance(adapter, DiscordAdapter):  # pragma: no cover - registered by platform
        raise TypeError("The adapter registered for Discord is not the Discord adapter")
    return adapter


class DiscordRoleSync:
    """Applies an organization's Discord role mappings to one person."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync(self, organization_id: UUID, user_id: UUID, *, seen: Seen | None = None) -> bool:
        """Make the person's Discord-managed memberships in one organization match their roles.

        Args:
            organization_id: The organization whose mappings apply.
            user_id: The person, by their account here.
            seen: Roles a turn's own payload already reported, read instead of
                asking Discord again.

        Returns:
            Whether the memberships were reconciled; `False` when Discord could
            not be asked and nothing was changed.
        """
        mappings = await discord_role_mapping_repo.list_for_org(
            self.db, organization_id=organization_id
        )
        if not mappings and not await discord_role_mapping_repo.synced_people(
            self.db, organization_id=organization_id, user_id=user_id
        ):
            # Every Discord turn passes here: with nothing mapped and nothing
            # placed there is nothing to reconcile, and no row to lock.
            return True
        accounts = [
            identity.platform_user_id
            for identity in await channel_identity_repo.list_for_user(self.db, user_id=user_id)
            if identity.platform == PLATFORM and identity.is_active
        ]
        matched: list[DiscordRoleMapping] = []
        if mappings and accounts:
            held = await self._held(mappings, accounts, seen or {})
            if held is None:
                return False
            matched = [
                mapping
                for mapping in mappings
                if mapping.discord_role_id
                in held.get((mapping.channel_bot_id, mapping.guild_id), frozenset())
            ]
        roles = [mapping.role for mapping in matched if mapping.role is not None]
        if await self._place(user_id, organization_id, winning_role(roles) if roles else None):
            await self._sync_groups(user_id, organization_id, {m.group_id for m in matched})
        return True

    async def on_turn(
        self, bot: ChannelBot, identity: ChannelIdentity, raw: dict[str, Any]
    ) -> None:
        """Bring a linked sender's memberships up to date before their turn is answered.

        A guild message or interaction carries the sender's roles in that
        server, so that one is not asked for again; a direct message carries
        none, and every mapped server is asked.
        """
        if identity.user_id is None:
            return
        seen: Seen = {}
        reported = payload_roles(raw)
        if reported is not None:
            guild_id, roles = reported
            seen[(bot.id, guild_id, identity.platform_user_id)] = roles
        await self.sync(bot.organization_id, identity.user_id, seen=seen)

    async def release(self, user_id: UUID) -> None:
        """Take back everything the Discord sync placed for a person who unlinked their account.

        Reconciled against what they still hold through any other linked Discord
        account, so unlinking a second account takes nothing the first still
        earns.
        """
        placed = await discord_role_mapping_repo.synced_people(self.db, user_id=user_id)
        for organization_id in sorted({organization_id for organization_id, _ in placed}):
            await self.sync(organization_id, user_id)

    async def _held(
        self, mappings: list[DiscordRoleMapping], accounts: list[str], seen: Seen
    ) -> dict[tuple[UUID, str], frozenset[str]] | None:
        """The roles held in each `(bot, server)` the mappings name, across the person's accounts.

        `None` when Discord could not be asked for one of them: a partial answer
        would read the unasked server as every role taken away.
        """
        bots = await channel_bot_repo.get_by_ids(
            self.db, {mapping.channel_bot_id for mapping in mappings}
        )
        adapter = discord_adapter()
        held: dict[tuple[UUID, str], frozenset[str]] = defaultdict(frozenset)
        for bot_id, guild_id in sorted({(m.channel_bot_id, m.guild_id) for m in mappings}):
            bot = bots.get(bot_id)
            if bot is None:
                continue
            for account in accounts:
                roles = seen.get((bot_id, guild_id, account))
                if roles is None:
                    roles = await self._ask(adapter, bot, guild_id, account)
                    if roles is None:
                        return None
                held[(bot_id, guild_id)] |= roles
        return held

    async def _ask(
        self, adapter: DiscordAdapter, bot: ChannelBot, guild_id: str, account: str
    ) -> frozenset[str] | None:
        """One account's roles in one server, empty when it is not there, `None` when unknown."""
        try:
            roles = await adapter.member_roles(unseal_bot_token(bot), guild_id, account)
        except httpx.HTTPError:
            logger.warning(
                "discord_roles_unreadable",
                exc_info=True,
                extra={"bot_id": str(bot.id), "guild_id": guild_id},
            )
            return None
        return roles if roles is not None else frozenset()

    async def _place(self, user_id: UUID, organization_id: UUID, role: str | None) -> bool:
        """Admit, update or remove the Discord-managed membership. Returns whether one is held after.

        With no role to admit by, a membership somebody else made still takes
        the mapped groups; a Discord-managed one ends.
        """
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id, for_update=True
        )
        if membership is None:
            if role is None:
                return False
            user = await user_repo.get_by_id(self.db, user_id)
            # A deactivated account stays linked; it is refused everywhere a
            # person signs in, and a role must not hand it a membership either.
            if user is None or not user.is_active:
                return False
            try:
                async with self.db.begin_nested():
                    await member_repo.create(
                        self.db,
                        organization_id=organization_id,
                        user_id=user_id,
                        role=role,
                        source=MembershipSource.DISCORD,
                    )
            except IntegrityError:
                # A turn and the sweep reconciling the same person: the other
                # got there first, with the membership this one would have made.
                logger.info("discord_member_created_concurrently")
                return True
            await ProactiveService(self.db).queue_welcome(organization_id, user_id)
            await self._audit("discord.member_added", user_id, organization_id, {"role": role})
            return True
        if membership.source != MembershipSource.DISCORD or membership.role == OrgRoleName.OWNER:
            return True
        if role is None:
            previous = membership.role
            await end_membership(self.db, membership)
            await self._audit(
                "discord.member_removed", user_id, organization_id, {"role": previous}
            )
            return False
        if membership.role != role:
            previous = membership.role
            await member_repo.update_role(self.db, membership, role=role)
            await self._audit(
                "discord.role_changed", user_id, organization_id, {"from": previous, "to": role}
            )
        return True

    async def _sync_groups(self, user_id: UUID, organization_id: UUID, wanted: set[UUID]) -> None:
        """Add the Discord group memberships `wanted` names and drop the ones it does not."""
        current = await group_repo.list_memberships_in_org(
            self.db, organization_id=organization_id, user_id=user_id
        )
        held = {member.group_id for member in current}
        for member in current:
            if member.source == MembershipSource.DISCORD and member.group_id not in wanted:
                await group_repo.remove_member(self.db, member)
                await self._audit(
                    "discord.group_left",
                    user_id,
                    organization_id,
                    {"group_id": str(member.group_id)},
                )
        for group_id in sorted(wanted - held):
            try:
                async with self.db.begin_nested():
                    await group_repo.add_member(
                        self.db,
                        group_id=group_id,
                        user_id=user_id,
                        source=MembershipSource.DISCORD,
                        added_by_user_id=None,
                    )
            except IntegrityError:
                logger.info("discord_group_member_created_concurrently")
                continue
            await self._audit(
                "discord.group_joined", user_id, organization_id, {"group_id": str(group_id)}
            )

    async def _audit(
        self, action: str, user_id: UUID, organization_id: UUID, details: dict[str, str]
    ) -> None:
        """Record a change the sync made, attributed to the person it was made for."""
        await record_audit(
            self.db,
            actor_user_id=user_id,
            organization_id=organization_id,
            action=action,
            target_type="member",
            target_id=str(user_id),
            details=details,
        )


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def sweep_discord_roles(sessions: SessionFactory) -> dict[str, int]:
    """Look again at everybody the Discord sync placed, one organization per transaction.

    Returns how many people were reconciled and how many could not be, because
    Discord did not answer for them - those keep what they hold until it does.
    """
    async with sessions() as db:
        placed = await discord_role_mapping_repo.synced_people(db)
    by_organization: dict[UUID, set[UUID]] = defaultdict(set)
    for organization_id, user_id in placed:
        by_organization[organization_id].add(user_id)
    counts = {"synced": 0, "unreadable": 0}
    for organization_id, people in sorted(by_organization.items()):
        async with sessions() as db:
            sync = DiscordRoleSync(db)
            for user_id in sorted(people):
                if await sync.sync(organization_id, user_id):
                    counts["synced"] += 1
                else:
                    counts["unreadable"] += 1
    return counts
