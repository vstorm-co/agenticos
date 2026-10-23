"""A Teams bot end to end: its endpoint, its registration, its app package, its posts (#1985).

The endpoint is called as a function with the Bot Connector's token check stubbed
to pass or refuse; what the token check itself refuses is `test_teams_auth.py`.
"""

import io
import json
import uuid
import zipfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.v1.teams_webhook import PRESS_RECEIVED, teams_messages
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.channel_bot import ChannelBotCreate
from app.services.agent_trigger import AgentTriggerService
from app.services.channel_bot import ChannelBotService, unseal_bot_token
from app.services.channel_link import ChannelLinkService
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.teams import ConversationRef, TeamsAdapter, conversation_key
from app.services.channels.teams_auth import TeamsAuthError, TeamsCredentials
from app.services.channels.teams_package import teams_app_package, teams_manifest
from app.services.channels.teams_post import post_to_teams

pytestmark = pytest.mark.anyio

APP_ID = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
SERVICE = "https://smba.trafficmanager.net/emea/"
ROUTE = "app.api.routes.v1.teams_webhook"


def _bot(**overrides: Any) -> MagicMock:
    bot = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        platform="teams",
        teams_app_id=APP_ID,
        teams_tenant_id=TENANT,
        is_active=True,
    )
    bot.name = "Support"
    for field, value in overrides.items():
        setattr(bot, field, value)
    return bot


def _activity(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "1",
        "serviceUrl": SERVICE,
        "channelId": "msteams",
        "from": {"id": "29:x", "name": "Ada", "aadObjectId": "aad-ada"},
        "recipient": {"id": f"28:{APP_ID}"},
        "conversation": {"id": "a:1chat", "conversationType": "personal", "tenantId": TENANT},
        "text": "hello",
        **overrides,
    }


class _Called:
    """What the endpoint did with one activity."""

    def __init__(self) -> None:
        self.adapter = TeamsAdapter()
        self.service = MagicMock(record_teams_conversation=AsyncMock())


async def _post(
    activity: dict[str, Any],
    *,
    bot: MagicMock | None = None,
    refuse: str | None = None,
    authorization: str = "Bearer t",
) -> tuple[Any, _Called, MagicMock]:
    called = _Called()
    called.service.find_active = AsyncMock(return_value=bot)
    request = MagicMock(headers={"authorization": authorization})
    request.json = AsyncMock(return_value=activity)
    verify = AsyncMock(side_effect=TeamsAuthError(refuse) if refuse else None)
    with (
        patch(f"{ROUTE}.teams_adapter", return_value=called.adapter),
        patch.object(called.adapter.auth, "verify", verify),
        patch(
            f"{ROUTE}.unseal_bot_token",
            return_value=TeamsCredentials(APP_ID, TENANT, "s").encode(),
        ),
        patch(f"{ROUTE}.spawn") as spawn,
    ):
        answered = await teams_messages(uuid.uuid4(), request, called.service)
    for call in spawn.call_args_list:
        call.args[0].close()
    await called.adapter.aclose()
    return answered, called, spawn


class TestTheEndpoint:
    async def test_an_unknown_bot_answers_empty(self) -> None:
        answered, _, spawn = await _post(_activity(), bot=None)
        assert answered.status_code == 200
        spawn.assert_not_called()

    @pytest.mark.security
    async def test_a_bot_that_is_not_a_teams_bot_is_refused(self) -> None:
        with pytest.raises(HTTPException) as refused:
            await _post(_activity(), bot=_bot(platform="slack"))
        assert refused.value.status_code == 403

    @pytest.mark.security
    async def test_a_token_that_does_not_check_out_is_refused_before_anything_runs(self) -> None:
        with pytest.raises(HTTPException) as refused:
            await _post(_activity(), bot=_bot(), refuse="a token issued to another bot")
        assert refused.value.status_code == 401

    @pytest.mark.security
    async def test_another_tenant_is_refused(self) -> None:
        activity = _activity(
            conversation={"id": "a:1", "conversationType": "personal", "tenantId": "elsewhere"}
        )
        with pytest.raises(HTTPException) as refused:
            await _post(activity, bot=_bot())
        assert refused.value.status_code == 403

    @pytest.mark.security
    async def test_a_service_that_is_not_a_connector_is_refused(self) -> None:
        with pytest.raises(HTTPException) as refused:
            await _post(_activity(serviceUrl="https://attacker.example/"), bot=_bot())
        assert refused.value.status_code == 400

    async def test_a_message_is_recorded_and_answered_in_the_background(self) -> None:
        bot = _bot()
        answered, called, spawn = await _post(_activity(), bot=bot)

        assert answered.status_code == 200
        ref = called.service.record_teams_conversation.await_args.args[1]
        assert ref.conversation_id == "a:1chat"
        assert spawn.call_args.kwargs["name"].startswith("teams_event:")
        assert called.adapter._refs[conversation_key("a:1chat")] == ref

    async def test_a_message_with_nothing_in_it_is_recorded_only(self) -> None:
        _, _, spawn = await _post(_activity(text=""), bot=_bot())
        spawn.assert_not_called()

    async def test_a_press_is_answered_at_once_and_decided_in_the_background(self) -> None:
        activity = _activity(
            type="invoke",
            name="adaptiveCard/action",
            value={"action": {"verb": "aos", "data": {"aos": "aos:p:0"}}},
        )
        answered, _, spawn = await _post(activity, bot=_bot())

        assert answered == PRESS_RECEIVED
        assert spawn.call_args.kwargs["name"].startswith("teams_press:")

    async def test_a_press_that_is_not_ours_is_an_error_card(self) -> None:
        activity = _activity(type="invoke", name="adaptiveCard/action", value={})
        answered, _, spawn = await _post(activity, bot=_bot())
        assert answered["statusCode"] == 400
        spawn.assert_not_called()

    async def test_an_accepted_file_is_uploaded_in_the_background(self) -> None:
        activity = _activity(type="invoke", name="fileConsent/invoke", value={})
        answered, _, spawn = await _post(activity, bot=_bot())
        assert answered == {}
        assert spawn.call_args.kwargs["name"].startswith("teams_file:")

    async def test_being_added_somewhere_is_remembered_for_later_posts(self) -> None:
        answered, called, spawn = await _post(
            _activity(type="conversationUpdate", text=None), bot=_bot()
        )
        assert answered.status_code == 200
        called.service.record_teams_conversation.assert_awaited_once()
        spawn.assert_not_called()


class TestRegisteringABot:
    def test_a_teams_bot_carries_its_app_and_tenant_and_is_a_webhook_bot(self) -> None:
        bot = ChannelBotCreate(
            platform="teams",
            name="Support",
            token="client-secret-value",
            teams_app_id=APP_ID,
            teams_tenant_id=TENANT,
        )
        assert bot.webhook_mode is True

    @pytest.mark.parametrize(
        "fields",
        [
            {"platform": "teams", "teams_app_id": APP_ID},
            {"platform": "teams", "teams_tenant_id": TENANT},
            {"platform": "slack", "teams_app_id": APP_ID, "teams_tenant_id": TENANT},
            {"platform": "teams", "teams_app_id": "not-a-guid", "teams_tenant_id": TENANT},
        ],
    )
    def test_a_half_registration_or_one_on_another_platform_is_refused(
        self, fields: dict[str, str]
    ) -> None:
        with pytest.raises(ValidationError):
            ChannelBotCreate(name="Support", token="client-secret-value", **fields)

    @pytest.mark.security
    def test_the_token_carries_the_app_and_tenant_beside_the_secret(self) -> None:
        bot = _bot(token_encrypted="sealed", secret_key_version=1)
        with patch("app.services.channel_bot.unseal", return_value="the-secret"):
            token = unseal_bot_token(bot)
        assert TeamsCredentials.decode(token) == TeamsCredentials(APP_ID, TENANT, "the-secret")

    async def test_only_a_teams_bot_has_an_app_package(self) -> None:
        service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
        with (
            patch.object(service, "get", AsyncMock(return_value=_bot(platform="slack"))),
            pytest.raises(BadRequestError),
        ):
            await service.teams_app_package(uuid.uuid4())

    async def test_a_conversation_is_recorded_under_its_key(self) -> None:
        bot = _bot()
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        ref = ConversationRef("19:x@thread.v2", SERVICE, "channel", TENANT, "General")
        with patch(
            "app.services.channel_bot.teams_conversation_repo.record", new=AsyncMock()
        ) as record:
            await service.record_teams_conversation(bot, ref)
        assert record.await_args.kwargs["key"] == conversation_key("19:x@thread.v2")
        assert record.await_args.kwargs["service_url"] == SERVICE


class TestTheAppPackage:
    def test_the_manifest_names_the_bot_in_every_scope(self) -> None:
        manifest = teams_manifest(_bot())
        (bot,) = manifest["bots"]
        assert manifest["id"] == bot["botId"] == APP_ID
        assert bot["scopes"] == ["personal", "groupChat", "team"]
        assert {command["title"] for command in bot["commandLists"][0]["commands"]} >= {
            "link",
            "help",
        }

    def test_the_package_is_the_manifest_and_both_icons(self) -> None:
        from PIL import Image

        package = zipfile.ZipFile(io.BytesIO(teams_app_package(_bot())))
        assert sorted(package.namelist()) == ["color.png", "manifest.json", "outline.png"]
        assert json.loads(package.read("manifest.json"))["id"] == APP_ID
        with (
            Image.open(io.BytesIO(package.read("color.png"))) as color,
            Image.open(io.BytesIO(package.read("outline.png"))) as outline,
        ):
            sizes = (color.size, outline.size)
        assert sizes == ((192, 192), (32, 32))


class TestATriggerPostsItsAnswer:
    async def test_it_is_posted_as_a_new_message(self) -> None:
        bot = _bot()
        row = MagicMock(bot_id=bot.id, key="k" * 32, conversation_id="19:x", service_url=SERVICE)
        row.name = "General"
        adapter = MagicMock(send_message=AsyncMock())
        with (
            patch(
                "app.services.channels.teams_post.teams_conversation_repo.get_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.channels.teams_post.channel_bot_repo.get_by_ids",
                new=AsyncMock(return_value={bot.id: bot}),
            ),
            patch("app.services.channels.teams_post.teams_adapter", return_value=adapter),
            patch("app.services.channels.teams_post.unseal_bot_token", return_value="token"),
        ):
            assert await post_to_teams(MagicMock(), uuid.uuid4(), "**Daily** summary") is True
        message = adapter.send_message.await_args.args[1]
        assert (message.platform_chat_id, message.text) == ("k" * 32, "**Daily** summary")

    @pytest.mark.parametrize("gone", ["conversation", "bot", "inactive", "refused"])
    async def test_a_post_that_cannot_happen_is_logged_not_raised(self, gone: str) -> None:
        bot = _bot(is_active=gone != "inactive")
        row = None if gone == "conversation" else MagicMock(bot_id=bot.id, key="k")
        adapter = MagicMock(
            send_message=AsyncMock(side_effect=httpx.ConnectError("down"))
            if gone == "refused"
            else AsyncMock()
        )
        with (
            patch(
                "app.services.channels.teams_post.teams_conversation_repo.get_by_id",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.channels.teams_post.channel_bot_repo.get_by_ids",
                new=AsyncMock(return_value={} if gone == "bot" else {bot.id: bot}),
            ),
            patch("app.services.channels.teams_post.teams_adapter", return_value=adapter),
            patch("app.services.channels.teams_post.unseal_bot_token", return_value="token"),
        ):
            assert await post_to_teams(MagicMock(), uuid.uuid4(), "x") is False

    @pytest.mark.security
    async def test_a_target_that_is_not_one_of_the_organizations_channels_is_refused(
        self,
    ) -> None:
        """Another organization's conversation, or somebody's personal chat, is not found."""
        ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
        service = AgentTriggerService(MagicMock())
        with (
            patch(
                "app.services.agent_trigger.teams_conversation_repo.get_postable",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await service._teams_target(ctx, uuid.uuid4())

    def test_the_target_is_part_of_what_a_trigger_is_created_with(self) -> None:
        target = uuid.uuid4()
        data = TriggerCreate(
            prompt="Summarise the day", interval_seconds=3600, teams_conversation_id=target
        )
        assert data.teams_conversation_id == target


class TestLinkingWhoTheDirectoryVouchesFor:
    @pytest.mark.security
    @pytest.mark.parametrize(
        ("user", "linked"),
        [
            (MagicMock(is_active=True, oauth_provider="oidc"), True),
            (MagicMock(is_active=True, oauth_provider=None), False),
            (MagicMock(is_active=True, oauth_provider="google"), False),
            (MagicMock(is_active=False, oauth_provider="oidc"), False),
            (None, False),
        ],
    )
    async def test_only_an_account_that_signs_in_through_the_directory_is_linked(
        self, user: MagicMock | None, linked: bool
    ) -> None:
        identity = MagicMock(user_id=None)
        with (
            patch(
                "app.services.channel_link.user_repo.get_by_email", new=AsyncMock(return_value=user)
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as update,
        ):
            assert (
                await ChannelLinkService(MagicMock()).link_vouched(identity, "ada@acme.com")
                is linked
            )
        assert update.await_count == int(linked)

    async def test_the_router_links_whom_the_platform_vouches_for(self) -> None:
        adapter = MagicMock(vouched_email=AsyncMock(return_value="ada@acme.com"))
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="token"),
            patch.object(ChannelLinkService, "link_vouched", new=AsyncMock()) as link,
        ):
            await ChannelMessageRouter()._link_vouched(
                MagicMock(platform="teams"), MagicMock(), MagicMock(), MagicMock()
            )
        assert link.await_args.args[1] == "ada@acme.com"

    @pytest.mark.parametrize("answer", [None, httpx.ConnectError("down")])
    async def test_nothing_vouched_or_a_failed_lookup_leaves_the_link_flow(
        self, answer: Any
    ) -> None:
        adapter = MagicMock(
            vouched_email=AsyncMock(side_effect=answer)
            if isinstance(answer, Exception)
            else AsyncMock(return_value=answer)
        )
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="token"),
            patch.object(ChannelLinkService, "link_vouched", new=AsyncMock()) as link,
        ):
            await ChannelMessageRouter()._link_vouched(
                MagicMock(platform="teams"), MagicMock(), MagicMock(), MagicMock()
            )
        link.assert_not_awaited()


@pytest.mark.security
async def test_a_deactivated_members_teams_turn_is_refused() -> None:
    """#1427 from day one: a linked Teams account whose member was deactivated is
    refused at the same gate as on every other platform."""
    identity = MagicMock(user_id=uuid.uuid4())
    with patch(
        "app.services.channels.router.member_repo.get_active", new=AsyncMock(return_value=None)
    ):
        admitted = await ChannelMessageRouter()._sender_is_active_member(
            MagicMock(), _bot(), identity
        )
    assert admitted is False


def test_a_teams_bot_reads_back_the_endpoint_to_paste_into_azure() -> None:
    from app.schemas.channel_bot import ChannelBotRead

    def read(platform: str) -> ChannelBotRead:
        return ChannelBotRead(
            id=uuid.uuid4(),
            platform=platform,
            name="Support",
            is_active=True,
            webhook_mode=True,
            webhook_url=None,
            access_policy={"mode": "open"},
            created_at="2026-10-16T00:00:00Z",
        )

    teams_bot = read("teams")
    assert teams_bot.messaging_endpoint is not None
    assert teams_bot.messaging_endpoint.endswith(f"/api/v1/teams/{teams_bot.id}/messages")
    assert read("slack").messaging_endpoint is None


async def test_a_routine_is_offered_only_the_team_channels_to_post_into() -> None:
    """A group chat is private to its participants (Codex on #2324)."""
    listed = AsyncMock(return_value=[])
    with patch("app.services.channel_bot.teams_conversation_repo.list_shared", new=listed):
        await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).teams_conversations()

    assert listed.await_args.kwargs["types"] == ("channel",)
