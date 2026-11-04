"""The Discord role sync's edges no database run reaches (#2569).

Where it sits in a turn, where the worker finds its adapter, and what it does
when it races itself or a bot is deleted under it. The rules themselves are
pinned against real rows in `tests/integration/test_discord_role_groups.py`.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestError
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.services import channels, rate_limit
from app.services.channels import router as router_module
from app.services.channels.base import IncomingMessage
from app.services.channels.discord import DiscordAdapter
from app.services.channels.discord_roles import (
    DiscordRoleSync,
    discord_adapter,
    sweep_discord_roles,
)
from app.services.channels.router import ChannelMessageRouter
from app.worker.tasks import channel_tasks

pytestmark = pytest.mark.anyio

SYNC = "app.services.channels.discord_roles"


class _Savepoint:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _db() -> MagicMock:
    db = MagicMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())
    return db


def _incoming(platform: str) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        bot_id=str(uuid.uuid4()),
        platform_user_id="1234",
        platform_chat_id="c-1",
        chat_type="private",
        text="hej",
        raw={"guild_id": "1100", "member": {"roles": ["7"]}},
    )


class TestWhereItRunsInATurn:
    async def _route(self, platform: str) -> tuple[AsyncMock, list[str]]:
        order: list[str] = []
        on_turn = AsyncMock(side_effect=lambda *_: order.append("roles"))
        command = AsyncMock(side_effect=lambda *_: order.append("command") or "handled")
        bot = MagicMock(is_active=True, access_policy={})
        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                new=AsyncMock(return_value=bot),
            ),
            patch.object(
                ChannelMessageRouter,
                "_resolve_identity",
                new=AsyncMock(return_value=MagicMock(user_id=uuid.uuid4())),
            ),
            patch.object(DiscordRoleSync, "on_turn", new=on_turn),
            patch.object(ChannelMessageRouter, "_handle_command", new=command),
            patch.object(ChannelMessageRouter, "_send_reply", new=AsyncMock()),
        ):
            await ChannelMessageRouter()._route_inner(_incoming(platform), MagicMock())
        return on_turn, order

    async def test_a_discord_turn_reconciles_roles_before_anything_is_answered(self):
        on_turn, order = await self._route("discord")

        assert order == ["roles", "command"]
        assert on_turn.await_args.args[2] == {"guild_id": "1100", "member": {"roles": ["7"]}}

    async def test_another_platform_never_asks_discord(self):
        on_turn, order = await self._route("mattermost")

        on_turn.assert_not_awaited()
        assert order == ["command"]


class TestTheRoleSyncsAllowance:
    """The sync asks Discord ahead of the commands, so it is counted even when a command answers."""

    @pytest.fixture(autouse=True)
    def _windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(router_module, "_fallback_windows", rate_limit.LocalWindows())

    def _bot(self) -> MagicMock:
        return MagicMock(id=uuid.uuid4(), is_active=True, access_policy={"rate_limit_rpm": 1})

    async def test_a_command_spends_it_and_the_next_asks_discord_nothing(self):
        bot, identity = self._bot(), MagicMock(user_id=uuid.uuid4())
        on_turn, command, refuse = (
            AsyncMock(),
            AsyncMock(return_value="Available commands"),
            AsyncMock(),
        )
        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                new=AsyncMock(return_value=bot),
            ),
            patch.object(
                ChannelMessageRouter, "_resolve_identity", new=AsyncMock(return_value=identity)
            ),
            patch.object(DiscordRoleSync, "on_turn", new=on_turn),
            patch.object(ChannelMessageRouter, "_handle_command", new=command),
            patch.object(ChannelMessageRouter, "_send_reply", new=AsyncMock()),
            patch.object(ChannelMessageRouter, "_refuse_if_named", new=refuse),
        ):
            for _ in range(2):
                await ChannelMessageRouter()._route_inner(_incoming("discord"), MagicMock())

        on_turn.assert_awaited_once()
        command.assert_awaited_once()
        assert refuse.await_args.args[2] == "Rate limit exceeded. Please slow down."

    async def test_an_ask_past_it_is_refused_before_discord_is_asked(self):
        bot, identity = self._bot(), MagicMock(user_id=uuid.uuid4())
        on_turn = AsyncMock()
        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                new=AsyncMock(return_value=bot),
            ),
            patch.object(ChannelMessageRouter, "_check_access"),
            patch.object(
                ChannelMessageRouter, "_resolve_identity", new=AsyncMock(return_value=identity)
            ),
            patch.object(DiscordRoleSync, "on_turn", new=on_turn),
            patch.object(ChannelMessageRouter, "_admits_unlinked", return_value=True),
        ):
            router = ChannelMessageRouter()
            assert await router.refusal_before_publishing(_incoming("discord"), MagicMock()) is None
            refusal = await router.refusal_before_publishing(_incoming("discord"), MagicMock())

        assert refusal == "Rate limit exceeded. Please slow down."
        on_turn.assert_awaited_once()

    async def test_an_unlinked_sender_is_asked_about_nothing_and_not_counted(self):
        bot, identity = self._bot(), MagicMock(user_id=None)
        with patch.object(DiscordRoleSync, "on_turn", new=AsyncMock()) as on_turn:
            for _ in range(3):
                await ChannelMessageRouter()._sync_discord_roles(
                    bot, identity, _incoming("discord"), MagicMock()
                )

        on_turn.assert_not_awaited()


class TestThePreflightBeforeAsk:
    """`/ask` posts the sender's words before the turn runs, so its check syncs first."""

    async def _preflight(self, platform: str, *, member: bool) -> tuple[str | None, list[str]]:
        order: list[str] = []
        bot = MagicMock(is_active=True, access_policy={})

        async def sender_is_member(*_: object) -> bool:
            order.append("membership")
            return member

        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                new=AsyncMock(return_value=bot),
            ),
            patch.object(ChannelMessageRouter, "_check_access"),
            patch.object(
                ChannelMessageRouter,
                "_resolve_identity",
                new=AsyncMock(return_value=MagicMock(user_id=uuid.uuid4())),
            ),
            patch.object(
                DiscordRoleSync,
                "on_turn",
                new=AsyncMock(side_effect=lambda *_: order.append("roles")),
            ),
            patch.object(ChannelMessageRouter, "_admits_unlinked", return_value=False),
            patch.object(ChannelMessageRouter, "_sender_is_active_member", new=sender_is_member),
        ):
            refusal = await ChannelMessageRouter().refusal_before_publishing(
                _incoming(platform), MagicMock()
            )
        return refusal, order

    async def test_roles_are_reconciled_before_the_membership_is_checked(self):
        refusal, order = await self._preflight("discord", member=True)

        assert refusal is None
        assert order == ["roles", "membership"]

    async def test_another_platform_is_checked_without_asking_discord(self):
        _, order = await self._preflight("mattermost", member=True)

        assert order == ["membership"]


class TestABotTokenThatDoesNotUnseal:
    async def test_is_unknown_rather_than_an_error(self):
        """One bot's broken token must not fail every turn the organization's other bots take."""
        bot = MagicMock(id=uuid.uuid4())
        adapter = MagicMock(member_roles=AsyncMock())
        with patch(
            f"{SYNC}.unseal_bot_token",
            side_effect=BadRequestError(message="Stored secret is malformed"),
        ):
            roles = await DiscordRoleSync(_db())._ask(adapter, bot, "1100", "1234")

        assert roles is None
        adapter.member_roles.assert_not_awaited()


class TestTheAdapter:
    def test_a_worker_with_none_registered_registers_one(self):
        with patch.dict(channels._adapters, clear=True):
            adapter = discord_adapter()

            assert isinstance(adapter, DiscordAdapter)
            assert channels.get_adapter("discord") is adapter

    def test_the_apis_own_adapter_is_the_one_used(self):
        registered = DiscordAdapter()
        with patch.dict(channels._adapters, {"discord": registered}, clear=True):
            assert discord_adapter() is registered


class TestTheSyncRacingItself:
    """A turn and the sweep reconciling one person at once: the loser keeps what the winner wrote."""

    def _patched(self, *, membership: MagicMock | None) -> tuple[MagicMock, MagicMock, AsyncMock]:
        org_id, bot_id = uuid.uuid4(), uuid.uuid4()
        mapping = MagicMock(
            organization_id=org_id,
            channel_bot_id=bot_id,
            guild_id="1100",
            discord_role_id="7",
            group_id=uuid.uuid4(),
            role="member",
        )
        members = MagicMock(get=AsyncMock(return_value=membership))
        members.create = AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
        groups = MagicMock(list_memberships_in_org=AsyncMock(return_value=[]))
        groups.add_member = AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
        audit = AsyncMock()
        self.org_id = org_id
        self.patches = [
            patch(
                f"{SYNC}.discord_role_mapping_repo.list_for_org",
                new=AsyncMock(return_value=[mapping]),
            ),
            patch(
                f"{SYNC}.channel_identity_repo.list_for_user",
                new=AsyncMock(
                    return_value=[
                        MagicMock(platform="discord", platform_user_id="1234", is_active=True)
                    ]
                ),
            ),
            patch(
                f"{SYNC}.channel_bot_repo.get_by_ids",
                new=AsyncMock(return_value={bot_id: MagicMock(id=bot_id, access_policy={})}),
            ),
            patch(f"{SYNC}.discord_adapter", return_value=MagicMock()),
            patch(f"{SYNC}.unseal_bot_token", return_value="tok"),
            patch.object(DiscordRoleSync, "_ask", new=AsyncMock(return_value=frozenset({"7"}))),
            patch(
                f"{SYNC}.user_repo.get_by_id", new=AsyncMock(return_value=MagicMock(is_active=True))
            ),
            patch(f"{SYNC}.member_repo", new=members),
            patch(f"{SYNC}.group_repo", new=groups),
            patch(f"{SYNC}.record_audit", new=audit),
        ]
        return members, groups, audit

    async def _sync(self) -> bool:
        for active in self.patches:
            active.start()
        try:
            return await DiscordRoleSync(_db()).sync(self.org_id, uuid.uuid4())
        finally:
            for active in reversed(self.patches):
                active.stop()

    async def test_a_membership_created_concurrently_is_not_an_error(self):
        _, groups, audit = self._patched(membership=None)
        groups.add_member = AsyncMock()

        assert await self._sync()

        audit.assert_awaited_once()  # the group joined; nobody admitted twice
        assert audit.await_args.kwargs["action"] == "discord.group_joined"

    async def test_a_group_membership_created_concurrently_is_not_an_error(self):
        _, _, audit = self._patched(membership=MagicMock(source="manual", role="member"))

        assert await self._sync()

        audit.assert_not_awaited()


class TestABotDeletedUnderTheSync:
    async def test_its_mappings_match_nobody(self):
        """The mapping and its bot are read one after the other: a bot deleted in
        between takes its mappings with it, and they match nothing this time."""
        org_id, user_id = uuid.uuid4(), uuid.uuid4()
        mapping = MagicMock(channel_bot_id=uuid.uuid4(), guild_id="1100", discord_role_id="7")
        with (
            patch(
                f"{SYNC}.discord_role_mapping_repo.list_for_org",
                new=AsyncMock(return_value=[mapping]),
            ),
            patch(
                f"{SYNC}.channel_identity_repo.list_for_user",
                new=AsyncMock(
                    return_value=[
                        MagicMock(platform="discord", platform_user_id="1234", is_active=True)
                    ]
                ),
            ),
            patch(f"{SYNC}.channel_bot_repo.get_by_ids", new=AsyncMock(return_value={})),
            patch(f"{SYNC}.discord_adapter", return_value=MagicMock()),
            patch.object(DiscordRoleSync, "_ask", new=AsyncMock()) as ask,
            patch.object(DiscordRoleSync, "_place", new=AsyncMock(return_value=True)) as place,
            patch.object(DiscordRoleSync, "_sync_groups", new=AsyncMock()) as groups,
        ):
            assert await DiscordRoleSync(_db()).sync(org_id, user_id)

        ask.assert_not_awaited()
        assert place.await_args.args == (user_id, org_id, None)
        assert place.await_args.kwargs == {"unread_roles": frozenset()}
        assert groups.await_args.kwargs == {"wanted": set(), "keep": set()}


class TestTheSweepTask:
    async def test_people_discord_did_not_answer_for_are_reported(self, caplog):
        with patch.object(
            channel_tasks,
            "sweep_discord_roles",
            new=AsyncMock(return_value={"synced": 3, "unreadable": 2, "failed": 1}),
        ):
            counts = await channel_tasks.sync_discord_roles()

        assert counts == {"synced": 3, "unreadable": 2, "failed": 1}
        assert "2 person(s) could not be checked" in caplog.text
        assert "1 person(s) failed" in caplog.text

    async def test_a_clean_sweep_says_nothing(self, caplog):
        with patch.object(
            channel_tasks,
            "sweep_discord_roles",
            new=AsyncMock(return_value={"synced": 3, "unreadable": 0, "failed": 0}),
        ):
            await channel_tasks.sync_discord_roles()

        assert "could not be checked" not in caplog.text
        assert "failed" not in caplog.text


class TestTheSweepOrder:
    async def test_a_sweep_cut_short_does_not_always_stop_at_the_same_person(self):
        """The job's timeout ends a sweep wherever it has got to; a fixed order
        would leave whoever sorts last unchecked on every run."""
        people = [(uuid.uuid4(), uuid.uuid4()) for _ in range(8)]
        firsts: list[tuple[uuid.UUID, uuid.UUID]] = []
        visited: list[tuple[uuid.UUID, uuid.UUID]] = []

        async def sync(self: DiscordRoleSync, organization_id, user_id, **kwargs):
            visited.append((organization_id, user_id))
            return True

        @asynccontextmanager
        async def sessions():
            yield MagicMock()

        with (
            patch(
                "app.services.channels.discord_roles.discord_role_mapping_repo.synced_people",
                AsyncMock(return_value=people),
            ),
            patch.object(DiscordRoleSync, "sync", new=sync),
        ):
            for _ in range(20):
                visited.clear()
                counts = await sweep_discord_roles(sessions)
                assert sorted(visited) == sorted(people)
                firsts.append(visited[0])

        assert counts == {"synced": 8, "unreadable": 0, "failed": 0}
        assert len(set(firsts)) > 1


def test_a_mapping_row_says_which_role_it_maps():
    assert "guild=1100, role=7" in repr(DiscordRoleMapping(guild_id="1100", discord_role_id="7"))


@pytest.mark.security
class TestDirectoryMembershipGrant:
    @pytest.mark.parametrize(
        "roles,unknown,expected",
        [
            (frozenset({"7"}), set(), ("member", False)),
            (frozenset(), set(), (None, False)),
            (frozenset({"7"}), {"unread"}, ("member", True)),
        ],
    )
    async def test_grant_distinguishes_a_known_role_from_an_incomplete_answer(
        self, roles, unknown, expected
    ):
        org, user, bot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        mapping = MagicMock(channel_bot_id=bot, guild_id="g", discord_role_id="7", role="member")
        service = DiscordRoleSync(_db())
        mappings = [mapping]
        if unknown:
            mappings.append(
                MagicMock(
                    channel_bot_id=bot, guild_id="unread", discord_role_id="8", role="builder"
                )
            )
            unknown = {(bot, "unread")}
        with (
            patch(
                f"{SYNC}.discord_role_mapping_repo.list_for_org",
                new=AsyncMock(return_value=mappings),
            ),
            patch(
                f"{SYNC}.channel_identity_repo.list_for_user",
                new=AsyncMock(
                    return_value=[
                        MagicMock(platform="discord", platform_user_id="u", is_active=True)
                    ]
                ),
            ),
            patch.object(
                service, "_held", new=AsyncMock(return_value=({(bot, "g"): roles}, unknown))
            ),
        ):
            grant = await service.membership_grant(org, user)
        assert (grant.role, grant.uncertain) == expected

    @pytest.mark.parametrize("mapped,linked", [(False, True), (True, False)])
    async def test_no_admission_mapping_or_linked_account_grants_nothing(self, mapped, linked):
        service = DiscordRoleSync(_db())
        with (
            patch(
                f"{SYNC}.discord_role_mapping_repo.list_for_org",
                new=AsyncMock(return_value=[MagicMock(role="member" if mapped else None)]),
            ),
            patch(
                f"{SYNC}.channel_identity_repo.list_for_user",
                new=AsyncMock(
                    return_value=[MagicMock(platform="discord", is_active=False)]
                    if not linked
                    else []
                ),
            ),
            patch.object(service, "_held", new=AsyncMock()) as held,
        ):
            grant = await service.membership_grant(uuid.uuid4(), uuid.uuid4())
        assert (grant.role, grant.uncertain) == (None, False)
        held.assert_not_awaited()

    @pytest.mark.parametrize("expired", [True, False])
    async def test_network_budget_exhaustion_keeps_the_admission_uncertain(self, expired):
        import asyncio

        bot = uuid.uuid4()
        mapping = MagicMock(channel_bot_id=bot, guild_id="g")
        service = DiscordRoleSync(_db())
        with (
            patch(
                f"{SYNC}.channel_bot_repo.get_by_ids",
                new=AsyncMock(return_value={bot: MagicMock()}),
            ),
            patch(f"{SYNC}.discord_adapter", return_value=MagicMock()),
            patch(f"{SYNC}._lookup_allowed", new=AsyncMock(return_value=True)),
            patch.object(service, "_ask", new=AsyncMock(side_effect=TimeoutError)) as ask,
        ):
            _, unknown = await service._held(
                [mapping],
                ["u"],
                {},
                user_id=uuid.uuid4(),
                deadline=0 if expired else asyncio.get_running_loop().time() + 10,
            )
        assert unknown == {(bot, "g")}
        assert ask.await_count == (0 if expired else 1)


@pytest.mark.security
async def test_a_discord_ask_preflight_spends_one_allowance_when_routed_to_its_thread():
    from dataclasses import replace

    bot = MagicMock(id=uuid.uuid4())
    identity = MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4())
    incoming = _incoming("discord")
    router = ChannelMessageRouter()
    with (
        patch.object(router, "_check_rate_limit", new=AsyncMock()) as meter,
        patch.object(DiscordRoleSync, "on_turn", new=AsyncMock()) as sync,
    ):
        await router._sync_discord_roles(bot, identity, incoming, MagicMock())
        routed = replace(incoming, platform_chat_id="new-thread")
        await router._sync_discord_roles(bot, identity, routed, MagicMock())
        assert meter.await_count == 1 and sync.await_count == 1
        identity.user_id = uuid.uuid4()
        await router._sync_discord_roles(bot, identity, routed, MagicMock())
        assert meter.await_count == 2 and sync.await_count == 2


@pytest.mark.parametrize(
    "previous,confirmed,unread,expected",
    [
        ("admin", None, frozenset({"viewer"}), "viewer"),
        ("viewer", None, frozenset({"admin"}), "viewer"),
        ("builder", None, frozenset({"operator"}), "viewer"),
        ("viewer", "admin", frozenset({"viewer"}), "admin"),
        ("admin", None, frozenset(), None),
    ],
)
def test_unread_roles_cannot_retain_or_add_unjustified_authority(
    previous, confirmed, unread, expected
):
    from app.services.directory import retained_role

    assert retained_role(previous, confirmed, unread) == expected


@pytest.mark.parametrize("metered", [True, False])
async def test_rest_allowance_is_shared_by_all_linked_accounts(metered, monkeypatch):
    from app.services.channels import discord_roles

    monkeypatch.setattr(discord_roles, "_lookup_windows", rate_limit.LocalWindows())
    bot = MagicMock(id=uuid.uuid4(), access_policy={"rate_limit_rpm": 1})
    user = uuid.uuid4()
    service = DiscordRoleSync(_db())
    mapping = MagicMock(channel_bot_id=bot.id, guild_id="g")
    with (
        patch(f"{SYNC}.channel_bot_repo.get_by_ids", AsyncMock(return_value={bot.id: bot})),
        patch(f"{SYNC}.discord_adapter", return_value=MagicMock()),
        patch(
            f"{SYNC}.rate_limit.consume",
            AsyncMock(
                side_effect=[
                    rate_limit.Decision(True, 0, metered=metered),
                    rate_limit.Decision(False, 60, metered=metered),
                ]
            ),
        ) as meter,
        patch.object(service, "_ask", AsyncMock(return_value=frozenset({"7"}))) as ask,
    ):
        import asyncio

        held, unknown = await service._held(
            [mapping],
            ["account-a", "account-b"],
            {},
            user_id=user,
            deadline=asyncio.get_running_loop().time() + 10,
        )
    assert ask.await_count == 1
    assert held == {(bot.id, "g"): frozenset({"7"})}
    assert unknown == {(bot.id, "g")}
    assert {call.kwargs["caller"] for call in meter.await_args_list} == {
        f"bot:{bot.id}:user:{user}"
    }


@pytest.mark.security
async def test_expired_budget_still_uses_confirmed_payload_without_an_rpc():
    bot, user = uuid.uuid4(), uuid.uuid4()
    mapping = MagicMock(channel_bot_id=bot, guild_id="g")
    service = DiscordRoleSync(_db())
    with (
        patch(f"{SYNC}.channel_bot_repo.get_by_ids", AsyncMock(return_value={bot: MagicMock()})),
        patch(f"{SYNC}.discord_adapter", return_value=MagicMock()),
        patch(f"{SYNC}._lookup_allowed", AsyncMock()) as meter,
    ):
        held, unknown = await service._held(
            [mapping],
            ["a", "b"],
            {(bot, "g", "a"): frozenset({"7"})},
            user_id=user,
            deadline=0,
        )
    assert held == {(bot, "g"): frozenset({"7"})}
    assert unknown == {(bot, "g")}
    meter.assert_not_awaited()


@pytest.mark.security
async def test_message_checks_for_two_accounts_share_the_linked_user_budget():
    bot = MagicMock(id=uuid.uuid4())
    user = uuid.uuid4()
    router = ChannelMessageRouter()
    with (
        patch.object(router, "_check_rate_limit", AsyncMock()) as meter,
        patch.object(DiscordRoleSync, "on_turn", AsyncMock()),
    ):
        for _ in range(2):
            await router._sync_discord_roles(
                bot, MagicMock(id=uuid.uuid4(), user_id=user), _incoming("discord"), MagicMock()
            )
    assert [call.args[1] for call in meter.await_args_list] == [f"user:{user}"] * 2


async def test_server_discovery_deadline_cancels_its_network_work(monkeypatch):
    import asyncio

    from app.core.exceptions import ExternalServiceError
    from app.services import discord_role_mapping
    from app.services.discord_role_mapping import DiscordRoleMappingService

    monkeypatch.setattr(discord_role_mapping, "_SERVER_DISCOVERY_TIMEOUT_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def blocked(token: str) -> list[object]:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return []

    bot = MagicMock(id=uuid.uuid4())
    with (
        patch.object(discord_role_mapping, "unseal_bot_token", return_value="tok"),
        patch.object(
            discord_role_mapping,
            "discord_adapter",
            return_value=MagicMock(servers=AsyncMock(side_effect=blocked)),
        ),
        pytest.raises(ExternalServiceError),
    ):
        await DiscordRoleMappingService(_db())._servers(bot)
    assert cancelled.is_set()


async def test_concurrent_server_discovery_is_refused_across_bots_in_one_org():
    import asyncio

    from app.core.exceptions import RateLimitError
    from app.core.permissions import AuthContext
    from app.services.discord_role_mapping import DiscordRoleMappingService

    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    started, finish = asyncio.Event(), asyncio.Event()
    service = DiscordRoleMappingService(_db())

    async def blocked(bot: object) -> list[object]:
        started.set()
        await finish.wait()
        return []

    with (
        patch.object(service, "_bot", AsyncMock(return_value=MagicMock())),
        patch.object(service, "_servers", side_effect=blocked) as discovery,
    ):
        task = asyncio.create_task(service.servers(ctx, uuid.uuid4()))
        try:
            await asyncio.wait_for(started.wait(), 1)
            with pytest.raises(RateLimitError):
                await service.servers(ctx, uuid.uuid4())
            assert discovery.await_count == 1
        finally:
            finish.set()
            await asyncio.wait_for(task, 1)
