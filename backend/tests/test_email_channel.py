"""E-mail as a channel (#2082): the relay's signature, the transport, threading and prompts."""

import base64
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app
from app.services.channels import email_state, get_adapter, register_adapter, sms_prompts
from app.services.channels.base import (
    ChannelChoice,
    IncomingAttachment,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.email import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    EmailAdapter,
    is_address,
    reply_body,
    sign,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.email.providers.base import SendResult

pytestmark = [pytest.mark.anyio, pytest.mark.security]

BOT_ADDRESS = "Agent@Mail.Acme.com"
SECRET = "relay-secret-1234"


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)


@pytest.fixture
def redis() -> _Redis:
    store = _Redis()
    sms_prompts.configure(store)  # type: ignore[arg-type]
    email_state.configure(store)  # type: ignore[arg-type]
    yield store
    sms_prompts.configure(None)
    email_state.configure(None)


class _Provider:
    def __init__(self, *, delivers: bool = True, accepted: bool = True) -> None:
        self.delivers = delivers
        self.accepted = accepted
        self.sent: list = []

    async def send(self, message):
        self.sent.append(message)
        return SendResult(
            provider_message_id="m1", accepted=self.accepted, error=None if self.accepted else "no"
        )


@pytest.fixture
def provider():
    mail = _Provider()
    with patch("app.services.channels.email.get_email_provider", return_value=mail):
        yield mail


class TestWhatThePersonWrote:
    def test_quoted_history_and_attributions_are_cut(self) -> None:
        text = "Yes, do it.\n\nOn Tue, 3 Nov 2026, Agent <a@x.com> wrote:\n> Shall I send it?\n"

        assert reply_body(text) == "Yes, do it."
        assert reply_body("1\r\n> quoted") == "1"
        assert reply_body("Hi\n-----Original Message-----\nold") == "Hi"
        assert reply_body("From: Ada <a@x.com>\nSent: today") == ""

    @pytest.mark.parametrize(
        ("value", "valid"),
        [("ada@acme.com", True), (" ada@acme.com ", True), ("ada", False), ("a b@c.de", False)],
    )
    def test_an_address_is_one(self, value: str, valid: bool) -> None:
        assert is_address(value) is valid


class TestTheSignature:
    def _headers(self, body: str, *, secret: str = SECRET, at: float | None = None) -> dict:
        stamp = str(int(at if at is not None else time.time()))
        return {SIGNATURE_HEADER: sign(secret, stamp, body), TIMESTAMP_HEADER: stamp}

    def test_a_fresh_signed_body_verifies_and_anything_else_does_not(self) -> None:
        adapter = EmailAdapter()
        body = '{"from": "ada@acme.com"}'

        assert adapter.verify_webhook_signature(self._headers(body), SECRET, body)
        assert not adapter.verify_webhook_signature(self._headers(body), SECRET, body + " ")
        assert not adapter.verify_webhook_signature(
            self._headers(body, secret="other"), SECRET, body
        )
        assert not adapter.verify_webhook_signature({}, SECRET, body)
        assert not adapter.verify_webhook_signature(self._headers(body), SECRET, None)
        assert not adapter.verify_webhook_signature(
            {SIGNATURE_HEADER: "x", TIMESTAMP_HEADER: "soon"}, SECRET, body
        )

    def test_a_captured_request_cannot_be_replayed_later(self) -> None:
        body = "{}"
        stale = self._headers(body, at=time.time() - 3600)

        assert not EmailAdapter().verify_webhook_signature(stale, SECRET, body)


class TestParsing:
    def test_a_mail_is_a_private_message_from_its_lowercased_sender(self) -> None:
        payload = {
            "from": "Ada@Acme.com",
            "text": "Hello\n> old",
            "message_id": "<1@acme>",
            "attachments": [
                {"filename": "a.txt", "content_type": "text/plain", "content_base64": "aGk="},
                {"filename": "bad"},
                "junk",
            ],
        }

        incoming = EmailAdapter().parse_incoming(payload, "bot-1")

        assert incoming is not None
        assert (incoming.platform_user_id, incoming.platform_chat_id) == ("ada@acme.com",) * 2
        assert incoming.text == "Hello" and incoming.chat_type == "private" and incoming.addressed
        (attachment,) = incoming.attachments
        assert (attachment.filename, attachment.mime_type, attachment.handle) == (
            "a.txt",
            "text/plain",
            "bot-1:<1@acme>:0",
        )

    @pytest.mark.parametrize(
        "payload",
        [{"from": "nobody", "text": "x"}, {"from": "a@b.co", "text": "> only quoted"}, {}],
    )
    def test_nothing_to_answer_is_ignored(self, payload: dict) -> None:
        assert EmailAdapter().parse_incoming(payload, "b") is None

    def test_files_alone_are_a_message_and_unnamed_ones_get_a_name(self) -> None:
        payload = {"from": "a@b.co", "attachments": [{"content_base64": "aGk="}], "text": ""}

        incoming = EmailAdapter().parse_incoming(payload, "b")

        assert incoming is not None
        assert incoming.attachments[0].filename == "attachment-1"
        assert incoming.attachments[0].handle == "b:none:0"
        assert EmailAdapter().parse_incoming({"from": "a@b.co", "attachments": "x"}, "b") is None


class TestSending:
    async def test_a_reply_goes_from_the_bots_address_into_the_senders_thread(
        self, redis: _Redis, provider: _Provider
    ) -> None:
        await email_state.remember_thread(
            "agent@mail.acme.com",
            "ada@acme.com",
            subject="Invoice",
            message_id="<2@acme>",
            references=["<1@acme>"],
        )

        await EmailAdapter().send_message(
            BOT_ADDRESS, OutgoingMessage(platform_chat_id="ada@acme.com", text="Done.\n\nBye <b>")
        )

        (sent,) = provider.sent
        assert sent.to == ["ada@acme.com"] and sent.from_email == BOT_ADDRESS
        assert sent.subject == "Re: Invoice"
        assert sent.headers == {"In-Reply-To": "<2@acme>", "References": "<1@acme> <2@acme>"}
        assert sent.html == "<p>Done.</p><p>Bye &lt;b&gt;</p>"

    async def test_a_first_message_has_no_thread_and_files_ride_along(
        self, redis: _Redis, provider: _Provider
    ) -> None:
        from app.services.channels.base import OutgoingAttachment

        await EmailAdapter().send_message(
            BOT_ADDRESS,
            OutgoingMessage(
                platform_chat_id="ada@acme.com",
                text="",
                attachments=[OutgoingAttachment("r.pdf", b"%PDF", "application/pdf")],
            ),
        )

        (sent,) = provider.sent
        assert sent.subject == "Message from your agent" and sent.headers == {}
        assert [(a.filename, a.content) for a in sent.attachments] == [("r.pdf", b"%PDF")]

    async def test_a_subject_already_a_reply_is_not_prefixed_twice(
        self, redis: _Redis, provider: _Provider
    ) -> None:
        await email_state.remember_thread(
            "agent@mail.acme.com", "a@b.co", subject="RE: Hi", message_id=None, references=[]
        )

        await EmailAdapter().send_message(
            BOT_ADDRESS, OutgoingMessage(platform_chat_id="a@b.co", text="x")
        )

        assert provider.sent[0].subject == "RE: Hi" and provider.sent[0].headers == {}

    async def test_nothing_is_sent_for_nothing(self, redis: _Redis, provider: _Provider) -> None:
        await EmailAdapter().send_message(
            BOT_ADDRESS, OutgoingMessage(platform_chat_id="a@b.co", text="  ")
        )

        assert provider.sent == []

    async def test_a_token_that_is_not_an_address_or_a_provider_that_delivers_nothing_refuses(
        self,
    ) -> None:
        with pytest.raises(ChannelNotConfigured, match="address"):
            await EmailAdapter().send_message(
                "not-an-address", OutgoingMessage(platform_chat_id="a@b.co", text="x")
            )
        with (
            patch(
                "app.services.channels.email.get_email_provider",
                return_value=_Provider(delivers=False),
            ),
            pytest.raises(ChannelNotConfigured, match="delivers nothing"),
        ):
            await EmailAdapter().send_message(
                BOT_ADDRESS, OutgoingMessage(platform_chat_id="a@b.co", text="x")
            )

    async def test_a_message_the_provider_refused_is_a_failure_not_a_success(
        self, redis: _Redis
    ) -> None:
        with (
            patch(
                "app.services.channels.email.get_email_provider",
                return_value=_Provider(accepted=False),
            ),
            pytest.raises(RuntimeError, match="no"),
        ):
            await EmailAdapter().send_message(
                BOT_ADDRESS, OutgoingMessage(platform_chat_id="a@b.co", text="x")
            )

    async def test_without_redis_there_is_no_thread_and_no_state(self, provider: _Provider) -> None:
        await email_state.remember_thread("a", "b", subject="s", message_id=None, references=[])
        await email_state.stash_attachment("h", "x")

        assert await email_state.thread_of("a", "b") is None
        assert await email_state.take_attachment("h") is None
        assert await email_state.first_delivery("bot", "<1>")

    async def test_a_thread_keeps_a_bounded_chain(self, redis: _Redis) -> None:
        refs = [f"<{n}>" for n in range(50)]

        await email_state.remember_thread(
            "a", "b", subject="s", message_id="<last>", references=refs
        )

        thread = await email_state.thread_of("a", "b")
        assert thread is not None and len(thread.references) == email_state.MAX_REFERENCES
        assert thread.references[-1] == "<last>"


class TestPromptsAndFiles:
    async def test_a_prompt_is_numbered_remembered_and_settled_per_channel(
        self, redis: _Redis, provider: _Provider
    ) -> None:
        adapter = EmailAdapter()
        prompt = PromptMessage(
            platform_chat_id="Ada@Acme.com",
            text="Send it?",
            choices=[ChannelChoice("Yes", "aos:a:0"), ChannelChoice("No", "aos:a:1")],
            bot_id="bot-1",
        )

        await adapter.send_prompt(BOT_ADDRESS, prompt)

        assert "1. Yes" in provider.sent[0].text and "just the number" in provider.sent[0].text
        assert await sms_prompts.answer("bot-1", "ada@acme.com", "2", platform="email") == "aos:a:1"
        assert await sms_prompts.answer("bot-1", "ada@acme.com", "2") is None, "not an SMS prompt"
        await adapter.settle_prompt(
            BOT_ADDRESS,
            IncomingPress(
                platform="email",
                bot_id="bot-1",
                platform_user_id="ada@acme.com",
                platform_chat_id="Ada@Acme.com",
                value="aos:a:0",
            ),
            "Approved",
        )
        assert await sms_prompts.answer("bot-1", "ada@acme.com", "2", platform="email") is None

    async def test_an_attachment_is_read_back_until_it_expires(self, redis: _Redis) -> None:
        handle = "bot:<1>:0"
        await email_state.stash_attachment(handle, base64.b64encode(b"hello").decode())
        item = IncomingAttachment(filename="a", mime_type="text/plain", size=5, handle=handle)

        assert await EmailAdapter().download_attachment(BOT_ADDRESS, item) == b"hello"
        redis.data.clear()
        with pytest.raises(ValueError, match="no longer available"):
            await EmailAdapter().download_attachment(BOT_ADDRESS, item)

    async def test_polling_and_webhook_registration_have_nothing_to_do(self) -> None:
        adapter = EmailAdapter()

        await adapter.start_polling("b", BOT_ADDRESS)
        assert await adapter.stop_polling("b") is None
        assert await adapter.register_webhook(BOT_ADDRESS, "https://x/y", None)
        assert await adapter.delete_webhook(BOT_ADDRESS)


@asynccontextmanager
async def _client(bot: object | None) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    register_adapter(EmailAdapter())
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


def _post(body: dict | str, *, secret: str = SECRET) -> dict:
    raw = body if isinstance(body, str) else json.dumps(body)
    stamp = str(int(time.time()))
    return {
        "content": raw,
        "headers": {
            SIGNATURE_HEADER: sign(secret, stamp, raw),
            TIMESTAMP_HEADER: stamp,
            "content-type": "application/json",
        },
    }


class TestTheWebhook:
    ROOT = f"{settings.API_V1_STR}/email"

    def _bot(self, platform: str = "email") -> MagicMock:
        return MagicMock(id=uuid4(), platform=platform)

    @asynccontextmanager
    async def _wired(self, bot: MagicMock, *, secret: str | None = SECRET):
        spawned: list[str] = []
        with (
            patch("app.api.routes.v1.email_webhook.unseal_webhook_secret", return_value=secret),
            patch("app.api.routes.v1.email_webhook.unseal_bot_token", return_value=BOT_ADDRESS),
            patch(
                "app.api.routes.v1.email_webhook.spawn",
                side_effect=lambda coro, name: (spawned.append(name), coro.close()),
            ),
            patch("app.api.routes.v1.email_webhook.process_channel_event", new=MagicMock()),
            patch("app.api.routes.v1.email_webhook.process_channel_press", new=MagicMock()),
        ):
            yield spawned

    async def test_a_signed_mail_is_acknowledged_kept_and_handed_to_the_router(
        self, redis: _Redis
    ) -> None:
        bot = self._bot()
        body = {
            "from": "ada@acme.com",
            "subject": "Invoice",
            "text": "Please send it",
            "message_id": "<1@acme>",
            "references": ["<0@acme>"],
            "attachments": [
                {"filename": "a.txt", "content_type": "text/plain", "content_base64": "aGk="}
            ],
        }
        async with self._wired(bot) as spawned, _client(bot) as client:
            response = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post(body))
            again = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post(body))

        assert response.status_code == again.status_code == 200
        assert spawned == [f"email_event:{bot.id}"], "a retried delivery runs the agent once"
        thread = await email_state.thread_of("agent@mail.acme.com", "ada@acme.com")
        assert thread is not None and thread.subject == "Invoice"
        assert thread.references == ["<0@acme>", "<1@acme>"]
        assert await email_state.take_attachment(f"{bot.id}:<1@acme>:0") == "aGk="

    async def test_a_lone_number_that_fits_a_waiting_prompt_is_a_press(self, redis: _Redis) -> None:
        bot = self._bot()
        await sms_prompts.remember(
            str(bot.id), "ada@acme.com", ["aos:a:0"], start=1, platform="email"
        )
        body = {"from": "ada@acme.com", "text": "1\n> Send it?", "message_id": "<9>"}
        async with self._wired(bot) as spawned, _client(bot) as client:
            await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post(body))

        assert spawned == [f"email_press:{bot.id}"]

    async def test_a_forged_unsigned_or_secretless_request_is_refused_and_runs_nothing(
        self, redis: _Redis
    ) -> None:
        bot = self._bot()
        body = {"from": "ada@acme.com", "text": "hi"}
        async with self._wired(bot) as spawned, _client(bot) as client:
            forged = await client.post(
                f"{self.ROOT}/{bot.id}/inbound", **_post(body, secret="wrong-secret")
            )
            unsigned = await client.post(f"{self.ROOT}/{bot.id}/inbound", json=body)
        async with self._wired(bot, secret=None) as no_secret_spawned, _client(bot) as client:
            no_secret = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post(body))

        assert forged.status_code == unsigned.status_code == no_secret.status_code == 403
        assert spawned == [] and no_secret_spawned == []

    async def test_an_unknown_or_other_platforms_bot_gets_an_empty_answer(self) -> None:
        async with _client(None) as client:
            missing = await client.post(f"{self.ROOT}/{uuid4()}/inbound", content="{}")
        async with _client(self._bot("sms")) as client:
            other = await client.post(f"{self.ROOT}/{uuid4()}/inbound", content="{}")

        assert missing.status_code == other.status_code == 200

    async def test_a_signed_body_that_is_not_a_message_is_refused_or_ignored(
        self, redis: _Redis
    ) -> None:
        bot = self._bot()
        async with self._wired(bot) as spawned, _client(bot) as client:
            not_json = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post("nope"))
            not_object = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post("[1]"))
            empty = await client.post(f"{self.ROOT}/{bot.id}/inbound", **_post({"from": "x"}))

        assert (not_json.status_code, not_object.status_code, empty.status_code) == (400, 400, 200)
        assert spawned == []

    async def test_an_oversized_message_is_refused_before_it_is_read(self) -> None:
        bot = self._bot()
        with patch("app.api.routes.v1.email_webhook.MAX_BODY_BYTES", 10):
            async with self._wired(bot), _client(bot) as client:
                declared = await client.post(
                    f"{self.ROOT}/{bot.id}/inbound", content="x" * 50, headers={"x-a": "b"}
                )

        assert declared.status_code == 413


def test_the_adapter_is_the_one_registered_for_email() -> None:
    register_adapter(EmailAdapter())

    assert isinstance(get_adapter("email"), EmailAdapter)


class TestCreatingABot:
    def test_it_needs_the_webhook_an_address_and_a_secret(self) -> None:
        from app.core.exceptions import BadRequestError
        from app.services.channel_bot import ChannelBotService

        def data(**kw):
            base = {
                "platform": "email",
                "token": "a@b.co",
                "webhook_mode": True,
                "webhook_secret": SECRET,
            }
            return MagicMock(**{**base, **kw})

        ChannelBotService._check_email(data())
        ChannelBotService._check_email(data(platform="sms", webhook_mode=False))
        with pytest.raises(BadRequestError):
            ChannelBotService._check_email(data(webhook_mode=False))
        with pytest.raises(BadRequestError):
            ChannelBotService._check_email(data(token="nope"))
        with pytest.raises(BadRequestError):
            ChannelBotService._check_email(data(webhook_secret=None))
        ChannelBotService._check_email_token("telegram", "anything")
