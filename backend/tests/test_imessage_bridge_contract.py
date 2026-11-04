"""Provider boundaries use the configured Mac only and preserve explicit failures."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.permissions import AuthContext
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services import channel_bot as bots
from app.services.channel_bot import ChannelBotService, unseal_bot_token
from app.services.channels.base import IncomingAttachment, IncomingMessage, OutgoingMessage
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.imessage import ImessageAdapter
from app.services.channels.imessage_transport import BridgeClient, BridgeCredentials
from app.services.channels.webhooks import inbound_webhook_url

pytestmark = pytest.mark.anyio


def credential() -> BridgeCredentials:
    return BridgeCredentials(
        bot_id=uuid4(),
        server="https://mac.example.com/prefix",
        password=SecretStr("bridge-password"),
        webhook_secret=SecretStr("callback-secret"),
    )


async def test_webhook_registration_and_removal_are_bound_to_this_bot_only() -> None:
    credentials = credential()
    target = inbound_webhook_url("imessage", credentials.bot_id)
    calls: list[httpx.Request] = []

    def bridge(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["events"] == ["new-message"]
            assert "agenticos:callback-secret@" in body["url"]
            assert "bridge-password" not in body["url"]
            return httpx.Response(200, json={"status": 200, "data": {"id": 1, "url": body["url"]}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": [
                        {"id": 1, "url": target.replace("://", "://agenticos:old-secret@")},
                        {"id": 2, "url": target.replace(str(credentials.bot_id), str(uuid4()))},
                        {"id": 3, "url": "https://another-deployment.example.com"},
                        {"id": 4, "url": "https://bad.example.com:invalid"},
                    ],
                },
            )
        assert request.url.path.endswith("/webhook/1")
        return httpx.Response(200, json={"status": 200})

    adapter = ImessageAdapter(httpx.MockTransport(bridge))
    try:
        assert await adapter.register_webhook(credentials.encode(), target, "callback-secret")
        assert await adapter.delete_webhook(credentials.encode())
        assert [call.method for call in calls] == ["POST", "GET", "DELETE"]
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("invalid", ["missing", "bad_url", "other_callback"])
async def test_webhook_registration_never_reports_a_different_callback_as_success(
    invalid: str,
) -> None:
    credentials = credential()
    adapter = ImessageAdapter(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"status": 200, "data": {"id": 1, "url": "https://other.example.com"}},
            )
        )
    )
    try:
        with pytest.raises((ChannelNotConfigured, ExternalServiceError)):
            await adapter.register_webhook(
                credentials.encode(),
                "https://callback.example.com?secret=x"
                if invalid == "bad_url"
                else "https://callback.example.com",
                None if invalid == "missing" else "callback-secret",
            )
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("wrong_chat", [False, True])
async def test_group_membership_comes_from_the_live_bridge_and_must_name_the_same_chat(
    wrong_chat: bool,
) -> None:
    target = "iMessage;+;group"
    seen: list[str] = []

    def bridge(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.url.params["with"] == "participants"
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "guid": "iMessage;+;other" if wrong_chat else target,
                    "participants": [{"address": "ADA@example.com"}],
                },
            },
        )

    adapter = ImessageAdapter(httpx.MockTransport(bridge))
    try:
        token = credential().encode()
        assert await adapter.is_channel_member(
            token, "iMessage;-;ada@example.com", "ADA@example.com", api_base_url=None
        )
        assert not await adapter.is_channel_member(
            token, "iMessage;-;ada@example.com", "other@example.com", api_base_url=None
        )
        assert seen == []
        if wrong_chat:
            with pytest.raises(ExternalServiceError, match="another chat"):
                await adapter.is_channel_member(token, target, "ada@example.com", api_base_url=None)
        else:
            assert await adapter.is_channel_member(
                token, target, "ada@example.com", api_base_url=None
            )
            assert not await adapter.is_channel_member(
                token, target, "removed@example.com", api_base_url=None
            )
    finally:
        await adapter.aclose()


async def test_optional_working_indicator_uses_a_native_tapback() -> None:
    sent: list[bytes] = []
    adapter = ImessageAdapter(
        httpx.MockTransport(
            lambda request: (
                sent.append(request.content) or httpx.Response(200, json={"status": 200})
            )
        )
    )
    incoming = IncomingMessage(
        platform="imessage",
        bot_id="bot",
        platform_user_id="ada@example.com",
        platform_chat_id="iMessage;-;ada@example.com",
        chat_type="private",
        text="Hello",
        message_id="msg",
    )
    try:
        await adapter.acknowledge_message(credential().encode(), incoming, "eyes")
        assert json.loads(sent[0])["reaction"] == "emphasize"
        with pytest.raises(ValueError, match="supported"):
            await adapter.acknowledge_message(credential().encode(), incoming, "fire")
    finally:
        await adapter.aclose()


async def test_file_download_uses_only_a_guid_at_the_configured_endpoint() -> None:
    seen: list[str] = []

    def bridge(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        assert request.url.path.startswith("/prefix/api/v1/attachment/")
        assert request.url.path.endswith("/download")
        return httpx.Response(200, content=b"file-content")

    adapter = ImessageAdapter(httpx.MockTransport(bridge))
    try:
        content = await adapter.download_attachment(
            credential().encode(),
            IncomingAttachment(
                filename="report.txt",
                mime_type="text/plain",
                size=0,
                handle="https://untrusted.example.com/file",
            ),
        )
        assert content == b"file-content" and seen == ["mac.example.com"]
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("status,content,limit", [(500, b"error", 30), (200, b"too long", 2)])
async def test_download_errors_and_streamed_size_limits_remain_visible(
    status: int, content: bytes, limit: int
) -> None:
    client = BridgeClient(
        httpx.MockTransport(lambda _request: httpx.Response(status, content=content))
    )
    try:
        with pytest.raises(ExternalServiceError):
            await client.download(credential(), "/api/v1/attachment/file/download", limit=limit)
    finally:
        await client.close()


async def test_invalid_provider_response_is_a_controlled_error() -> None:
    class Receipt(BaseModel):
        status: int

    client = BridgeClient(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=b"not JSON"))
    )
    try:
        with pytest.raises(ExternalServiceError, match="invalid response"):
            await client.json_request(credential(), "GET", "/api/v1/server/info", Receipt)
    finally:
        await client.close()


async def test_provider_reported_send_error_is_not_success() -> None:
    adapter = ImessageAdapter(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"status": 200, "data": {"guid": "message", "error": 1}}
            )
        )
    )
    try:
        with pytest.raises(ExternalServiceError, match="delivery error"):
            await adapter.send_message(
                credential().encode(),
                OutgoingMessage(platform_chat_id="iMessage;-;ada@example.com", text="hello"),
            )
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "http://169.254.169.254",
        "http://metadata.google.internal",
        "https://user:pass@mac.example.com",
        "https://mac.example.com?password=secret",
    ],
)
def test_saved_configuration_refuses_missing_or_unsafe_bridge_addresses(
    endpoint: str | None,
) -> None:
    with pytest.raises(ValidationError):
        ChannelBotCreate(
            platform="imessage", name="Mac", token="bridge-password", api_base_url=endpoint
        )


def test_bridge_configuration_is_webhook_only_and_credentials_remain_vault_bound() -> None:
    config = ChannelBotCreate(
        platform="imessage", name="Mac", token="bridge-password", api_base_url="http://mac:1234"
    )
    assert config.webhook_mode
    org = uuid4()
    token, callback = (
        seal(config.token, scope=VaultScope.organization(org)),
        seal("callback-secret", scope=VaultScope.organization(org)),
    )
    bot = ChannelBot(
        id=uuid4(),
        organization_id=org,
        platform="imessage",
        name="Mac",
        token_encrypted=token.ciphertext,
        webhook_secret_encrypted=callback.ciphertext,
        secret_key_version=token.key_version,
        api_base_url=config.api_base_url,
    )
    decoded = BridgeCredentials.decode(unseal_bot_token(bot))
    assert decoded.bot_id == bot.id and decoded.password.get_secret_value() == config.token
    assert (
        decoded.webhook_secret is not None
        and decoded.webhook_secret.get_secret_value() == "callback-secret"
    )
    with pytest.raises(BadRequestError):
        ChannelBotService._check_imessage_reaction("imessage", "fire")
    ChannelBotService._check_imessage_reaction("imessage", "emphasize")


@pytest.mark.parametrize("change", ["server", "password"])
async def test_replacing_the_mac_also_revokes_its_old_callback_credential(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    org = uuid4()
    token = seal("bridge-password", scope=VaultScope.organization(org))
    callback = seal("callback-secret", scope=VaultScope.organization(org))
    bot = ChannelBot(
        id=uuid4(),
        organization_id=org,
        platform="imessage",
        name="Mac",
        token_encrypted=token.ciphertext,
        webhook_secret_encrypted=callback.ciphertext,
        secret_key_version=token.key_version,
        api_base_url="https://old-mac.example.com",
    )
    service = ChannelBotService(AsyncMock(), organization_id=org)
    monkeypatch.setattr(service, "get", AsyncMock(return_value=bot))
    monkeypatch.setattr(service, "_check_transcription", AsyncMock())
    monkeypatch.setattr(bots.discord_role_mapping_repo, "list_for_bot", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_reopen_stream", lambda _bot: None)
    write = AsyncMock(return_value=bot)
    monkeypatch.setattr(bots.channel_bot_repo, "update", write)
    patch = (
        ChannelBotUpdate(api_base_url="https://new-mac.example.com")
        if change == "server"
        else ChannelBotUpdate(token="new-bridge-password")
    )
    await service.update(
        bot.id, patch, AuthContext(user_id=uuid4(), organization_id=org, role="owner")
    )
    fields = write.await_args.kwargs["update_data"]
    assert "authorization_generation" in fields
    replacement = unseal(
        fields["webhook_secret_encrypted"],
        scope=VaultScope.organization(org),
        key_version=token.key_version,
    )
    assert replacement != "callback-secret" and len(replacement) >= 32
