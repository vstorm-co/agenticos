"""SMS through Twilio (#2082): the signature, the transport and the webhook."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app
from app.services.channels import get_adapter, inbound_webhook_url, register_adapter
from app.services.channels.base import OutgoingMessage
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.sms import (
    MAX_CHARS,
    MORE_IN_THE_APP,
    SIGNATURE_HEADER,
    SIGNED_URL_HEADER,
    SmsAdapter,
    fit_to_sms,
    plain,
    split_credentials,
    twilio_signature,
)

pytestmark = pytest.mark.anyio

TOKEN = "AC123:secret-token:+15550001111"
VECTOR_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
VECTOR = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675309",
    "Digits": "1234",
    "From": "+14158675309",
    "To": "+18005551212",
}


def test_the_signature_is_twilios_published_one() -> None:
    assert twilio_signature(VECTOR_URL, VECTOR, "12345") == "RSOYDt4T1cUTdK1PDd93/VVr8B8="


class TestCredentials:
    def test_a_token_is_account_secret_and_number(self) -> None:
        assert split_credentials(TOKEN) == ("AC123", "secret-token", "+15550001111")

    @pytest.mark.parametrize(
        "token",
        ["only-one", "AC1:two", "AC1:tok:15550001111", "XX1:tok:+1555", "AC1::+1555", "AC1:a:b:+1"],
    )
    def test_anything_else_is_a_configuration_error(self, token: str) -> None:
        with pytest.raises(ChannelNotConfigured):
            split_credentials(token)


class TestTheTextSent:
    def test_markdown_becomes_what_a_phone_shows(self) -> None:
        assert plain("**Done**\n# Title\n> quoted\nSee [the invoice](https://x.io/i) `now`") == (
            "Done\nTitle\nquoted\nSee the invoice (https://x.io/i) now"
        )

    def test_a_short_answer_is_untouched_and_a_long_one_says_where_the_rest_is(self) -> None:
        assert fit_to_sms("  Yes.  ") == "Yes."
        long = fit_to_sms("a" * (MAX_CHARS * 2))
        assert len(long) == MAX_CHARS and long.endswith(MORE_IN_THE_APP)


class TestTheAdapter:
    def _adapter(self, handler) -> SmsAdapter:
        adapter = SmsAdapter(api="https://twilio.test")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return adapter

    async def test_a_reply_is_one_authenticated_post_from_the_bots_number(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json={})

        adapter = self._adapter(handler)
        await adapter.send_message(
            TOKEN, OutgoingMessage(platform_chat_id="+15559998888", text="**Hi**")
        )

        request = seen[0]
        assert str(request.url) == "https://twilio.test/2010-04-01/Accounts/AC123/Messages.json"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.content.decode() == urlencode(
            {"To": "+15559998888", "From": "+15550001111", "Body": "Hi"}
        )
        await adapter.aclose()

    async def test_nothing_is_sent_for_an_empty_answer_and_a_refusal_is_raised(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(401, json={})

        adapter = self._adapter(handler)
        await adapter.send_message(TOKEN, OutgoingMessage(platform_chat_id="+1", text="   "))
        assert calls == []
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.send_message(TOKEN, OutgoingMessage(platform_chat_id="+1", text="hi"))
        await adapter.aclose()

    async def test_there_is_nothing_to_poll_and_the_webhook_is_the_operators_to_paste(self) -> None:
        adapter = SmsAdapter()
        await adapter.start_polling("b", TOKEN)
        await adapter.stop_polling("b")
        assert await adapter.register_webhook(TOKEN, "https://x/hook", None) is True
        assert await adapter.delete_webhook(TOKEN) is True
        await adapter.aclose()

    def test_only_twilios_signature_over_the_signed_url_verifies(self) -> None:
        adapter = SmsAdapter()
        body = urlencode(VECTOR)
        good = {SIGNATURE_HEADER: "RSOYDt4T1cUTdK1PDd93/VVr8B8=", SIGNED_URL_HEADER: VECTOR_URL}

        assert adapter.verify_webhook_signature(good, "12345", body)
        assert not adapter.verify_webhook_signature(good, "wrong-token", body)
        assert not adapter.verify_webhook_signature(good, "12345", body + "&extra=1")
        assert not adapter.verify_webhook_signature({**good, SIGNATURE_HEADER: ""}, "12345", body)
        assert not adapter.verify_webhook_signature({SIGNATURE_HEADER: "x"}, "12345", body)
        assert not adapter.verify_webhook_signature(good, "12345", None)

    def test_a_text_is_a_private_message_from_its_number_and_an_empty_one_is_nothing(self) -> None:
        adapter = SmsAdapter()
        incoming = adapter.parse_incoming(
            {"From": "+15559998888", "Body": " hello ", "MessageSid": "SM1"}, "bot-1"
        )

        assert incoming is not None
        assert (incoming.platform, incoming.bot_id, incoming.chat_type) == (
            "sms",
            "bot-1",
            "private",
        )
        assert incoming.platform_user_id == incoming.platform_chat_id == "+15559998888"
        assert incoming.text == "hello" and incoming.message_id == "SM1" and incoming.addressed
        assert adapter.parse_incoming({"From": "+1", "Body": "  "}, "b") is None
        assert adapter.parse_incoming({"Body": "hi"}, "b") is None
        assert adapter.parse_incoming({"From": "+1", "Body": "hi"}, "b").message_id is None  # type: ignore[union-attr]


def test_the_receiver_is_where_the_registry_says() -> None:
    bot_id = uuid4()

    assert inbound_webhook_url("sms", bot_id).endswith(f"/api/v1/sms/{bot_id}/webhook")


@asynccontextmanager
async def _client(bot: object | None) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    register_adapter(SmsAdapter())
    try:
        with patch(
            "app.services.channel_bot.ChannelBotService.find_active",
            new=AsyncMock(return_value=bot),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client
    finally:
        app.dependency_overrides.clear()


def _signed(bot_id: object, params: dict[str, str]) -> dict[str, str]:
    url = inbound_webhook_url("sms", bot_id)  # type: ignore[arg-type]
    return {
        SIGNATURE_HEADER: twilio_signature(url, params, "secret-token"),
        "content-type": "application/x-www-form-urlencoded",
    }


class TestTheWebhook:
    ROOT = f"{settings.API_V1_STR}/sms"

    def _bot(self, platform: str = "sms") -> MagicMock:
        return MagicMock(id=uuid4(), platform=platform)

    async def test_a_signed_text_is_acknowledged_and_handed_to_the_router(self) -> None:
        bot = self._bot()
        params = {"From": "+15559998888", "Body": "hello", "MessageSid": "SM1"}
        spawned: list[object] = []
        with (
            patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value=TOKEN),
            patch(
                "app.api.routes.v1.sms_webhook.spawn",
                side_effect=lambda coro, name: (spawned.append(name), coro.close()),
            ),
            patch("app.api.routes.v1.sms_webhook.process_channel_event", new=MagicMock()),
        ):
            async with _client(bot) as client:
                response = await client.post(
                    f"{self.ROOT}/{bot.id}/webhook",
                    content=urlencode(params),
                    headers=_signed(bot.id, params),
                )

        assert response.status_code == 200 and "<Response/>" in response.text
        assert response.headers["content-type"].startswith("text/xml")
        assert spawned == [f"sms_event:{bot.id}"]

    async def test_an_unsigned_or_wrongly_signed_text_is_refused_and_runs_nothing(self) -> None:
        bot = self._bot()
        params = {"From": "+15559998888", "Body": "hello"}
        with (
            patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value=TOKEN),
            patch("app.api.routes.v1.sms_webhook.spawn") as spawn,
        ):
            async with _client(bot) as client:
                forged = await client.post(
                    f"{self.ROOT}/{bot.id}/webhook",
                    content=urlencode(params),
                    headers={SIGNATURE_HEADER: "forged"},
                )
                unsigned = await client.post(
                    f"{self.ROOT}/{bot.id}/webhook", content=urlencode(params)
                )

        assert forged.status_code == 403 and unsigned.status_code == 403
        assert not spawn.called

    async def test_a_bot_whose_token_cannot_sign_refuses_rather_than_trusting(self) -> None:
        bot = self._bot()
        with patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value="not-a-token"):
            async with _client(bot) as client:
                response = await client.post(
                    f"{self.ROOT}/{bot.id}/webhook", content="From=%2B1&Body=x"
                )

        assert response.status_code == 403

    async def test_an_unknown_paused_or_other_platforms_bot_gets_an_empty_answer(self) -> None:
        async with _client(None) as client:
            missing = await client.post(
                f"{self.ROOT}/{uuid4()}/webhook", content="From=%2B1&Body=x"
            )
        async with _client(self._bot("telegram")) as client:
            other = await client.post(f"{self.ROOT}/{uuid4()}/webhook", content="From=%2B1&Body=x")

        assert missing.status_code == other.status_code == 200
        assert "<Response/>" in missing.text and "<Response/>" in other.text

    async def test_a_signed_empty_text_is_acknowledged_and_runs_nothing(self) -> None:
        bot = self._bot()
        params = {"From": "+15559998888", "Body": ""}
        with (
            patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value=TOKEN),
            patch("app.api.routes.v1.sms_webhook.spawn") as spawn,
        ):
            async with _client(bot) as client:
                response = await client.post(
                    f"{self.ROOT}/{bot.id}/webhook",
                    content=urlencode(params),
                    headers=_signed(bot.id, params),
                )

        assert response.status_code == 200 and not spawn.called


def test_the_adapter_is_the_one_registered_for_sms() -> None:
    register_adapter(SmsAdapter())

    assert isinstance(get_adapter("sms"), SmsAdapter)


class TestCreatingABot:
    def _data(self, **overrides: object) -> MagicMock:
        data = MagicMock(platform="sms", webhook_mode=True, token=TOKEN)
        for key, value in overrides.items():
            setattr(data, key, value)
        return data

    def test_an_sms_bot_is_webhook_only_with_a_token_that_can_sign_and_send(self) -> None:
        from app.core.exceptions import BadRequestError
        from app.services.channel_bot import ChannelBotService

        ChannelBotService._check_sms(self._data())
        ChannelBotService._check_sms(self._data(platform="telegram", webhook_mode=False, token="x"))
        with pytest.raises(BadRequestError, match="only by webhook"):
            ChannelBotService._check_sms(self._data(webhook_mode=False))
        with pytest.raises(BadRequestError, match="ACCOUNT_SID"):
            ChannelBotService._check_sms(self._data(token="just-a-token"))
