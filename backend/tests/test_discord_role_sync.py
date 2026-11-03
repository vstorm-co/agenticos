"""The Discord role sync's edges no database run reaches (#2569).

Where it sits in a turn, where the worker finds its adapter, and what it does
when it races itself or a bot is deleted under it. The rules themselves are
pinned against real rows in `tests/integration/test_discord_role_groups.py`.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestError
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.services import channels
from app.services.channels.base import IncomingMessage
from app.services.channels.discord import DiscordAdapter
from app.services.channels.discord_roles import DiscordRoleSync, discord_adapter
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
                new=AsyncMock(return_value={bot_id: MagicMock(id=bot_id)}),
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
        assert place.await_args.kwargs == {"keep": False}
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


def test_a_mapping_row_says_which_role_it_maps():
    assert "guild=1100, role=7" in repr(DiscordRoleMapping(guild_id="1100", discord_role_id="7"))
