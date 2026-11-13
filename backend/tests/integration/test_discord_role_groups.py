"""Discord server roles mapped to groups, against a real database (#2569).

What only Postgres can say: that the new `discord` source is a value both
membership tables accept, and that the sync - run over real rows - admits,
re-roles, groups and removes exactly the memberships it owns, and nothing an
administrator or the directory made. Discord itself is a stand-in answering
`member_roles`: the requests it receives are the adapter's tests'.
"""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.db.models.group import Group, GroupMember
from app.db.models.oauth import OAuthClient, OAuthGrant
from app.db.models.organization import MembershipSource, Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import discord_role_mapping_repo, member_repo
from app.schemas.channel_bot import ChannelBotUpdate
from app.schemas.discord_role_mapping import DiscordRoleMappingCreate
from app.services.channel_bot import ChannelBotService
from app.services.channel_link import ChannelLinkService
from app.services.channels import discord_roles
from app.services.channels.base import IncomingMessage
from app.services.channels.discord_protocol import Server, ServerRole
from app.services.channels.discord_roles import (
    DiscordMembershipGrant,
    DiscordRoleSync,
    sweep_discord_roles,
)
from app.services.channels.router import ChannelMessageRouter
from app.services.directory import DirectorySyncService
from app.services.discord_role_mapping import DiscordRoleMappingService
from app.services.group import GroupService

pytestmark = pytest.mark.anyio

GUILD = "1100"
OTHER_GUILD = "2200"
FINANCE = "7"
SUPPORT = "8"


class _Discord:
    """Who holds which role, per `(server, account)`, as the bot would read it."""

    def __init__(self) -> None:
        self.roles: dict[tuple[str, str], frozenset[str] | None] = {}
        self.down = False
        self.asked: list[tuple[str, str]] = []
        self.servers = AsyncMock(
            return_value=[
                Server(
                    id=GUILD,
                    name="Acme HQ",
                    roles=(
                        ServerRole(id=FINANCE, name="Finance"),
                        ServerRole(id=SUPPORT, name="Support"),
                    ),
                )
            ]
        )

    async def server(self, _token: str, guild_id: str) -> Server | None:
        return next((s for s in await self.servers() if s.id == guild_id), None)

    def give(self, account: str, *roles: str, guild: str = GUILD) -> None:
        self.roles[(guild, account)] = frozenset(roles)

    async def member_roles(self, _token: str, guild_id: str, account: str) -> frozenset[str] | None:
        self.asked.append((guild_id, account))
        if self.down:
            raise httpx.ConnectError("Discord is down")
        return self.roles.get((guild_id, account))


@pytest.fixture
def discord() -> Iterator[_Discord]:
    fake = _Discord()
    with (
        patch.object(discord_roles, "discord_adapter", return_value=fake),
        patch.object(discord_roles, "unseal_bot_token", return_value="tok"),
        patch("app.services.discord_role_mapping.discord_adapter", return_value=fake),
        patch("app.services.discord_role_mapping.unseal_bot_token", return_value="tok"),
    ):
        yield fake


async def _user(db: AsyncSession, *, active: bool = True) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=None,
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession, *, personal: bool = False) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
        is_personal=personal,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    await db.flush()
    return org, owner


async def _bot(db: AsyncSession, org: Organization, *, platform: str = "discord") -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=org.id,
        platform=platform,
        name="Helper",
        token_encrypted="sealed-elsewhere",
    )
    db.add(bot)
    await db.flush()
    return bot


async def _group(db: AsyncSession, org: Organization, name: str = "Finance") -> Group:
    group = Group(organization_id=org.id, name=name)
    db.add(group)
    await db.flush()
    return group


async def _mapping(
    db: AsyncSession,
    bot: ChannelBot,
    group: Group,
    *,
    discord_role: str = FINANCE,
    guild: str = GUILD,
    role: str | None = None,
) -> DiscordRoleMapping:
    mapping = DiscordRoleMapping(
        organization_id=bot.organization_id,
        channel_bot_id=bot.id,
        guild_id=guild,
        discord_role_id=discord_role,
        guild_name="Acme HQ",
        discord_role_name="Finance",
        group_id=group.id,
        role=role,
    )
    db.add(mapping)
    await db.flush()
    return mapping


async def _linked(
    db: AsyncSession, user: User | None, *, platform: str = "discord"
) -> ChannelIdentity:
    identity = ChannelIdentity(
        id=uuid.uuid4(),
        platform=platform,
        platform_user_id=str(uuid.uuid4().int)[:18],
        user_id=user.id if user else None,
    )
    db.add(identity)
    await db.flush()
    return identity


async def _member(
    db: AsyncSession, org: Organization, *, role: str = "member", source: str = "manual"
) -> User:
    user = await _user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, source=source))
    await db.flush()
    return user


async def _groups(db: AsyncSession, user: User) -> dict[uuid.UUID, str]:
    rows = (await db.execute(select(GroupMember).where(GroupMember.user_id == user.id))).scalars()
    return {row.group_id: row.source for row in rows}


async def _membership(db: AsyncSession, org: Organization, user: User) -> OrganizationMember | None:
    return await member_repo.get(db, organization_id=org.id, user_id=user.id)


def _turn(identity: ChannelIdentity, *roles: str, guild: str = GUILD) -> dict[str, object]:
    return {
        "guild_id": guild,
        "author": {"id": identity.platform_user_id},
        "member": {"roles": list(roles)},
    }


class TestTheSync:
    async def test_a_linked_member_holding_the_role_joins_the_group_and_leaves_it_with_the_role(
        self, db, discord
    ):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance)
        alice = await _member(db, org)
        account = await _linked(db, alice)
        sync = DiscordRoleSync(db)

        await sync.on_turn(bot, account, _turn(account, FINANCE))
        assert await _groups(db, alice) == {finance.id: "discord"}
        assert discord.asked == []  # the turn's own payload answered

        await sync.on_turn(bot, account, _turn(account))
        assert await _groups(db, alice) == {}
        # A member somebody invited stays one: the role only ever gave the group.
        assert (await _membership(db, org, alice)).source == "manual"
        actions = (
            await db.execute(
                select(AppAdminAuditLog.action).where(AppAdminAuditLog.organization_id == org.id)
            )
        ).scalars()
        assert set(actions) == {"discord.group_joined", "discord.group_left"}

    async def test_a_group_membership_added_by_hand_is_not_removed_by_the_sync(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance)
        alice = await _member(db, org)
        db.add(GroupMember(group_id=finance.id, user_id=alice.id, source="manual"))
        await db.flush()
        account = await _linked(db, alice)

        await DiscordRoleSync(db).on_turn(bot, account, _turn(account))

        assert await _groups(db, alice) == {finance.id: "manual"}

    async def test_an_unlinked_discord_user_is_given_nothing(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        stranger = await _linked(db, None)

        await DiscordRoleSync(db).on_turn(bot, stranger, _turn(stranger, FINANCE))

        members = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
            )
        ).scalars()
        assert [member.role for member in members] == ["owner"]
        assert (await db.execute(select(GroupMember))).scalars().all() == []

    async def test_the_same_role_id_in_another_bots_server_does_not_match(self, db, discord):
        """The payload names bot B's server; the mapping is bot A's, and A reads none there."""
        org, _ = await _org(db)
        ours = await _bot(db, org)
        theirs = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, ours, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        discord.give(account.platform_user_id, FINANCE, guild=OTHER_GUILD)

        await DiscordRoleSync(db).on_turn(
            theirs, account, _turn(account, FINANCE, guild=OTHER_GUILD)
        )

        assert discord.asked == [(GUILD, account.platform_user_id)]
        assert await _membership(db, org, bob) is None
        assert await _groups(db, bob) == {}

    async def test_a_mapping_with_a_role_admits_a_linked_holder_and_removes_them_with_it(
        self, db, discord
    ):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        sync = DiscordRoleSync(db)

        # A direct message carries no roles, so the server is asked.
        discord.give(account.platform_user_id, FINANCE)
        await sync.on_turn(bot, account, {"author": {"id": account.platform_user_id}})

        membership = await _membership(db, org, bob)
        assert (membership.role, membership.source) == ("member", "discord")
        assert await _groups(db, bob) == {finance.id: "discord"}
        welcome = (await db.execute(select(BackgroundJob.kind))).scalars().all()
        assert "welcome-member" in welcome

        discord.roles.pop((GUILD, account.platform_user_id))  # left the server
        await sync.on_turn(bot, account, {"author": {"id": account.platform_user_id}})

        assert await _membership(db, org, bob) is None
        assert await _groups(db, bob) == {}

    async def test_the_highest_mapped_role_wins_and_follows_the_roles(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        support = await _group(db, org, "Support")
        await _mapping(db, bot, finance, role="viewer")
        await _mapping(db, bot, support, discord_role=SUPPORT, role="builder")
        bob = await _user(db)
        account = await _linked(db, bob)
        sync = DiscordRoleSync(db)

        await sync.on_turn(bot, account, _turn(account, FINANCE, SUPPORT))
        assert (await _membership(db, org, bob)).role == "builder"
        assert set(await _groups(db, bob)) == {finance.id, support.id}

        await sync.on_turn(bot, account, _turn(account, FINANCE))
        assert (await _membership(db, org, bob)).role == "viewer"
        assert set(await _groups(db, bob)) == {finance.id}

    @pytest.mark.parametrize(
        "previous,unread,expected", [("admin", "viewer", "viewer"), ("viewer", "admin", "viewer")]
    )
    async def test_an_unread_mapping_bounds_retained_authority(
        self, db, discord, previous, unread, expected
    ):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        await _mapping(db, bot, await _group(db, org), role="admin")
        await _mapping(db, bot, await _group(db, org, "Support"), guild=OTHER_GUILD, role=unread)
        user = await _member(db, org, role=previous, source="discord")
        account = await _linked(db, user)
        before = await _membership(db, org, user)
        membership_id = before.id
        discord.down = True
        assert not await DiscordRoleSync(db).sync(
            org.id,
            user.id,
            seen={(bot.id, GUILD, account.platform_user_id): frozenset()},
        )
        after = await _membership(db, org, user)
        assert (after.id, after.source, after.role) == (membership_id, "discord", expected)

    async def test_a_membership_an_administrator_made_keeps_its_role(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="viewer")
        carol = await _member(db, org, role="admin")
        account = await _linked(db, carol)

        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        membership = await _membership(db, org, carol)
        assert (membership.role, membership.source) == ("admin", "manual")
        assert await _groups(db, carol) == {finance.id: "discord"}

    async def test_an_owner_is_never_removed_by_it(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        ownership = await _membership(db, org, owner)
        await member_repo.update_role(db, ownership, role="owner")
        ownership.source = "discord"
        await db.flush()
        account = await _linked(db, owner)

        await DiscordRoleSync(db).on_turn(bot, account, _turn(account))

        assert (await _membership(db, org, owner)).role == "owner"

    async def test_a_deactivated_account_is_not_admitted(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        await _mapping(db, bot, await _group(db, org), role="member")
        gone = await _user(db, active=False)
        account = await _linked(db, gone)

        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        assert await _membership(db, org, gone) is None

    async def test_discord_not_answering_changes_nothing(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        discord.give(account.platform_user_id, FINANCE)
        sync = DiscordRoleSync(db)
        assert await sync.sync(org.id, bob.id)

        discord.down = True
        assert not await sync.sync(org.id, bob.id)

        assert (await _membership(db, org, bob)).source == "discord"
        assert await _groups(db, bob) == {finance.id: "discord"}

    async def test_one_server_not_answering_does_not_hold_up_the_others(self, db, discord):
        org, _ = await _org(db)
        broken, working = await _bot(db, org), await _bot(db, org)
        finance, support = await _group(db, org), await _group(db, org, "Support")
        await _mapping(db, broken, finance, role="member")
        await _mapping(db, working, support, discord_role=SUPPORT, guild=OTHER_GUILD)
        bob = await _user(db)
        account = await _linked(db, bob)
        discord.give(account.platform_user_id, FINANCE)
        discord.give(account.platform_user_id, SUPPORT, guild=OTHER_GUILD)
        sync = DiscordRoleSync(db)
        assert await sync.sync(org.id, bob.id)
        assert await _groups(db, bob) == {finance.id: "discord", support.id: "discord"}

        # The first bot's server stops answering; the second says Support is gone.
        answer = discord.member_roles

        async def member_roles(token: str, guild: str, who: str) -> frozenset[str] | None:
            if guild == GUILD:
                raise httpx.ConnectError("revoked")
            return await answer(token, guild, who)

        discord.member_roles = member_roles  # type: ignore[method-assign] - one server fails
        discord.give(account.platform_user_id, guild=OTHER_GUILD)

        assert not await sync.sync(org.id, bob.id)
        # What the server that answered took away is gone; what the unread one
        # gave - the group and the membership it admitted - is kept.
        assert await _groups(db, bob) == {finance.id: "discord"}
        assert (await _membership(db, org, bob)).role == "member"

    async def test_a_group_membership_taken_over_since_it_was_read_is_left(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance)
        alice = await _member(db, org)
        account = await _linked(db, alice)
        sync = DiscordRoleSync(db)
        await sync.on_turn(bot, account, _turn(account, FINANCE))
        row = (
            await db.execute(select(GroupMember).where(GroupMember.user_id == alice.id))
        ).scalar_one()
        # An administrator takes the membership over after the sync has read it
        # as its own: the session still holds the row with its old source.
        await db.execute(
            update(GroupMember)
            .where(GroupMember.id == row.id)
            .values(source="manual")
            .execution_options(synchronize_session=False)
        )
        assert row.source == "discord"

        await sync.on_turn(bot, account, _turn(account))

        await db.refresh(row)
        assert row.source == "manual"
        actions = (
            await db.execute(
                select(AppAdminAuditLog.action).where(AppAdminAuditLog.organization_id == org.id)
            )
        ).scalars()
        assert "discord.group_left" not in set(actions)

    async def test_a_personal_organization_is_never_joined(self, db, discord):
        org, _ = await _org(db, personal=True)
        bot = await _bot(db, org)
        await _mapping(db, bot, await _group(db, org), role="member")
        bob = await _user(db)
        account = await _linked(db, bob)

        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        assert await _membership(db, org, bob) is None

    async def test_nothing_mapped_and_nothing_placed_asks_nobody(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        alice = await _member(db, org)
        await _linked(db, alice)

        assert await DiscordRoleSync(db).sync(org.id, alice.id)
        await DiscordRoleSync(db).on_turn(bot, await _linked(db, None), {})

        assert discord.asked == []

    async def test_a_deleted_mapping_takes_back_what_it_gave(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        mapping = await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        sync = DiscordRoleSync(db)
        await sync.on_turn(bot, account, _turn(account, FINANCE))

        await discord_role_mapping_repo.delete_mapping(db, mapping)
        await sync.on_turn(bot, account, _turn(account, FINANCE))

        assert await _membership(db, org, bob) is None

    async def test_a_sign_in_leaves_what_the_discord_sync_placed(self, db, discord):
        """The directory drops every directory row its groups no longer name - not Discord's."""
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        db.add(
            DirectoryGroupMapping(organization_id=org.id, external_group="cn=other", role="member")
        )
        await db.flush()
        bob = await _user(db)
        account = await _linked(db, bob)
        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        await DirectorySyncService(db).apply(bob.id, [], provider="oidc")

        assert (await _membership(db, org, bob)).source == "discord"
        assert await _groups(db, bob) == {finance.id: "discord"}

    async def test_a_second_linked_account_still_earns_the_role(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance)
        alice = await _member(db, org)
        first = await _linked(db, alice)
        second = await _linked(db, alice)
        discord.give(second.platform_user_id, FINANCE)

        await DiscordRoleSync(db).on_turn(bot, first, _turn(first))

        assert await _groups(db, alice) == {finance.id: "discord"}


class TestUnlinkingAndTheSweep:
    async def test_unlinking_the_account_takes_back_what_its_roles_gave(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        assert await ChannelLinkService(db).unlink(bob.id, account.id)

        assert await _membership(db, org, bob) is None
        assert discord.asked == []

    async def test_unlinking_in_the_chat_takes_back_what_its_roles_gave(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))
        incoming = IncomingMessage(
            platform="discord",
            bot_id=str(bot.id),
            platform_user_id=account.platform_user_id,
            platform_chat_id="dm-1",
            chat_type="private",
            text="/unlink",
        )

        reply = await ChannelMessageRouter()._handle_command(
            "/unlink", incoming, bot, db, account, False
        )

        assert reply == "Your account has been unlinked."
        assert await _membership(db, org, bob) is None
        assert await _groups(db, bob) == {}

    async def test_linking_the_account_to_somebody_else_releases_the_first(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob, carol = await _user(db), await _user(db)
        account = await _linked(db, bob)
        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))
        url = await ChannelLinkService(db).request(
            IncomingMessage(
                platform="discord",
                bot_id=str(bot.id),
                platform_user_id=account.platform_user_id,
                platform_chat_id="dm-1",
                chat_type="private",
                text="/link",
            )
        )

        assert await ChannelLinkService(db).confirm(url.rsplit("/", 1)[1], carol.id)

        assert await _membership(db, org, bob) is None
        # Carol holds the account now; the role places her at her next turn.
        assert await _membership(db, org, carol) is None

    async def test_unlinking_another_platform_leaves_discord_alone(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _user(db)
        account = await _linked(db, bob)
        slack = await _linked(db, bob, platform="slack")
        await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))

        assert await ChannelLinkService(db).unlink(bob.id, slack.id)

        assert (await _membership(db, org, bob)).source == "discord"

    async def test_the_sweep_reconciles_everybody_it_placed(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        stays, leaves, unknown = await _user(db), await _user(db), await _user(db)
        accounts = {user.id: await _linked(db, user) for user in (stays, leaves, unknown)}
        for user in (stays, leaves, unknown):
            account = accounts[user.id]
            await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))
        discord.give(accounts[stays.id].platform_user_id, FINANCE)
        discord.give(accounts[leaves.id].platform_user_id)
        unreadable = accounts[unknown.id].platform_user_id

        async def member_roles(token: str, guild: str, account: str) -> frozenset[str] | None:
            if account == unreadable:
                raise httpx.ReadTimeout("slow")
            return discord.roles.get((guild, account))

        discord.member_roles = member_roles  # type: ignore[method-assign] - one account times out

        @asynccontextmanager
        async def sessions():
            yield db

        counts = await sweep_discord_roles(sessions)

        assert counts == {"synced": 2, "unreadable": 1, "failed": 0}
        assert (await _membership(db, org, stays)).source == "discord"
        assert await _membership(db, org, leaves) is None
        assert (await _membership(db, org, unknown)).source == "discord"

    async def test_one_person_failing_does_not_stop_the_sweep(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        broken, leaves = await _user(db), await _user(db)
        for user in (broken, leaves):
            account = await _linked(db, user)
            await DiscordRoleSync(db).on_turn(bot, account, _turn(account, FINANCE))
        real_sync = DiscordRoleSync.sync

        async def sync(self: DiscordRoleSync, organization_id, user_id, **kwargs):
            if user_id == broken.id:
                raise RuntimeError("one person's rows are broken")
            return await real_sync(self, organization_id, user_id, **kwargs)

        @asynccontextmanager
        async def sessions():
            yield db

        with patch.object(DiscordRoleSync, "sync", new=sync):
            counts = await sweep_discord_roles(sessions)

        assert counts == {"synced": 1, "unreadable": 0, "failed": 1}
        assert await _membership(db, org, leaves) is None


class TestMappings:
    def _ctx(self, org: Organization, user: User, role: str = "owner") -> AuthContext:
        return AuthContext(user_id=user.id, organization_id=org.id, role=role)

    def _create(self, group: Group, **overrides: object) -> DiscordRoleMappingCreate:
        data: dict[str, object] = {
            "guild_id": GUILD,
            "discord_role_id": FINANCE,
            "group_id": group.id,
        }
        data.update(overrides)
        return DiscordRoleMappingCreate.model_validate(data)

    async def test_an_administrator_maps_a_role_and_lists_it_with_its_names(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        service = DiscordRoleMappingService(db)

        mapping, group_name = await service.create(
            self._ctx(org, owner), bot.id, self._create(finance, role="member")
        )

        assert (mapping.guild_name, mapping.discord_role_name, group_name) == (
            "Acme HQ",
            "Finance",
            "Finance",
        )
        listed = await service.list_mappings(self._ctx(org, owner), bot.id)
        assert [(row.id, name) for row, name in listed] == [(mapping.id, "Finance")]
        assert await service.servers(self._ctx(org, owner), bot.id) == await discord.servers()

    async def test_mapping_the_same_role_twice_is_refused(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        service = DiscordRoleMappingService(db)
        await service.create(self._ctx(org, owner), bot.id, self._create(finance))

        with pytest.raises(AlreadyExistsError):
            await service.create(self._ctx(org, owner), bot.id, self._create(finance))

    async def test_a_concurrent_duplicate_is_refused_by_the_constraint(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        with (
            patch.object(discord_role_mapping_repo, "get_by_role", AsyncMock(return_value=None)),
        ):
            service = DiscordRoleMappingService(db)
            await service.create(self._ctx(org, owner), bot.id, self._create(finance))
            with pytest.raises(AlreadyExistsError):
                await service.create(self._ctx(org, owner), bot.id, self._create(finance))

    @pytest.mark.parametrize("parent", ["group", "bot"])
    async def test_a_mapping_whose_parent_is_deleted_meanwhile_is_not_found(
        self, db, engine, discord, parent
    ):
        """It waits on the delete's lock and then fails its foreign key, which
        is not the duplicate the constraint error otherwise means."""
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def create() -> None:
            async with factory() as session:
                await DiscordRoleMappingService(session).create(
                    self._ctx(org, owner), bot.id, self._create(finance)
                )

        checked, resume = asyncio.Event(), asyncio.Event()
        found = discord.server

        async def after_validation(token: str, guild_id: str) -> Server | None:
            result = await found(token, guild_id)
            checked.set()
            await resume.wait()
            return result

        discord.server = after_validation
        creating = asyncio.create_task(create())
        # The create must have validated both parents before either is deleted.
        # A timed sleep could instead let the delete commit before that read on CI.
        async with asyncio.timeout(15):
            await checked.wait()
        # The bot's connection has nothing behind it to close here.
        with patch("app.services.channel_bot.close_inbound_stream", AsyncMock()):
            async with factory() as deleting:
                if parent == "group":
                    await GroupService(deleting).delete(self._ctx(org, owner), finance.id)
                else:
                    await ChannelBotService(deleting, organization_id=org.id).delete(
                        bot.id, self._ctx(org, owner)
                    )
                resume.set()
                done, _ = await asyncio.wait({creating}, timeout=0.2)
                assert not done
                await deleting.commit()
                async with asyncio.timeout(15):
                    with pytest.raises(NotFoundError):
                        await creating

    async def test_a_token_replaced_while_discord_is_asked_is_refused(self, db, engine, discord):
        """The new token found no mapping to check and the mapping was checked
        with the old token, so neither side may commit as if the other had not."""
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        admin = await _member(db, org, role="admin")
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        asking, answered = asyncio.Event(), asyncio.Event()
        found = discord.server

        async def slow_server(token: str, guild_id: str) -> Server | None:
            asking.set()
            await answered.wait()
            return await found(token, guild_id)

        async def create() -> None:
            async with factory() as session:
                await DiscordRoleMappingService(session).create(
                    self._ctx(org, owner), bot.id, self._create(finance, role="admin")
                )
                await session.commit()

        with (
            patch.object(discord, "server", slow_server),
            patch.object(ChannelBotService, "_seal_at", return_value="sealed-anew"),
            patch.object(ChannelBotService, "_reopen_stream"),
        ):
            creating = asyncio.create_task(create())
            async with asyncio.timeout(15):
                await asking.wait()
                async with factory() as updating:
                    await ChannelBotService(updating, organization_id=org.id).update(
                        bot.id, ChannelBotUpdate(token="t" * 40), self._ctx(org, admin, "admin")
                    )
                    await updating.commit()
                answered.set()
                with pytest.raises(ConcurrentChangeError):
                    await creating

        assert await db.scalar(select(DiscordRoleMapping.id)) is None

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"guild_id": OTHER_GUILD}, "guild_id"),
            ({"discord_role_id": "99"}, "discord_role_id"),
        ],
    )
    async def test_a_server_or_role_the_bot_cannot_see_is_refused(
        self, db, discord, overrides, field
    ):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)

        with pytest.raises(BadRequestError) as refused:
            await DiscordRoleMappingService(db).create(
                self._ctx(org, owner), bot.id, self._create(finance, **overrides)
            )

        assert refused.value.details["fields"][0]["field"] == field

    async def test_a_group_of_another_organization_is_refused(self, db, discord):
        org, owner = await _org(db)
        other, _ = await _org(db)
        bot = await _bot(db, org)

        with pytest.raises(BadRequestError):
            await DiscordRoleMappingService(db).create(
                self._ctx(org, owner), bot.id, self._create(await _group(db, other))
            )

    async def test_a_personal_organization_takes_no_mappings(self, db, discord):
        org, owner = await _org(db, personal=True)
        bot = await _bot(db, org)

        with pytest.raises(BadRequestError):
            await DiscordRoleMappingService(db).create(
                self._ctx(org, owner), bot.id, self._create(await _group(db, org))
            )

    async def test_a_bot_of_another_platform_or_organization_is_refused(self, db, discord):
        org, owner = await _org(db)
        other, _ = await _org(db)
        service = DiscordRoleMappingService(db)

        with pytest.raises(BadRequestError):
            await service.list_mappings(
                self._ctx(org, owner), (await _bot(db, org, platform="slack")).id
            )
        with pytest.raises(NotFoundError):
            await service.list_mappings(self._ctx(org, owner), (await _bot(db, other)).id)

    @pytest.mark.security
    async def test_group_only_mapping_cannot_be_cascaded_without_channel_permission(
        self, db, discord
    ):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        group = await _group(db, org)
        mapping = await _mapping(db, bot, group)
        narrowed = AuthContext(
            user_id=owner.id,
            organization_id=org.id,
            role="owner",
            key_scopes=frozenset({Perm.MEMBERS_MANAGE, Perm.ROLES_MANAGE}),
        )
        with pytest.raises(AuthorizationError):
            await GroupService(db).delete(narrowed, group.id)
        assert await db.get(Group, group.id) is not None
        assert await db.get(DiscordRoleMapping, mapping.id) is not None
        await GroupService(db).delete(self._ctx(org, owner), group.id)
        assert await discord_role_mapping_repo.list_for_bot(db, channel_bot_id=bot.id) == []

    @pytest.mark.parametrize(
        ("requester", "role"),
        [
            ("builder", None),  # cannot manage members
            ("admin", "admin"),  # does not outrank its own level
        ],
    )
    async def test_a_mapping_beyond_the_requesters_own_authority_is_refused(
        self, db, discord, requester, role
    ):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        person = await _member(db, org, role=requester)

        with pytest.raises(AuthorizationError):
            await DiscordRoleMappingService(db).create(
                self._ctx(org, person, requester), bot.id, self._create(finance, role=role)
            )

    async def test_naming_a_role_takes_roles_manage(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        ctx = MagicMock(
            organization_id=org.id,
            user_id=owner.id,
            role="admin",
            has=lambda perm: perm.value != "roles:manage",
        )

        with pytest.raises(AuthorizationError):
            await DiscordRoleMappingService(db).create(
                ctx, bot.id, self._create(await _group(db, org), role="member")
            )

    async def test_discord_not_answering_is_a_503_not_a_refusal(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        discord.servers.side_effect = httpx.ConnectError("down")
        service = DiscordRoleMappingService(db)

        with pytest.raises(ExternalServiceError):
            await service.servers(self._ctx(org, owner), bot.id)
        with pytest.raises(ExternalServiceError):
            await service.create(self._ctx(org, owner), bot.id, self._create(await _group(db, org)))

    async def test_deleting_a_mapping_takes_the_ceiling_making_it_took(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        to_admin = await _mapping(db, bot, finance, role="admin")
        plain = await _mapping(db, bot, finance, discord_role=SUPPORT)
        admin = await _member(db, org, role="admin")
        service = DiscordRoleMappingService(db)

        with pytest.raises(AuthorizationError):
            await service.delete(self._ctx(org, admin, "admin"), bot.id, to_admin.id)
        await service.delete(self._ctx(org, admin, "admin"), bot.id, plain.id)
        await service.delete(self._ctx(org, owner), bot.id, to_admin.id)

        assert await discord_role_mapping_repo.list_for_bot(db, channel_bot_id=bot.id) == []
        with pytest.raises(NotFoundError):
            await service.delete(self._ctx(org, owner), bot.id, plain.id)

    async def test_deleting_the_group_takes_the_ceiling_its_mappings_took(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="admin")
        admin = await _member(db, org, role="admin")
        groups = GroupService(db)

        with pytest.raises(AuthorizationError):
            await groups.delete(self._ctx(org, admin, "admin"), finance.id)
        # An owner's API key scoped below `roles:manage` cannot delete the
        # mapping directly, and so cannot delete the group it cascades with.
        narrowed = AuthContext(
            user_id=owner.id,
            organization_id=org.id,
            role="owner",
            key_scopes=frozenset({Perm.MEMBERS_MANAGE}),
        )
        with pytest.raises(AuthorizationError):
            await groups.delete(narrowed, finance.id)
        await groups.delete(self._ctx(org, owner), finance.id)

        assert await discord_role_mapping_repo.list_for_bot(db, channel_bot_id=bot.id) == []

    @pytest.mark.parametrize(
        ("requester", "role"),
        [
            ("admin", "admin"),  # the mapping admits peers the admin cannot demote
            ("builder", None),  # its placements take members:manage to undo
        ],
    )
    async def test_deleting_the_bot_takes_what_deleting_its_mappings_takes(
        self, db, discord, requester, role
    ):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        await _mapping(db, bot, await _group(db, org), role=role)
        person = await _member(db, org, role=requester)

        with pytest.raises(AuthorizationError):
            await ChannelBotService(db, organization_id=org.id).delete(
                bot.id, self._ctx(org, person, requester)
            )
        with patch("app.services.channel_bot.spawn_after_commit") as deferred:
            await ChannelBotService(db, organization_id=org.id).delete(
                bot.id, self._ctx(org, owner)
            )
        deferred.call_args.args[1].close()

        assert await discord_role_mapping_repo.list_for_bot(db, channel_bot_id=bot.id) == []

    async def test_a_new_token_takes_what_deleting_the_mappings_takes(self, db, discord):
        org, owner = await _org(db)
        bot = await _bot(db, org)
        await _mapping(db, bot, await _group(db, org), role="admin")
        admin = await _member(db, org, role="admin")
        service = ChannelBotService(db, organization_id=org.id)
        new_token = ChannelBotUpdate(token="t" * 40)

        # Another application's token is in none of the mapped servers: the next
        # sync would read everybody the mapping admitted as having left.
        with (
            patch.object(ChannelBotService, "_seal_at", return_value="sealed-anew"),
            patch.object(ChannelBotService, "_reopen_stream"),
        ):
            with pytest.raises(AuthorizationError):
                await service.update(bot.id, new_token, self._ctx(org, admin, "admin"))
            # Renaming it changes nobody's roles.
            renamed = await service.update(
                bot.id, ChannelBotUpdate(name="Renamed"), self._ctx(org, admin, "admin")
            )
            assert renamed.name == "Renamed"
            assert renamed.token_encrypted == "sealed-elsewhere"
            updated = await service.update(bot.id, new_token, self._ctx(org, owner))
        assert updated.token_encrypted == "sealed-anew"

    @pytest.mark.parametrize("parent", ["group", "bot"])
    async def test_a_mapping_made_while_its_parent_is_deleted_is_checked(
        self, db, engine, discord, parent
    ):
        """An owner's mapping committed between the delete's check and its
        cascade would otherwise go with the parent without being checked."""
        org, owner = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        admin = await _member(db, org, role="admin")
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def delete_as_admin() -> None:
            async with factory() as session:
                ctx = self._ctx(org, admin, "admin")
                if parent == "group":
                    await GroupService(session).delete(ctx, finance.id)
                else:
                    await ChannelBotService(session, organization_id=org.id).delete(bot.id, ctx)
                await session.commit()

        async with factory() as owners:
            await _mapping(owners, bot, finance, role="admin")
            deleting = asyncio.create_task(delete_as_admin())
            # Held behind the uncommitted mapping's foreign-key lock on the parent.
            done, _ = await asyncio.wait({deleting}, timeout=0.2)
            assert not done
            await owners.commit()
            async with asyncio.timeout(15):
                with pytest.raises(AuthorizationError):
                    await deleting

        assert await db.scalar(select(DiscordRoleMapping.id)) is not None

    async def test_deleting_the_bot_or_the_group_deletes_its_mappings(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance)
        await _mapping(db, await _bot(db, org), await _group(db, org, "Support"))

        await db.delete(bot)
        await db.delete(finance)
        await db.flush()

        remaining = (await db.execute(select(DiscordRoleMapping))).scalars().all()
        assert len(remaining) == 1


@pytest.mark.security
class TestDirectoryDiscordHandover:
    async def _credentials(
        self, db: AsyncSession, org: Organization, user: User
    ) -> tuple[ApiKey, OAuthGrant]:
        client = OAuthClient(client_id=uuid.uuid4().hex, info={})
        db.add(client)
        await db.flush()
        grant = OAuthGrant(
            client_id=client.client_id,
            user_id=user.id,
            organization_id=org.id,
            scopes=["agents:run"],
        )
        db.add(grant)
        await db.flush()
        key = ApiKey(
            user_id=user.id,
            organization_id=org.id,
            name="Keep me",
            prefix=uuid.uuid4().hex[:16],
            key_hash="a" * 64,
            scopes=["agents:run"],
            oauth_grant_id=grant.id,
        )
        db.add(key)
        await db.flush()
        return key, grant

    async def test_directory_takes_priority_without_revoking_existing_access(self, db, discord):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance, manual = await _group(db, org), await _group(db, org, "Hand added")
        await _mapping(db, bot, finance, role="builder")
        bob = await _user(db)
        account = await _linked(db, bob)
        discord.give(account.platform_user_id, FINANCE)
        await DiscordRoleSync(db).sync(org.id, bob.id)
        membership_id = (await _membership(db, org, bob)).id
        db.add(GroupMember(group_id=manual.id, user_id=bob.id, source="manual"))
        db.add(DirectoryGroupMapping(organization_id=org.id, external_group="staff", role="member"))
        await db.flush()
        key, grant = await self._credentials(db, org, bob)

        await DirectorySyncService(db).apply(bob.id, ["staff"], provider="oidc")
        discord.give(account.platform_user_id)
        await DiscordRoleSync(db).sync(org.id, bob.id)

        membership = await _membership(db, org, bob)
        assert (membership.id, membership.source, membership.role) == (
            membership_id,
            "directory",
            "member",
        )
        await db.refresh(key)
        await db.refresh(grant)
        assert key.revoked_at is None and grant.revoked_at is None
        assert await _groups(db, bob) == {manual.id: "manual"}

    @pytest.mark.parametrize("outcome", ["grant", "none", "unreadable"])
    async def test_directory_departure_checks_discord_before_revoking_credentials(
        self, db, discord, outcome
    ):
        org, _ = await _org(db)
        bot = await _bot(db, org)
        finance = await _group(db, org)
        await _mapping(db, bot, finance, role="member")
        bob = await _member(db, org, role="builder", source="directory")
        account = await _linked(db, bob)
        discord.give(account.platform_user_id, *([FINANCE] if outcome == "grant" else []))
        discord.down = outcome == "unreadable"
        db.add(GroupMember(group_id=finance.id, user_id=bob.id, source="manual"))
        await db.flush()
        key, grant = await self._credentials(db, org, bob)
        membership_id = (await _membership(db, org, bob)).id

        await DirectorySyncService(db).apply(bob.id, [], provider="ldap")

        membership = await _membership(db, org, bob)
        await db.refresh(key)
        await db.refresh(grant)
        if outcome == "none":
            assert membership is None
            assert key.revoked_at is not None and grant.revoked_at is not None
            assert await _groups(db, bob) == {}
        else:
            assert membership.id == membership_id
            assert (membership.source, membership.role) == (("discord", "member"))
            assert key.revoked_at is None and grant.revoked_at is None
            assert await _groups(db, bob) == {finance.id: "manual"}
            if outcome == "unreadable":
                assert (org.id, bob.id) in await discord_role_mapping_repo.synced_people(db)
                discord.down = False
                await DiscordRoleSync(db).sync(org.id, bob.id)
                assert await _membership(db, org, bob) is None
                await db.refresh(key)
                await db.refresh(grant)
                assert key.revoked_at is not None and grant.revoked_at is not None

    @pytest.mark.parametrize(
        "source,role", [("manual", "viewer"), ("discord", "owner"), ("directory", "owner")]
    )
    async def test_directory_never_takes_over_manual_or_owner_memberships(
        self, db, discord, source, role
    ):
        org, _ = await _org(db)
        bob = await _member(db, org, source=source, role=role)
        db.add(DirectoryGroupMapping(organization_id=org.id, external_group="staff", role="member"))
        await db.flush()
        await DirectorySyncService(db).apply(bob.id, ["staff"], provider="oidc")
        membership = await _membership(db, org, bob)
        assert (membership.source, membership.role) == (source, role)


@pytest.mark.security
@pytest.mark.parametrize("takeover", ["manual", "owner"])
async def test_directory_departure_rechecks_a_membership_changed_during_discord_lookup(
    db, engine, discord, takeover
):
    import contextlib

    org, _ = await _org(db)
    bot = await _bot(db, org)
    finance = await _group(db, org)
    await _mapping(db, bot, finance, role="member")
    bob = await _member(db, org, source="directory")
    account = await _linked(db, bob)
    discord.give(account.platform_user_id)
    key, grant = await TestDirectoryDiscordHandover()._credentials(db, org, bob)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    looked_up, proceed = asyncio.Event(), asyncio.Event()
    original = DiscordRoleSync.membership_grant

    async def lookup(
        sync: DiscordRoleSync,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        deadline: float | None = None,
    ) -> DiscordMembershipGrant:
        result = await original(sync, organization_id, user_id, deadline=deadline)
        looked_up.set()
        await proceed.wait()
        return result

    async def sign_in() -> None:
        async with factory() as session:
            await DirectorySyncService(session).apply(bob.id, [], provider="oidc")
            await session.commit()

    with patch.object(DiscordRoleSync, "membership_grant", new=lookup):
        task = asyncio.create_task(sign_in())
        try:
            await asyncio.wait_for(looked_up.wait(), 5)
            async with factory() as administrator:
                member = await member_repo.get(
                    administrator, organization_id=org.id, user_id=bob.id, for_update=True
                )
                assert member is not None
                await member_repo.update_role(
                    administrator,
                    member,
                    role="owner" if takeover == "owner" else "viewer",
                    source=None if takeover == "owner" else MembershipSource.MANUAL,
                )
                await administrator.commit()
            proceed.set()
            await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
    await db.refresh(key)
    await db.refresh(grant)
    assert key.revoked_at is None and grant.revoked_at is None
    member = await _membership(db, org, bob)
    assert member is not None
    assert member.role == ("owner" if takeover == "owner" else "viewer")


@pytest.mark.security
@pytest.mark.parametrize("foreign_parent", ["bot", "group"])
async def test_mapping_constraint_rejects_cross_organization_parents(
    db: AsyncSession, foreign_parent: str
):
    from sqlalchemy.exc import IntegrityError

    org, _ = await _org(db)
    foreign, _ = await _org(db)
    bot, other_bot = await _bot(db, org), await _bot(db, foreign)
    group, other_group = await _group(db, org), await _group(db, foreign)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                DiscordRoleMapping(
                    organization_id=org.id,
                    channel_bot_id=other_bot.id if foreign_parent == "bot" else bot.id,
                    group_id=other_group.id if foreign_parent == "group" else group.id,
                    guild_id=GUILD,
                    discord_role_id=FINANCE,
                    guild_name="Acme",
                    discord_role_name="Finance",
                )
            )
            await db.flush()


@pytest.mark.security
@pytest.mark.parametrize("existing", [True, False])
async def test_confirmed_sender_role_survives_another_linked_accounts_lookup_failure(
    db: AsyncSession, discord, existing: bool
):
    org, _ = await _org(db)
    bot = await _bot(db, org)
    group = await _group(db, org)
    await _mapping(db, bot, group, role="member")
    bob = await _member(db, org) if existing else await _user(db)
    unread, sender = await _linked(db, bob), await _linked(db, bob)

    async def unavailable(_token: str, _guild: str, _user: str):
        raise httpx.ConnectError("Discord unavailable for second account")

    with (
        patch.object(discord, "member_roles", new=unavailable),
        patch.object(
            discord_roles.channel_identity_repo,
            "list_for_user",
            new=AsyncMock(return_value=[unread, sender]),
        ),
    ):
        assert not await DiscordRoleSync(db).sync(
            org.id, bob.id, seen={(bot.id, GUILD, sender.platform_user_id): frozenset({FINANCE})}
        )
    membership = await _membership(db, org, bob)
    assert membership is not None
    assert membership.source == ("manual" if existing else "discord")
    assert await _groups(db, bob) == {group.id: "discord"}
