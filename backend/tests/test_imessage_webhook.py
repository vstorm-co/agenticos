"""Authenticate before reading and reuse the canonical channel handlers."""

import base64
import json
from collections.abc import AsyncIterator, Coroutine
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.models.channel_bot import ChannelBot
from app.services import imessage_webhook as receiver
from app.services.channels.imessage import ImessageAdapter

pytestmark = pytest.mark.anyio
_SECRET = "callback-secret"
_AUTH = "Basic " + base64.b64encode(f"agenticos:{_SECRET}".encode()).decode()


async def chunks(body: bytes) -> AsyncIterator[bytes]:
    yield body


def event(*, attachment: bool = False) -> bytes:
    return json.dumps(
        {
            "type": "new-message",
            "data": {
                "guid": "MESSAGE-GUID",
                "text": "7",
                "isFromMe": False,
                "handle": {"address": "ada@example.com"},
                "chats": [{"guid": "iMessage;-;ada@example.com"}],
                "attachments": [{"guid": "file", "transferName": "x.txt"}] if attachment else [],
            },
        }
    ).encode()


@pytest.fixture
def bot() -> ChannelBot:
    return ChannelBot(
        id=uuid4(),
        organization_id=uuid4(),
        platform="imessage",
        name="Mac",
        webhook_mode=True,
        is_active=True,
        token_encrypted="sealed",
        secret_key_version=1,
    )


@pytest.fixture
async def service(
    monkeypatch: pytest.MonkeyPatch,
    bot: ChannelBot,
) -> AsyncIterator[receiver.ImessageWebhookService]:
    monkeypatch.setattr(receiver.ChannelBotService, "find_active", AsyncMock(return_value=bot))
    monkeypatch.setattr(receiver, "unseal_webhook_secret", lambda _bot: _SECRET)
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    monkeypatch.setattr(receiver, "get_adapter", lambda _platform: adapter)
    async with AsyncSession() as db:
        yield receiver.ImessageWebhookService(db)
    await adapter.aclose()


@pytest.mark.parametrize("failure", ["unknown", "platform", "mode", "secret", "auth"])
async def test_bad_credentials_never_read_the_body(
    monkeypatch: pytest.MonkeyPatch,
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
    failure: str,
) -> None:
    if failure == "unknown":
        monkeypatch.setattr(receiver.ChannelBotService, "find_active", AsyncMock(return_value=None))
    elif failure == "platform":
        bot.platform = "slack"
    elif failure == "mode":
        bot.webhook_mode = False
    elif failure == "secret":
        monkeypatch.setattr(receiver, "unseal_webhook_secret", lambda _bot: None)
    read = False

    async def forbidden_body() -> AsyncIterator[bytes]:
        nonlocal read
        read = True
        yield b"private"

    with pytest.raises(AuthorizationError):
        await service.receive(bot.id, "forged" if failure == "auth" else _AUTH, forbidden_body())
    assert not read


@pytest.mark.parametrize("body", [b"no JSON", b"[]", b"null", b"x" * (256 * 1024 + 1)])
async def test_invalid_or_oversized_payload_is_refused(
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
    body: bytes,
) -> None:
    with pytest.raises(BadRequestError):
        await service.receive(bot.id, _AUTH, chunks(body))


async def test_stalled_body_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
) -> None:
    class Expired:
        async def __aenter__(self) -> None:
            raise TimeoutError

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(receiver.asyncio, "timeout", lambda _seconds: Expired())
    with pytest.raises(BadRequestError, match="timed out"):
        await service.receive(bot.id, _AUTH, chunks(b"{}"))


async def test_nonmessage_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Receipt must not start an agent")

    monkeypatch.setattr(receiver, "spawn_after_commit", forbidden)
    await service.receive(bot.id, _AUTH, chunks(b'{"type":"updated-message"}'))


async def test_mounted_receiver_uses_the_service_and_preserves_authentication(
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
) -> None:
    from app.api.deps import get_imessage_webhook_service
    from app.main import app

    app.dependency_overrides[get_imessage_webhook_service] = lambda: service
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            path = f"/api/v1/imessage/{bot.id}/webhook"
            refused = await client.post(path, json={"type": "updated-message"})
            assert refused.status_code == 403
            accepted = await client.post(
                path, headers={"authorization": _AUTH}, json={"type": "updated-message"}
            )
            assert accepted.status_code == 200 and accepted.content == b""
    finally:
        app.dependency_overrides.pop(get_imessage_webhook_service, None)


@pytest.mark.parametrize(
    "choice,attachment", [(None, False), ("aos:request:0", False), (None, True)]
)
async def test_messages_and_numbered_answers_use_existing_handlers_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    service: receiver.ImessageWebhookService,
    bot: ChannelBot,
    choice: str | None,
    attachment: bool,
) -> None:
    answer = AsyncMock(return_value=choice)
    message, press = AsyncMock(), AsyncMock()
    monkeypatch.setattr(receiver.sms_prompts, "answer", answer)
    monkeypatch.setattr(receiver, "process_channel_event", message)
    monkeypatch.setattr(receiver, "process_channel_press", press)
    pending: list[Coroutine[object, object, None]] = []

    def defer(_db: AsyncSession, coro: Coroutine[object, object, None], *, name: str) -> None:
        assert name.startswith("imessage_")
        pending.append(coro)

    monkeypatch.setattr(receiver, "spawn_after_commit", defer)
    await service.receive(bot.id, _AUTH, chunks(event(attachment=attachment)))
    assert len(pending) == 1
    message.assert_not_awaited()
    press.assert_not_awaited()
    await pending[0]
    if choice is not None:
        message.assert_not_called()
        sent = press.await_args.args[0]
        assert sent.value == choice and sent.platform == "imessage"
    else:
        press.assert_not_called()
        assert message.await_args.args[0].platform_user_id == "ada@example.com"
    if attachment:
        answer.assert_not_awaited()
    else:
        answer.assert_awaited_once_with(
            str(bot.id), "iMessage;-;ada@example.com", "7", platform="imessage"
        )


async def test_duplicate_numbered_reply_never_dispatches_another_toggle(service, monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr(receiver.sms_prompts, "answer", AsyncMock(return_value="question:choice"))
    monkeypatch.setattr(receiver, "claim_delivery", AsyncMock(return_value=False))
    monkeypatch.setattr(receiver, "spawn_after_commit", dispatch)
    await service.receive(uuid4(), _AUTH, chunks(event()))
    dispatch.assert_not_called()
