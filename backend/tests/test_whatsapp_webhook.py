"""The WhatsApp webhook: Meta's handshake, the signature, and what reaches the router (#2076).

The route functions are called directly, with the inbound service and the bot service
stubbed, as `test_teams_channel.py` does; what the signature check itself accepts is
`test_whatsapp_payload.py`, and what the inbound service does with a batch is
`test_whatsapp_inbound.py`.
"""

import asyncio
import enum
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.v1.whatsapp_webhook import MAX_BODY_BYTES, whatsapp_events, whatsapp_verify
from app.services.channels import dedupe
from app.services.channels.attachments import ChannelAttachmentService
from app.services.channels.base import IncomingMessage
from app.services.channels.mentions import AnsweredTurn, UnaddressedMessage
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.whatsapp import WhatsAppAdapter
from app.services.channels.whatsapp_graph import WhatsAppCredentials, WhatsAppGraphError
from app.services.channels.whatsapp_payload import parse_webhook, to_event
from app.worker.background.channel import process_channel_events_in_order
from tests.test_whatsapp_payload import FIXTURES
from tests.whatsapp_fakes import OpenWindow

pytestmark = pytest.mark.anyio

ROUTE = "app.api.routes.v1.whatsapp_webhook"


class _Sentinel(enum.Enum):
    SIGNED = enum.auto()


_SIGNED = _Sentinel.SIGNED
APP_SECRET = "meta-app-secret"
VERIFY_TOKEN = "the-verify-token"
ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
PHONE = "4915112345678"


def _bot(**overrides: Any) -> MagicMock:
    bot = MagicMock(
        id=uuid.uuid4(),
        organization_id=ORG,
        platform="whatsapp",
        whatsapp_phone_number_id="PNID1",
        whatsapp_account_id="WABA1",
        is_active=True,
    )
    for field, value in overrides.items():
        setattr(bot, field, value)
    return bot


def _payload(name: str = "text", *, ages: list[int] | None = None) -> dict[str, Any]:
    """A fixture whose messages are `ages` seconds old, in order; each defaults to five."""
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    now = int(time.time())
    for entry in payload["entry"]:
        for change in entry["changes"]:
            messages = change["value"].get("messages", [])
            for index, message in enumerate(messages):
                age = ages[index] if ages else 5
                message["timestamp"] = str(now - age)
    return payload


def _sign(body: bytes, key: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def _service(bot: MagicMock | None) -> MagicMock:
    return MagicMock(find_active=AsyncMock(return_value=bot))


async def _chunks(raw: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    for start in range(0, len(raw), size):
        yield raw[start : start + size]


def _request(raw: bytes, headers: dict[str, str]) -> MagicMock:
    request = MagicMock(headers=headers)
    request.stream = lambda: _chunks(raw)
    return request


async def _post(
    body: bytes | dict[str, Any],
    *,
    bot: MagicMock | None = None,
    signature: str | _Sentinel | None = _SIGNED,
    secret: str | None = APP_SECRET,
    headers: dict[str, str] | None = None,
    inbound: MagicMock | None = None,
) -> tuple[Any, MagicMock]:
    """Call the route as Meta would; `signature` defaults to a valid one, `None` sends none."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    sent = (
        {}
        if signature is None
        else {"x-hub-signature-256": _sign(raw) if signature is _Sentinel.SIGNED else signature}
    )
    request = _request(raw, {**sent, **(headers or {})})
    inbound = inbound if inbound is not None else _inbound()
    with patch(f"{ROUTE}.unseal_webhook_secret", return_value=secret):
        answered = await whatsapp_events(
            bot.id if bot else uuid.uuid4(), request, _service(bot), inbound
        )
    return answered, inbound


def _inbound() -> MagicMock:
    return MagicMock(receive=AsyncMock())


def _incoming(payload: dict[str, Any], bot: MagicMock, index: int = 0) -> IncomingMessage:
    """What the router is handed for the payload's message `index`."""
    parsed = parse_webhook(
        payload, phone_number_id="PNID1", account_id="WABA1", now=datetime.now(UTC)
    )
    event = to_event(parsed.messages[index], bot_id=str(bot.id), organization_id=ORG)
    assert isinstance(event, IncomingMessage)
    return event


class TestTheHandshake:
    async def _verify(self, query: dict[str, str], bot: MagicMock | None) -> Any:
        request = MagicMock(query_params=query)
        with patch(f"{ROUTE}.unseal_whatsapp_verify_token", return_value=VERIFY_TOKEN):
            return await whatsapp_verify(uuid.uuid4(), request, _service(bot))

    async def test_the_handshake_echoes_the_challenge_as_plain_text(self):
        answered = await self._verify(
            {
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "1158201444",
            },
            _bot(),
        )

        assert answered.body == b"1158201444"
        assert answered.media_type == "text/plain"

    @pytest.mark.parametrize(
        "query",
        [
            {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
            {"hub.mode": "subscribe", "hub.challenge": "1"},
            {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"},
            {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN},
        ],
    )
    async def test_a_wrong_verify_token_is_refused(self, query):
        with pytest.raises(HTTPException) as refused:
            await self._verify(query, _bot())

        assert refused.value.status_code == 403

    async def test_the_handshake_for_another_platforms_bot_is_refused(self):
        query = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"}

        for bot in (_bot(platform="teams"), None, _bot(is_active=False)):
            with pytest.raises(HTTPException) as refused:
                await self._verify(query, None if bot is None or not bot.is_active else bot)
            assert refused.value.status_code == 403

    async def test_a_bot_with_no_verify_token_refuses_an_empty_one(self):
        request = MagicMock(
            query_params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}
        )
        for stored in (None, ""):
            with (
                patch(f"{ROUTE}.unseal_whatsapp_verify_token", return_value=stored),
                pytest.raises(HTTPException) as refused,
            ):
                await whatsapp_verify(uuid.uuid4(), request, _service(_bot()))
            assert refused.value.status_code == 403


class TestRefusals:
    async def test_an_unknown_or_inactive_bot_gets_200_and_nothing_runs(self):
        answered, inbound = await _post(_payload(), bot=None)

        assert answered.status_code == 200
        inbound.receive.assert_not_awaited()

    async def test_a_bot_of_another_platform_or_without_its_number_is_refused(self):
        for bot in (
            _bot(platform="teams"),
            _bot(whatsapp_phone_number_id=None),
            _bot(whatsapp_account_id=None),
        ):
            with pytest.raises(HTTPException) as refused:
                await _post(_payload(), bot=bot)
            assert refused.value.status_code == 403

    @pytest.mark.security
    @pytest.mark.parametrize("signature", [None, "sha256=" + "0" * 64, "nonsense"])
    async def test_a_bad_or_missing_signature_is_401_and_nothing_is_parsed_or_spawned(
        self, signature, caplog
    ):
        bot = _bot()
        inbound = _inbound()
        with (
            caplog.at_level("WARNING"),
            patch(f"{ROUTE}.parse_webhook") as parse,
            pytest.raises(HTTPException) as refused,
        ):
            await _post(_payload(), bot=bot, signature=signature, inbound=inbound)

        assert refused.value.status_code == 401
        parse.assert_not_called()
        inbound.receive.assert_not_awaited()
        assert [r.message for r in caplog.records] == ["whatsapp_signature_refused"]
        assert caplog.records[0].bot_id == str(bot.id)

    @pytest.mark.security
    @pytest.mark.parametrize("secret", [None, ""])
    async def test_a_bot_without_an_app_secret_refuses_every_post(self, secret):
        """An HMAC under an empty key is computable by anyone, so it is never tried."""
        body = json.dumps(_payload()).encode()
        for forged in (_sign(body, ""), _sign(body, "anything"), None):
            with pytest.raises(HTTPException) as refused:
                await _post(body, bot=_bot(), secret=secret, signature=forged)
            assert refused.value.status_code == 401

    @pytest.mark.security
    async def test_a_body_signed_with_the_verify_token_is_refused(self):
        body = json.dumps(_payload()).encode()

        with pytest.raises(HTTPException) as refused:
            await _post(body, bot=_bot(), signature=_sign(body, VERIFY_TOKEN))

        assert refused.value.status_code == 401

    @pytest.mark.security
    async def test_an_oversized_body_is_refused_before_verification(self):
        for headers, body in (
            ({"content-length": str(MAX_BODY_BYTES + 1)}, b"{}"),
            # No declared length: a chunked body is measured as it arrives.
            ({}, b" " * (MAX_BODY_BYTES + 1)),
        ):
            service = _service(_bot())
            request = _request(body, headers)
            inbound = _inbound()
            with (
                patch(f"{ROUTE}.verify_signature") as verify,
                pytest.raises(HTTPException) as refused,
            ):
                await whatsapp_events(uuid.uuid4(), request, service, inbound)

            assert refused.value.status_code == 413
            verify.assert_not_called()
            service.find_active.assert_not_awaited()
            inbound.receive.assert_not_awaited()

    @pytest.mark.security
    async def test_a_chunked_body_is_never_buffered_past_the_limit(self):
        read = 0

        async def endless() -> AsyncIterator[bytes]:
            nonlocal read
            while True:
                read += 1
                yield b" " * 1_000_000

        request = MagicMock(headers={})
        request.stream = endless
        with pytest.raises(HTTPException) as refused:
            await whatsapp_events(uuid.uuid4(), request, _service(_bot()), _inbound())

        assert refused.value.status_code == 413
        assert read <= MAX_BODY_BYTES // 1_000_000 + 1

    async def test_a_content_length_that_is_not_a_number_is_read_and_measured(self):
        answered, inbound = await _post(_payload(), bot=_bot(), headers={"content-length": "lots"})

        assert answered.status_code == 200
        inbound.receive.assert_awaited_once()

    @pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"'])
    async def test_a_signed_body_that_is_not_an_object_is_a_400(self, body):
        with pytest.raises(HTTPException) as refused:
            await _post(body, bot=_bot())

        assert refused.value.status_code == 400


class TestMessages:
    async def test_the_route_hands_the_parsed_batch_to_the_customer_record(self):
        bot = _bot()
        answered, inbound = await _post(_payload(), bot=bot)

        assert answered.status_code == 200
        inbound.receive.assert_awaited_once()
        received_bot, parsed = inbound.receive.await_args.args
        assert received_bot is bot
        assert parsed.messages[0].wamid == "wamid.A1"

    @pytest.mark.security
    async def test_a_bad_signature_records_no_customer(self):
        inbound = _inbound()
        with pytest.raises(HTTPException) as refused:
            await _post(_payload(), bot=_bot(), signature="sha256=" + "0" * 64, inbound=inbound)

        assert refused.value.status_code == 401
        inbound.receive.assert_not_awaited()

    async def test_events_are_awaited_one_after_another(self):
        order: list[str] = []

        async def process(event: IncomingMessage) -> None:
            order.append(f"start {event.text}")
            await asyncio.sleep(0.01 if event.text == "first" else 0)
            order.append(f"end {event.text}")

        events = [
            IncomingMessage("whatsapp", "b", "u", "c", "private", text=text)
            for text in ("first", "second")
        ]
        with patch("app.worker.background.channel.process_channel_event", process):
            await process_channel_events_in_order(events)

        assert order == ["start first", "end first", "start second", "end second"]

    async def test_an_image_that_cannot_be_fetched_is_answered_by_name(self):
        """Meta refuses the media lookup: the image still reaches the router, which says so."""
        bot = _bot()
        incoming = _incoming(_payload("image"), bot)
        assert [a.filename for a in incoming.attachments] == ["image.jpg"]

        graph = MagicMock(
            send_text=AsyncMock(),
            mark_read=AsyncMock(),
            media_info=AsyncMock(side_effect=WhatsAppGraphError(code=100)),
            aclose=AsyncMock(),
        )
        adapter = WhatsAppAdapter(graph, window=OpenWindow())
        creds = WhatsAppCredentials(bot_id=str(bot.id), access_token="t", phone_number_id="PNID1")
        row = MagicMock(
            id=uuid.uuid4(),
            organization_id=ORG,
            is_active=True,
            access_policy={},
            api_base_url=None,
        )
        answered = AnsweredTurn(text="answered")
        agents = MagicMock(
            answer=AsyncMock(side_effect=UnaddressedMessage),
            answer_default=AsyncMock(return_value=answered),
        )

        service = ChannelAttachmentService(MagicMock())
        service.uploads = MagicMock(validate_upload=lambda *a, **k: (True, None))
        router = "app.services.channels.router"
        with (
            patch(f"{router}.get_adapter", return_value=adapter),
            patch(f"{router}.unseal_bot_token", return_value=creds.encode()),
            patch(f"{router}.channel_bot_repo.get_for_inbound", AsyncMock(return_value=row)),
            patch(
                f"{router}.WorkflowExposureService.receive_channel_message",
                AsyncMock(return_value=False),
            ),
            patch(
                f"{router}.channel_identity_repo.get_by_platform_user",
                AsyncMock(return_value=MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4())),
            ),
            patch(
                f"{router}.channel_session_repo.get_by_bot_and_chat",
                AsyncMock(return_value=MagicMock(conversation_id=uuid.uuid4(), turn_count=1)),
            ),
            patch(
                f"{router}.ChannelLinkService.complete_with_code", AsyncMock(return_value="none")
            ),
            patch(f"{router}.channel_session_repo.touch", AsyncMock()),
            patch(
                f"{router}.conversation_repo.get_messages_by_conversation",
                AsyncMock(return_value=[]),
            ),
            patch(f"{router}.conversation_repo.count_messages", AsyncMock(return_value=0)),
            patch(
                f"{router}.ConversationService",
                return_value=MagicMock(model_history=AsyncMock(return_value=[])),
            ),
            patch(f"{router}.ChannelAgentRouter", return_value=agents),
            patch(f"{router}.ChannelAttachmentService", return_value=service),
            patch(f"{router}.ChannelPrompts.reply", AsyncMock(return_value=False)),
            patch(f"{router}.member_repo.get_active", AsyncMock(return_value=MagicMock())),
        ):
            await ChannelMessageRouter()._route_inner(incoming, MagicMock())
        await adapter.aclose()

        texts = [c.kwargs["body"] for c in graph.send_text.await_args_list]
        assert any("image.jpg: could not be downloaded." in t for t in texts), texts

    async def test_a_redelivered_message_runs_once(self):
        class Redis:
            def __init__(self) -> None:
                self.store: set[str] = set()

            async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False):
                if nx and key in self.store:
                    return False
                self.store.add(key)
                return True

            async def delete(self, key: str) -> int:
                self.store.discard(key)
                return 1

        incoming = _incoming(_payload(), _bot())

        inner = AsyncMock()
        dedupe.configure(Redis())  # type: ignore[arg-type]
        try:
            with patch.object(ChannelMessageRouter, "_route_inner", inner):
                await ChannelMessageRouter().route(incoming, AsyncMock())
                await ChannelMessageRouter().route(incoming, AsyncMock())
        finally:
            dedupe.configure(None)

        inner.assert_awaited_once()

    async def test_statuses_are_acknowledged_and_never_run(self, caplog):
        bot = _bot()
        with caplog.at_level("INFO"):
            answered, inbound = await _post(_payload("statuses"), bot=bot)

        assert answered.status_code == 200
        inbound.receive.assert_awaited_once()
        assert inbound.receive.await_args.args[1].messages == ()
        failed = [r for r in caplog.records if r.message == "whatsapp_status_failed"]
        assert [(r.bot_id, r.status, r.codes) for r in failed] == [
            (str(bot.id), "failed", [131047])
        ]
        assert not any(hasattr(r, "wamid") for r in failed)

    async def test_another_numbers_changes_are_ignored(self, caplog):
        with caplog.at_level("INFO"):
            answered, inbound = await _post(
                _payload("text"), bot=_bot(whatsapp_phone_number_id="OTHER")
            )

        assert answered.status_code == 200
        assert inbound.receive.await_args.args[1].messages == ()
        dropped = [r for r in caplog.records if r.message == "whatsapp_webhook_dropped"]
        assert dropped[0].levelname == "WARNING" and dropped[0].foreign == 1

    async def test_stale_and_ignored_messages_are_counted_at_info(self, caplog):
        payload = _payload("text", ages=[8 * 24 * 3600])
        with caplog.at_level("INFO"):
            answered, inbound = await _post(payload, bot=_bot())

        assert answered.status_code == 200
        assert inbound.receive.await_args.args[1].messages == ()
        (dropped,) = [r for r in caplog.records if r.message == "whatsapp_webhook_dropped"]
        assert dropped.levelname == "INFO" and dropped.stale == 1


class TestHygiene:
    async def test_a_failed_status_logs_neither_its_wamid_nor_the_number_inside_it(self, caplog):
        """A wamid is base64 of ids that include the customer's phone number."""
        wamid = "wamid.HBgLMTY1MDUwNzY1MjAVAgARGBI5QTNDQTVCM0Q0Q0Q2RTY3RTcA"
        payload = _payload("statuses")
        payload["entry"][0]["changes"][0]["value"]["statuses"][1]["id"] = wamid

        with caplog.at_level("DEBUG"):
            await _post(payload, bot=_bot())

        assert any(r.message == "whatsapp_status_failed" for r in caplog.records)
        logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
        assert wamid not in logged and wamid.removeprefix("wamid.") not in logged
        assert "16505076520" not in logged

    async def test_nothing_logged_contains_the_phone_number(self, caplog):
        payload = _payload("text")
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = PHONE
        payload["entry"][0]["changes"].append(
            {**payload["entry"][0]["changes"][0], "value": {"metadata": {"phone_number_id": "X"}}}
        )
        incoming = _incoming(payload, _bot())
        with caplog.at_level("DEBUG"):
            await _post(payload, bot=_bot())
            await _post(payload, bot=_bot(whatsapp_phone_number_id="OTHER"))
            with pytest.raises(HTTPException):
                await _post(payload, bot=_bot(), signature=None)

        logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
        assert PHONE not in logged
        assert PHONE not in repr(incoming)
