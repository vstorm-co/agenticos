"""Channel transport handoff and account-policy boundaries without live credentials."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.teams_conversation import TeamsConversation
from app.repositories import notification_route as route_repo
from app.schemas.notification_route import NotificationRouteUpdate
from app.services import notification_routes as routes
from app.services.channels.base import OutgoingMessage
from app.services.channels.teams import ConversationRef, conversation_key

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def destination(platform: str = "slack") -> route_repo.Destination:
    bot = ChannelBot(
        id=uuid4(),
        organization_id=uuid4(),
        name="Assistant",
        platform=platform,
        token_encrypted="secret",
        api_base_url="https://chat.example.com",
        access_policy={},
    )
    identity = ChannelIdentity(
        id=uuid4(),
        platform=platform,
        user_id=uuid4(),
        platform_user_id="ada",
        created_at=datetime.now(UTC),
    )
    session = ChannelSession(
        id=uuid4(),
        bot_id=bot.id,
        identity_id=identity.id,
        platform_chat_id="private:thread",
        chat_type="private",
    )
    return session, bot, identity


class Transport:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[str, OutgoingMessage]] = []
        self.ref: ConversationRef | None = None
        self.closed = False
        self.fail = fail

    def know(self, ref: ConversationRef) -> None:
        self.ref = ref

    async def aclose(self) -> None:
        self.closed = True

    async def send_notification(
        self, token: str, message: OutgoingMessage, *, context_url: str | None
    ) -> None:
        from dataclasses import replace

        if context_url:
            message = replace(message, text=f"{message.text}\n\n{context_url}")
        await self.send_message(token, message)

    async def send_message(self, token: str, message: OutgoingMessage) -> None:
        self.messages.append((token, message))
        if self.fail:
            raise TimeoutError("Unconfirmed submission")


@pytest.mark.parametrize(
    "platform,name",
    [
        ("slack", "SlackAdapter"),
        ("telegram", "TelegramAdapter"),
        ("mattermost", "MattermostAdapter"),
        ("teams", "TeamsAdapter"),
        ("sms", "SmsAdapter"),
        ("imessage", "ImessageAdapter"),
        ("discord", "DiscordAdapter"),
    ],
)
@pytest.mark.parametrize("fail", [False, True])
async def test_transport_reuses_platform_contract_and_closes_resources(
    mock_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    name: str,
    fail: bool,
) -> None:
    source = destination(platform)
    if platform == "teams":
        source[0].platform_chat_id = f"{conversation_key('teams-private')}:thread"
    transport = Transport(fail=fail)
    monkeypatch.setattr(
        importlib.import_module(f"app.services.channels.{platform}"), name, lambda: transport
    )
    monkeypatch.setattr(routes, "unseal_bot_token", lambda bot: "opaque credential")
    monkeypatch.setattr(routes.settings, "FRONTEND_URL", "https://console.example.com")
    monkeypatch.setattr(
        route_repo,
        "teams_reference",
        AsyncMock(
            return_value=TeamsConversation(
                conversation_id="teams-private",
                service_url="https://smba.trafficmanager.net/emea/",
                conversation_type="personal",
                tenant_id="tenant",
                name="Ada",
            )
        ),
    )
    service = routes.NotificationRouteService(mock_db_session)
    if fail:
        with pytest.raises(TimeoutError):
            await service._send(source, summary="Done <@someone>", context_url="/runs")
    else:
        await service._send(source, summary="Done <@someone>", context_url="/runs")
    token, message = transport.messages[0]
    assert token == "opaque credential"
    assert message.platform_chat_id == source[0].platform_chat_id
    assert message.api_base_url == "https://chat.example.com"
    assert "https://console.example.com/runs" in message.text
    assert "<@someone>" in message.text
    assert len(transport.messages) == 1
    if platform == "teams":
        assert transport.ref is not None and transport.ref.conversation_type == "personal"
    if platform != "telegram":
        assert transport.closed


async def test_missing_private_teams_reference_refuses_before_credentials(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(route_repo, "teams_reference", AsyncMock(return_value=None))
    unseal = AsyncMock()
    monkeypatch.setattr(routes, "unseal_bot_token", unseal)
    with pytest.raises(NotFoundError):
        await routes.NotificationRouteService(mock_db_session)._send(
            destination("teams"), summary="Done", context_url=None
        )
    unseal.assert_not_called()


@pytest.mark.parametrize(
    "policy,allowed",
    [
        ({}, True),
        ({"mode": "whitelist", "whitelist": ["ada"]}, True),
        ({"mode": "whitelist", "whitelist": []}, False),
        ({"mode": "group_only"}, False),
        ({"mode": "invalid"}, False),
        ('{"mode":"jwt_linked"}', True),
    ],
)
async def test_policy_is_checked_without_a_provider_request(policy: object, allowed: bool) -> None:
    source = destination()
    source[1].access_policy = policy
    assert routes.available(source) is allowed


async def test_sms_requires_current_number_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    source = destination("sms")
    source[2].created_at = datetime.now(UTC) - timedelta(days=91)
    monkeypatch.setattr(routes.settings, "SMS_LINK_MAX_AGE_DAYS", 90)
    assert not routes.available(source)
    source[2].updated_at = datetime.now(UTC)
    assert routes.available(source)
    monkeypatch.setattr(routes.settings, "SMS_LINK_MAX_AGE_DAYS", 0)
    source[2].updated_at = None
    assert routes.available(source)


@pytest.mark.parametrize("field", ["impersonation", "fired_as_creator"])
async def test_background_or_impersonated_actor_cannot_enable_routes(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    if field == "impersonation":
        monkeypatch.setattr(routes, "current_impersonator", lambda: uuid4())
    else:
        ctx = replace(ctx, fired_as_creator="schedule")
    with pytest.raises(AuthorizationError):
        await routes.NotificationRouteService(mock_db_session).replace(
            ctx, NotificationRouteUpdate(channel="sms", session_id=None)
        )


async def test_unscoped_or_revoked_route_never_resolves_credentials(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = routes.NotificationRouteService(mock_db_session)
    send = AsyncMock()
    monkeypatch.setattr(service, "_send", send)
    notification = Notification(organization_id=None, recipient_user_id=uuid4())
    delivery = NotificationDelivery(channel="slack", route_id=uuid4())
    assert (
        await service.deliver(delivery, notification, summary="Done", context_url=None) == "skipped"
    )
    notification.organization_id = uuid4()
    monkeypatch.setattr(route_repo, "current", AsyncMock(return_value=None))
    assert (
        await service.deliver(delivery, notification, summary="Done", context_url=None) == "skipped"
    )
    send.assert_not_awaited()


async def test_inconsistent_teams_reference_cannot_fall_back_to_another_bot(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        route_repo,
        "teams_reference",
        AsyncMock(
            return_value=TeamsConversation(
                conversation_id="different-conversation",
                service_url="https://smba.trafficmanager.net/emea/",
                conversation_type="personal",
                tenant_id="tenant",
                name="Ada",
            )
        ),
    )
    with pytest.raises(NotFoundError):
        await routes.NotificationRouteService(mock_db_session)._send(
            destination("teams"), summary="Done", context_url=None
        )


async def test_unknown_transport_refuses_instead_of_defaulting_to_email(
    mock_db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="Unsupported notification transport"):
        await routes.NotificationRouteService(mock_db_session)._send(
            destination("unknown"), summary="Done", context_url=None
        )


@pytest.mark.parametrize(
    "change,rotates", [("token", True), ("server", True), ("same_server", False), ("name", False)]
)
async def test_explicit_bot_authorization_changes_invalidate_notification_consent(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, change: str, rotates: bool
) -> None:
    from app.schemas.channel_bot import ChannelBotUpdate
    from app.services import channel_bot

    _, bot, _ = destination("mattermost")
    original = uuid4()
    bot.authorization_generation = original
    service = channel_bot.ChannelBotService(mock_db_session, organization_id=bot.organization_id)
    monkeypatch.setattr(service, "get", AsyncMock(return_value=bot))
    monkeypatch.setattr(service, "_seal_at", lambda value, *, key_version: "sealed")
    monkeypatch.setattr(service, "_reopen_stream", lambda row: None)
    monkeypatch.setattr(service, "_refuse_unless_mappings_removable", AsyncMock())
    update = AsyncMock(return_value=bot)
    monkeypatch.setattr(channel_bot.channel_bot_repo, "update", update)
    fields = (
        {"token": "t" * 24}
        if change == "token"
        else {"api_base_url": "https://other.example.com"}
        if change == "server"
        else {"api_base_url": bot.api_base_url}
        if change == "same_server"
        else {"name": "Renamed"}
    )
    await service.update(
        bot.id,
        ChannelBotUpdate.model_validate(fields),
        AuthContext(user_id=uuid4(), organization_id=bot.organization_id, role="owner"),
    )
    written = update.await_args.kwargs["update_data"]
    assert ("authorization_generation" in written) is rotates
    if rotates:
        assert written["authorization_generation"] != original
