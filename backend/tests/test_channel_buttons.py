"""Approvals and questions as buttons on Telegram and Mattermost (#2064, #2068).

Each platform draws the buttons its own way and hands a press back its own way;
what has to hold on both is that a press reaches the same handler with the same
four facts - who, where, which message, which value - and that Mattermost, which
signs nothing, is not trusted with a press this deployment did not sign.
"""

import base64
import contextlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException

from app.api.routes.v1.mattermost_webhook import mattermost_action
from app.api.routes.v1.telegram_webhook import telegram_webhook
from app.services.channels.base import ChannelChoice, IncomingPress, PromptMessage
from app.services.channels.mattermost import MattermostAdapter, trigger_presser
from app.services.channels.telegram import TelegramAdapter
from app.services.channels.telegram_press import parse_press
from app.services.channels.webhooks import inbound_actions_url, sign_press
from app.worker.background.channel import process_channel_press, process_slack_surface

pytestmark = pytest.mark.anyio


def _prompt(**fields: Any) -> PromptMessage:
    return PromptMessage(
        platform_chat_id=fields.pop("platform_chat_id", "42"),
        text="Approve it?",
        choices=[
            ChannelChoice(label="Approve", value="aos:p:0", style="primary"),
            ChannelChoice(label="Reject", value="aos:p:1", style="danger"),
            ChannelChoice(label="Maybe", value="aos:p:2"),
        ],
        **fields,
    )


def _telegram(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    bot = MagicMock()
    for method in ("send_message", "answer_callback_query", "edit_message_text"):
        setattr(bot, method, AsyncMock())

    @contextlib.asynccontextmanager
    async def fake_bot(token: str, **_: Any):
        yield bot

    monkeypatch.setattr(TelegramAdapter, "_bot", staticmethod(fake_bot))
    return bot


class TestTelegram:
    async def test_a_prompt_is_an_inline_keyboard_one_button_a_row(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_prompt("t", _prompt())

        markup = bot.send_message.await_args.kwargs["reply_markup"]
        assert [[button.text for button in row] for row in markup.inline_keyboard] == [
            ["Approve"],
            ["Reject"],
            ["Maybe"],
        ]
        assert markup.inline_keyboard[0][0].callback_data == "aos:p:0"

    async def test_a_press_stops_spinning_and_the_keyboard_comes_off(self, monkeypatch):
        bot = _telegram(monkeypatch)
        press = IncomingPress(
            platform="telegram",
            bot_id="b",
            platform_user_id="9",
            platform_chat_id="42",
            value="aos:p:0",
            message_id="7",
            prompt_text="Approve it?",
            ack_id="q1",
        )

        await TelegramAdapter().acknowledge("t", press)
        await TelegramAdapter().settle_prompt("t", press, "Approved.")
        press.prompt_text = None
        await TelegramAdapter().settle_prompt("t", press, "Approved.")

        bot.answer_callback_query.assert_awaited_once_with(callback_query_id="q1")
        first, second = bot.edit_message_text.await_args_list
        assert first.kwargs == {"chat_id": "42", "message_id": 7, "text": "Approve it?\nApproved."}
        assert second.kwargs["text"] == "Approved."

    async def test_nothing_to_acknowledge_or_edit_calls_nothing(self, monkeypatch):
        bot = _telegram(monkeypatch)
        press = IncomingPress(
            platform="telegram", bot_id="b", platform_user_id="9", platform_chat_id="42", value="v"
        )

        await TelegramAdapter().acknowledge("t", press)
        await TelegramAdapter().settle_prompt("t", press, "Approved.")

        bot.answer_callback_query.assert_not_awaited()
        bot.edit_message_text.assert_not_awaited()

    def test_a_callback_query_is_read_into_a_press(self):
        press = parse_press(
            {
                "callback_query": {
                    "id": "q1",
                    "from": {"id": 9, "username": "ada"},
                    "message": {"message_id": 7, "chat": {"id": 42}, "text": "Approve it?"},
                    "data": "aos:p:0",
                }
            },
            "bot-1",
        )

        assert press == IncomingPress(
            platform="telegram",
            bot_id="bot-1",
            platform_user_id="9",
            platform_chat_id="42",
            value="aos:p:0",
            platform_username="ada",
            message_id="7",
            prompt_text="Approve it?",
            ack_id="q1",
        )

    @pytest.mark.parametrize(
        "payload", [{"message": {}}, {"callback_query": "x"}, {"callback_query": {"id": "q"}}]
    )
    def test_anything_else_is_not_a_press(self, payload: dict[str, Any]):
        assert parse_press(payload, "b") is None

    async def test_a_polled_press_reaches_the_same_handler(self):
        query = MagicMock()
        query.model_dump.return_value = {"id": "q", "from": {"id": 1}, "data": "aos:p:0"}
        with patch(
            "app.worker.background.channel.process_channel_press", new=AsyncMock()
        ) as pressed:
            await TelegramAdapter()._handle_press(query, "b")
            query.model_dump.return_value = {"id": "q"}
            await TelegramAdapter()._handle_press(query, "b")

        pressed.assert_awaited_once()

    async def test_a_webhook_press_is_handled_in_the_background(self):
        payload = {"callback_query": {"id": "q", "from": {"id": 1}, "data": "aos:p:0"}}
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)
        request.headers = {}
        adapter = MagicMock()
        adapter.verify_webhook_signature.return_value = True
        module = "app.api.routes.v1.telegram_webhook"
        with (
            patch(f"{module}.get_adapter", return_value=adapter),
            patch(f"{module}.unseal_webhook_secret", return_value="s"),
            patch(f"{module}.spawn") as spawn,
        ):
            await telegram_webhook(
                uuid.uuid4(), request, MagicMock(find_active=AsyncMock(return_value=MagicMock()))
            )

        assert spawn.call_args.kwargs["name"].startswith("telegram_press:")
        spawn.call_args.args[0].close()
        adapter.parse_incoming.assert_not_called()


def _trigger(
    key: ec.EllipticCurvePrivateKey, user_id: str, *, at: datetime, channel: bool = True
) -> str:
    """A trigger id as a Mattermost server mints one for a press."""
    fields = ["client", user_id, str(int(at.timestamp() * 1000))] + (["chan"] if channel else [])
    data = ":".join(fields) + ":"
    signature = key.sign(data.encode(), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode((data + base64.b64encode(signature).decode()).encode()).decode()


def _der(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


class TestWhoPressed:
    """A Mattermost press names its presser in an unsigned body; the trigger id proves it."""

    NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    @pytest.mark.parametrize("channel", [True, False], ids=["current", "older-server"])
    def test_a_trigger_the_server_signed_names_its_user(self, channel: bool):
        key = ec.generate_private_key(ec.SECP256R1())

        trigger = _trigger(key, "ada", at=self.NOW, channel=channel)

        assert trigger_presser(trigger, _der(key), now=self.NOW) == "ada"

    @pytest.mark.parametrize(
        "case", ["other-key", "too-old", "edited", "garbage", "not-ec", "too-short"]
    )
    def test_anything_else_names_nobody(self, case: str):
        key = ec.generate_private_key(ec.SECP256R1())
        der = _der(key)
        trigger = _trigger(key, "ada", at=self.NOW)
        if case == "other-key":
            der = _der(ec.generate_private_key(ec.SECP256R1()))
        elif case == "too-old":
            trigger = _trigger(key, "ada", at=self.NOW - timedelta(minutes=6))
        elif case == "edited":
            decoded = base64.b64decode(trigger).decode().replace(":ada:", ":eve:")
            trigger = base64.b64encode(decoded.encode()).decode()
        elif case == "garbage":
            trigger = "not base64!"
        elif case == "not-ec":
            der = (
                rsa.generate_private_key(public_exponent=65537, key_size=2048)
                .public_key()
                .public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            )
        else:
            trigger = base64.b64encode(b"client:ada:sig").decode()

        assert trigger_presser(trigger, der, now=self.NOW) is None

    async def test_the_press_is_checked_against_the_server_s_published_key(self):
        key = ec.generate_private_key(ec.SECP256R1())
        stale = ec.generate_private_key(ec.SECP256R1())
        served = [_der(stale), _der(key)]
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            published = base64.b64encode(served.pop(0)).decode()
            return httpx.Response(200, json={"AsymmetricSigningPublicKey": published})

        adapter = _mattermost(handler)
        payload = {"user_id": "ada", "trigger_id": _trigger(key, "ada", at=datetime.now(UTC))}

        # The cached key is stale: it is read again once, and the press proven.
        assert await adapter.pressed_by("https://mm/", payload)
        assert seen == ["https://mm/api/v4/config/client?format=old"] * 2
        # The second press costs no request.
        assert await adapter.pressed_by("https://mm", payload)
        assert len(seen) == 2
        # A body naming somebody else is not the presser the trigger names.
        assert not await adapter.pressed_by("https://mm", {**payload, "user_id": "operator"})

    @pytest.mark.parametrize(
        "payload",
        [{"trigger_id": "t"}, {"user_id": "ada"}, {"user_id": "ada", "trigger_id": 3}],
        ids=["no-user", "no-trigger", "trigger-not-text"],
    )
    async def test_a_press_missing_either_half_is_refused_unread(self, payload: dict[str, Any]):
        adapter = _mattermost(lambda request: httpx.Response(500))

        assert not await adapter.pressed_by("https://mm", payload)

    async def test_a_trigger_no_published_key_signed_proves_nobody(self):
        published = base64.b64encode(_der(ec.generate_private_key(ec.SECP256R1()))).decode()
        adapter = _mattermost(
            lambda request: httpx.Response(200, json={"AsymmetricSigningPublicKey": published})
        )
        forger = ec.generate_private_key(ec.SECP256R1())
        payload = {"user_id": "ada", "trigger_id": _trigger(forger, "ada", at=datetime.now(UTC))}

        assert not await adapter.pressed_by("https://mm", payload)

    async def test_a_server_that_publishes_no_key_proves_nobody(self):
        adapter = _mattermost(lambda request: httpx.Response(200, json={}))
        key = ec.generate_private_key(ec.SECP256R1())
        payload = {"user_id": "ada", "trigger_id": _trigger(key, "ada", at=datetime.now(UTC))}

        assert not await adapter.pressed_by("https://mm", payload)


def _mattermost(handler: Any) -> MattermostAdapter:
    adapter = MattermostAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


class TestMattermost:
    @pytest.fixture(autouse=True)
    def _registered(self):
        """The registry is filled at app startup, which unit tests skip."""
        with patch(
            "app.api.routes.v1.mattermost_webhook.get_adapter", return_value=MattermostAdapter()
        ):
            yield

    async def test_a_prompt_is_an_interactive_post_whose_buttons_carry_our_signature(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json={"id": "post-1"})

        await _mattermost(handler).send_prompt(
            "t",
            _prompt(platform_chat_id="ch:root", bot_id="bot-1", api_base_url="https://mm.acme/"),
        )

        body = json.loads(seen[0].content)
        assert str(seen[0].url) == "https://mm.acme/api/v4/posts"
        assert (body["channel_id"], body["root_id"]) == ("ch", "root")
        actions = body["props"]["attachments"][0]["actions"]
        assert [(action["name"], action["style"]) for action in actions] == [
            ("Approve", "primary"),
            ("Reject", "danger"),
            ("Maybe", "default"),
        ]
        integration = actions[0]["integration"]
        assert integration["url"] == inbound_actions_url("bot-1")
        assert integration["context"]["signature"] == sign_press("bot-1", "aos:p:0")

    async def test_a_prompt_with_no_server_is_refused(self):
        with pytest.raises(ValueError, match="no server URL"):
            await _mattermost(lambda request: httpx.Response(201)).send_prompt("t", _prompt())

    async def test_a_top_level_prompt_has_no_root(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json={})

        await _mattermost(handler).send_prompt(
            "t", _prompt(bot_id="b", api_base_url="https://mm.acme")
        )

        assert "root_id" not in json.loads(seen[0].content)

    async def test_a_pressed_post_loses_its_buttons(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        adapter = _mattermost(handler)
        adapter.remember_server("b", "https://mm.acme/")
        press = IncomingPress(
            platform="mattermost",
            bot_id="b",
            platform_user_id="u",
            platform_chat_id="ch",
            value="v",
            message_id="post-1",
            prompt_text="Approve it?",
        )

        await adapter.settle_prompt("t", press, "Approved.")
        press.prompt_text = None
        await adapter.settle_prompt("t", press, "Approved.")
        press.message_id = None
        await adapter.settle_prompt("t", press, "Approved.")

        assert len(seen) == 2
        assert str(seen[0].url) == "https://mm.acme/api/v4/posts/post-1/patch"
        assert json.loads(seen[0].content) == {
            "message": "Approve it?\n**Approved.**",
            "props": {"attachments": []},
        }
        assert json.loads(seen[1].content)["message"] == "**Approved.**"

    def test_a_signed_press_is_read_and_an_unsigned_one_is_not(self):
        signed = {
            "user_id": "u",
            "user_name": "ada",
            "channel_id": "ch",
            "post_id": "post-1",
            "context": {
                "value": "aos:p:0",
                "text": "Approve it?",
                "signature": sign_press("b", "aos:p:0"),
            },
        }

        press = MattermostAdapter.parse_press(signed, "b")

        assert press is not None
        assert (press.platform_user_id, press.message_id, press.prompt_text) == (
            "u",
            "post-1",
            "Approve it?",
        )
        # The same press relayed to another bot fails its signature.
        assert MattermostAdapter.parse_press(signed, "other-bot") is None
        assert MattermostAdapter.parse_press({"context": {"value": "v"}}, "b") is None

    @pytest.mark.security
    async def test_the_action_url_refuses_an_unsigned_press(self):
        request = MagicMock()
        request.json = AsyncMock(
            return_value={"context": {"value": "aos:p:0", "signature": "nope"}}
        )
        service = MagicMock(
            find_active=AsyncMock(return_value=MagicMock(api_base_url="https://mm"))
        )

        with pytest.raises(HTTPException) as refused:
            await mattermost_action(uuid.uuid4(), request, service)

        assert refused.value.status_code == 403

    async def test_the_action_url_hands_a_signed_press_on(self):
        bot_id = uuid.uuid4()
        request = MagicMock()
        request.json = AsyncMock(
            return_value={
                "user_id": "u",
                "context": {"value": "aos:p:0", "signature": sign_press(str(bot_id), "aos:p:0")},
            }
        )
        service = MagicMock(
            find_active=AsyncMock(return_value=MagicMock(api_base_url="https://mm"))
        )
        with (
            patch("app.api.routes.v1.mattermost_webhook.spawn") as spawn,
            patch.object(MattermostAdapter, "pressed_by", AsyncMock(return_value=True)),
        ):
            answered = await mattermost_action(bot_id, request, service)

        assert answered == {}
        assert spawn.call_args.kwargs["name"].startswith("mattermost_press:")
        spawn.call_args.args[0].close()

    @pytest.mark.security
    async def test_the_action_url_refuses_a_press_whose_presser_is_not_proven(self):
        """Codex on #2062: the body's `user_id` alone decided whose role pressed."""
        bot_id = uuid.uuid4()
        request = MagicMock()
        request.json = AsyncMock(
            return_value={
                "user_id": "operator",
                "context": {"value": "aos:p:0", "signature": sign_press(str(bot_id), "aos:p:0")},
            }
        )
        service = MagicMock(
            find_active=AsyncMock(return_value=MagicMock(api_base_url="https://mm"))
        )
        with (
            patch("app.api.routes.v1.mattermost_webhook.spawn") as spawn,
            patch.object(MattermostAdapter, "pressed_by", AsyncMock(return_value=False)),
            pytest.raises(HTTPException) as refused,
        ):
            await mattermost_action(bot_id, request, service)

        assert refused.value.status_code == 403
        spawn.assert_not_called()

    async def test_the_action_url_for_an_unknown_bot_answers_empty(self):
        service = MagicMock(find_active=AsyncMock(return_value=None))

        assert await mattermost_action(uuid.uuid4(), MagicMock(), service) == {}


class TestTheBackgroundHandlers:
    async def test_a_press_is_handled_and_a_failure_is_only_logged(self):
        module = "app.worker.background.channel"
        with (
            patch(f"{module}.get_db_context") as db_context,
            patch(f"{module}.ChannelPrompts") as prompts,
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            prompts.return_value.press = AsyncMock()
            await process_channel_press(MagicMock(value="aos:prompt:0"))
            prompts.return_value.press.side_effect = RuntimeError("boom")
            await process_channel_press(MagicMock(value="aos:prompt:0"))

        assert prompts.return_value.press.await_count == 2

    async def test_a_surface_event_reaches_an_active_bot_only(self):
        module = "app.worker.background.channel"
        with (
            patch(f"{module}.get_db_context") as db_context,
            patch(f"{module}.channel_bot_repo.get_for_inbound", new=AsyncMock()) as found,
            patch(f"{module}.SlackSurfaces") as surfaces,
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            surfaces.return_value.handle = AsyncMock()
            found.return_value = MagicMock(is_active=True)
            await process_slack_surface({}, str(uuid.uuid4()))
            found.return_value = None
            await process_slack_surface({}, str(uuid.uuid4()))
            await process_slack_surface({}, "not-a-uuid")

        surfaces.return_value.handle.assert_awaited_once()
