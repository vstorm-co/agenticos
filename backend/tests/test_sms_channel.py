"""SMS through Twilio (#2082): the signature, the transport and the webhook."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
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

pytestmark = [pytest.mark.anyio, pytest.mark.security]

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


class _Redis:
    """The few Redis calls the prompt store makes, in memory."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self.data[key] = value
        if ttl is not None:
            self.ttl[key] = ttl
        return True

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)

    async def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)


@pytest.fixture
def prompts() -> _Redis:
    from app.services.channels import sms_prompts

    redis = _Redis()
    sms_prompts.configure(redis)  # type: ignore[arg-type]
    yield redis
    sms_prompts.configure(None)


class TestNumberedAnswers:
    async def test_a_digit_that_fits_names_the_choice_and_leaves_the_prompt_open(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import sms_prompts

        await sms_prompts.remember("bot", "+1555", ["aos:a:1", "aos:a:2"], start=1)

        assert await sms_prompts.answer("bot", "+1555", " 2 ") == "aos:a:2"
        assert await sms_prompts.answer("bot", "+1555", "1") == "aos:a:1", "a multi-select goes on"
        assert prompts.ttl["channel:sms:prompt:bot:+1555"] == sms_prompts.TTL_SECONDS

    @pytest.mark.parametrize("reply", ["3", "0", "12", "yes", "", "1 please"])
    async def test_anything_that_does_not_fit_is_an_ordinary_message(
        self, prompts: _Redis, reply: str
    ) -> None:
        from app.services.channels import sms_prompts

        await sms_prompts.remember("bot", "+1555", ["aos:a:1", "aos:a:2"], start=1)

        assert await sms_prompts.answer("bot", "+1555", reply) is None
        assert await sms_prompts.answer("bot", "+1555", "1") == "aos:a:1", (
            "the prompt is still open"
        )

    async def test_nothing_pending_or_nowhere_to_keep_it_is_never_an_answer(self) -> None:
        from app.services.channels import sms_prompts

        sms_prompts.configure(None)
        await sms_prompts.remember("bot", "+1555", ["aos:a:1"], start=1)
        assert await sms_prompts.answer("bot", "+1555", "1") is None
        sms_prompts.configure(_Redis())  # type: ignore[arg-type]
        assert await sms_prompts.answer("bot", "+1555", "1") is None
        sms_prompts.configure(None)

    async def test_a_prompt_is_sent_as_numbered_lines_and_remembered(self, prompts: _Redis) -> None:
        from app.services.channels.base import ChannelChoice, PromptMessage

        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(201, json={})

        adapter = SmsAdapter(api="https://twilio.test")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await adapter.send_prompt(
            TOKEN,
            PromptMessage(
                platform_chat_id="+15559998888",
                text="Send the invoice?",
                choices=[ChannelChoice("Approve", "aos:a:0"), ChannelChoice("Deny", "aos:a:1")],
                bot_id="bot-1",
            ),
        )

        body = sent[0].content.decode()
        assert "1.+Approve" in body and "2.+Deny" in body and "Reply+with+the+number" in body
        assert prompts.data["channel:sms:prompt:bot-1:+15559998888"] == (
            '{"1": "aos:a:0", "2": "aos:a:1"}'
        )
        await adapter.aclose()

    async def test_a_second_prompt_carries_on_numbering_and_settling_one_keeps_the_other(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import sms_prompts
        from app.services.channels.base import ChannelChoice, PromptMessage

        bodies: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content.decode())
            return httpx.Response(201, json={})

        adapter = SmsAdapter(api="https://twilio.test")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        for prompt_id in ("a", "b"):
            await adapter.send_prompt(
                TOKEN,
                PromptMessage(
                    platform_chat_id="+1555",
                    text="Go?",
                    choices=[
                        ChannelChoice("Yes", f"aos:{prompt_id}:0"),
                        ChannelChoice("No", f"aos:{prompt_id}:1"),
                    ],
                    bot_id="bot",
                ),
            )

        assert "3.+Yes" in bodies[1] and "4.+No" in bodies[1]
        assert await sms_prompts.answer("bot", "+1555", "3") == "aos:b:0"
        await sms_prompts.settle("bot", "+1555", "aos:a:0")
        assert await sms_prompts.answer("bot", "+1555", "1") is None
        assert await sms_prompts.answer("bot", "+1555", "4") == "aos:b:1"
        await sms_prompts.settle("bot", "+1555", "aos:b:1")
        assert await sms_prompts.answer("bot", "+1555", "4") is None
        await sms_prompts.settle("bot", "+1555", "not-a-press")
        await adapter.aclose()

    async def test_a_prompt_that_failed_to_send_is_not_remembered(self, prompts: _Redis) -> None:
        from app.services.channels.base import ChannelChoice, PromptMessage

        adapter = SmsAdapter(api="https://twilio.test")
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(500, json={}))
        )
        with pytest.raises(Exception):  # noqa: B017
            await adapter.send_prompt(
                TOKEN,
                PromptMessage(
                    platform_chat_id="+1555",
                    text="Go?",
                    choices=[ChannelChoice("Yes", "aos:a:0")],
                    bot_id="bot",
                ),
            )

        assert prompts.data == {}
        await adapter.aclose()

    async def test_settling_with_nowhere_to_keep_prompts_is_harmless(self) -> None:
        from app.services.channels import sms_prompts

        sms_prompts.configure(None)
        await sms_prompts.settle("bot", "+1555", "aos:a:0")

    def test_a_replacement_token_is_held_to_the_same_shape(self) -> None:
        from app.core.exceptions import BadRequestError
        from app.services.channel_bot import ChannelBotService

        ChannelBotService._check_sms_token("sms", TOKEN)
        ChannelBotService._check_sms_token("telegram", "anything")
        with pytest.raises(BadRequestError, match="ACCOUNT_SID"):
            ChannelBotService._check_sms_token("sms", "just-a-token-that-is-long")

    def test_the_bot_says_where_to_paste_its_webhook(self) -> None:
        from datetime import UTC, datetime

        from app.schemas.channel_bot import ChannelBotRead

        def read(platform: str) -> ChannelBotRead:
            return ChannelBotRead.model_validate(
                {
                    "id": uuid4(),
                    "organization_id": uuid4(),
                    "platform": platform,
                    "name": "Bot",
                    "is_active": True,
                    "webhook_mode": True,
                    "webhook_url": None,
                    "created_at": datetime.now(UTC),
                    "access_policy": {},
                },
                from_attributes=True,
            )

        sms, other = read("sms"), read("telegram")
        assert sms.messaging_endpoint is not None
        assert sms.messaging_endpoint.endswith(f"/api/v1/sms/{sms.id}/webhook")
        assert other.messaging_endpoint is None

    async def test_a_digit_reply_to_a_prompt_is_a_press_not_a_message(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import sms_prompts

        bot = MagicMock(id=uuid4(), platform="sms")
        await sms_prompts.remember(str(bot.id), "+15559998888", ["aos:a:0", "aos:a:1"], start=1)
        params = {"From": "+15559998888", "Body": "2", "MessageSid": "SM9"}
        spawned: list[str] = []
        pressed = MagicMock()
        with (
            patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value=TOKEN),
            patch(
                "app.api.routes.v1.sms_webhook.spawn",
                side_effect=lambda coro, name: (spawned.append(name), coro.close()),
            ),
            patch(
                "app.api.routes.v1.sms_webhook.link_has_lapsed", new=AsyncMock(return_value=False)
            ),
            patch("app.api.routes.v1.sms_webhook.process_channel_press", new=pressed),
            patch("app.api.routes.v1.sms_webhook.process_channel_event", new=MagicMock()),
        ):
            async with _client(bot) as client:
                response = await client.post(
                    f"{settings.API_V1_STR}/sms/{bot.id}/webhook",
                    content=urlencode(params),
                    headers=_signed(bot.id, params),
                )

        assert response.status_code == 200 and spawned == [f"sms_press:{bot.id}"]
        press = pressed.call_args.args[0]
        assert (press.platform, press.value, press.platform_user_id) == (
            "sms",
            "aos:a:1",
            "+15559998888",
        )


class TestALinkedNumberExpires:
    def _identity(self, days_ago: int) -> SimpleNamespace:
        from datetime import UTC, datetime, timedelta

        return SimpleNamespace(
            updated_at=None, created_at=datetime.now(UTC) - timedelta(days=days_ago)
        )

    def test_only_an_old_sms_link_lapses(self) -> None:
        from app.services.channels.router import ChannelMessageRouter

        lapsed = ChannelMessageRouter._sms_link_lapsed
        assert lapsed("sms", self._identity(91))
        assert not lapsed("sms", self._identity(10))
        assert not lapsed("telegram", self._identity(900)), "a chat account is not a phone number"

    def test_a_deployment_may_keep_links_for_ever_and_an_unstamped_one_is_not_old(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.channels import router
        from app.services.channels.router import ChannelMessageRouter

        monkeypatch.setattr(router.settings, "SMS_LINK_MAX_AGE_DAYS", 0)
        assert not ChannelMessageRouter._sms_link_lapsed("sms", self._identity(5000))
        monkeypatch.setattr(router.settings, "SMS_LINK_MAX_AGE_DAYS", 90)
        assert not ChannelMessageRouter._sms_link_lapsed(
            "sms", SimpleNamespace(updated_at=None, created_at=None)
        )

    async def test_a_lapsed_number_is_unlinked_before_anything_runs_as_its_old_person(self) -> None:
        from app.services.channels import router
        from app.services.channels.router import ChannelMessageRouter

        identity = SimpleNamespace(**vars(self._identity(200)), user_id=uuid4())

        async def unlink(db, *, db_identity, update_data):
            for key, value in update_data.items():
                setattr(db_identity, key, value)

        updated = AsyncMock(side_effect=unlink)
        with (
            patch.object(
                router.channel_identity_repo, "get_or_create", new=AsyncMock(return_value=identity)
            ),
            patch.object(router.channel_identity_repo, "update", new=updated),
            patch.object(ChannelMessageRouter, "_link_vouched", new=AsyncMock()) as vouched,
        ):
            incoming = SimpleNamespace(
                platform="sms",
                platform_user_id="+1",
                platform_username=None,
                platform_display_name=None,
            )
            await ChannelMessageRouter()._resolve_identity(incoming, MagicMock(), object())  # type: ignore[arg-type]

        assert updated.await_args.kwargs["update_data"] == {"user_id": None}
        assert identity.user_id is None and vouched.await_count == 1


class TestAChangedOwnerStartsAgain:
    async def test_a_private_chat_whose_conversation_belongs_to_somebody_else_is_rotated(
        self,
    ) -> None:
        from app.services.channels import router
        from app.services.channels.router import ChannelMessageRouter

        old, new = uuid4(), uuid4()
        incoming = SimpleNamespace(chat_type="private")
        identity = SimpleNamespace(user_id=new)
        with patch.object(router.conversation_repo, "get_owner", new=AsyncMock(return_value=old)):
            assert await ChannelMessageRouter._owner_changed(
                SimpleNamespace(conversation_id=uuid4()),
                incoming,
                identity,
                object(),  # type: ignore[arg-type]
            )
        with patch.object(router.conversation_repo, "get_owner", new=AsyncMock(return_value=new)):
            assert not await ChannelMessageRouter._owner_changed(
                SimpleNamespace(conversation_id=uuid4()),
                incoming,
                identity,
                object(),  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        ("chat_type", "user"), [("group", uuid4()), ("private", None)], ids=["a-room", "unlinked"]
    )
    async def test_a_room_and_an_unlinked_sender_are_never_rotated(self, chat_type, user) -> None:
        from app.services.channels.router import ChannelMessageRouter

        assert not await ChannelMessageRouter._owner_changed(
            SimpleNamespace(conversation_id=uuid4()),
            SimpleNamespace(chat_type=chat_type),
            SimpleNamespace(user_id=user),
            object(),  # type: ignore[arg-type]
        )

    async def test_a_session_of_a_missing_conversation_is_left_alone(self) -> None:
        from app.services.channels import router
        from app.services.channels.router import ChannelMessageRouter

        with patch.object(router.conversation_repo, "get_owner", new=AsyncMock(return_value=None)):
            assert not await ChannelMessageRouter._owner_changed(
                SimpleNamespace(conversation_id=uuid4()),
                SimpleNamespace(chat_type="private"),
                SimpleNamespace(user_id=uuid4()),
                object(),  # type: ignore[arg-type]
            )

    async def test_the_session_is_moved_to_a_fresh_conversation_and_pending_prompts_go(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import router, sms_prompts
        from app.services.channels.router import ChannelMessageRouter

        bot = SimpleNamespace(id=uuid4(), organization_id=uuid4())
        incoming = SimpleNamespace(platform_chat_id="+1555", chat_type="private", platform="sms")
        identity = SimpleNamespace(id=uuid4(), user_id=uuid4())
        session = SimpleNamespace(conversation_id=uuid4())
        fresh = uuid4()
        await sms_prompts.remember(str(bot.id), "+1555", ["aos:a:1"], start=1)
        updated = AsyncMock(return_value="rotated")
        with (
            patch.object(
                router.channel_session_repo,
                "get_by_bot_and_chat",
                new=AsyncMock(return_value=session),
            ),
            patch.object(ChannelMessageRouter, "_owner_changed", new=AsyncMock(return_value=True)),
            patch.object(
                ChannelMessageRouter, "_first_conversation", new=AsyncMock(return_value=fresh)
            ),
            patch.object(router.channel_session_repo, "update", new=updated),
            patch.object(
                router.channel_session_repo, "touch", new=AsyncMock(side_effect=lambda db, s: s)
            ),
        ):
            result = await ChannelMessageRouter()._resolve_session(
                incoming, bot, identity, object()
            )  # type: ignore[arg-type]

        assert result == "rotated"
        assert updated.await_args.kwargs["update_data"] == {
            "identity_id": identity.id,
            "conversation_id": fresh,
        }
        assert await sms_prompts.answer(str(bot.id), "+1555", "1") is None


class TestASettledPromptIsForgotten:
    async def test_settling_ends_it_and_a_later_digit_is_a_message_again(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import sms_prompts
        from app.services.channels.base import IncomingPress

        await sms_prompts.remember("bot", "+1555", ["aos:a:1"], start=1)
        press = IncomingPress(
            platform="sms",
            bot_id="bot",
            platform_user_id="+1555",
            platform_chat_id="+1555",
            value="aos:a:1",
        )

        await SmsAdapter().settle_prompt(TOKEN, press, "Approved")

        assert await sms_prompts.answer("bot", "+1555", "1") is None

    async def test_forgetting_with_nowhere_to_keep_prompts_is_harmless(self) -> None:
        from app.services.channels import sms_prompts

        sms_prompts.configure(None)
        await sms_prompts.forget("bot", "+1555")

    async def test_a_digit_after_the_link_lapsed_is_a_message_not_a_press(
        self, prompts: _Redis
    ) -> None:
        from app.services.channels import sms_prompts

        bot = MagicMock(id=uuid4(), platform="sms")
        await sms_prompts.remember(str(bot.id), "+15559998888", ["aos:a:0"], start=1)
        params = {"From": "+15559998888", "Body": "1", "MessageSid": "SM9"}
        spawned: list[str] = []
        with (
            patch("app.api.routes.v1.sms_webhook.unseal_bot_token", return_value=TOKEN),
            patch(
                "app.api.routes.v1.sms_webhook.link_has_lapsed", new=AsyncMock(return_value=True)
            ),
            patch(
                "app.api.routes.v1.sms_webhook.spawn",
                side_effect=lambda coro, name: (spawned.append(name), coro.close()),
            ),
            patch("app.api.routes.v1.sms_webhook.process_channel_press", new=MagicMock()),
            patch("app.api.routes.v1.sms_webhook.process_channel_event", new=MagicMock()),
        ):
            async with _client(bot) as client:
                response = await client.post(
                    f"{settings.API_V1_STR}/sms/{bot.id}/webhook",
                    content=urlencode(params),
                    headers=_signed(bot.id, params),
                )

        assert response.status_code == 200 and spawned == [f"sms_event:{bot.id}"]
        assert await sms_prompts.answer(str(bot.id), "+15559998888", "1") is None

    async def test_the_lapse_check_reads_the_numbers_identity(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.services.channels import sms_links

        @asynccontextmanager
        async def session():
            yield object()

        old = SimpleNamespace(updated_at=None, created_at=datetime.now(UTC) - timedelta(days=500))
        for found, expected in ((old, True), (None, False)):
            with (
                patch.object(sms_links, "get_db_context", session),
                patch.object(
                    sms_links.channel_identity_repo,
                    "get_by_platform_user",
                    new=AsyncMock(return_value=found),
                ),
            ):
                assert await sms_links.link_has_lapsed("+1555") is expected
