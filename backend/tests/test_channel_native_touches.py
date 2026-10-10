"""The platform side of #2084: streamed answers, thumbs, reactions and `/agent`."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.channels.base import AnswerStep, IncomingMessage, IncomingPress, OutgoingMessage
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.slack_answer import SlackNativeAnswer
from app.services.channels.webhooks import sign_press

pytestmark = pytest.mark.anyio


def _incoming(**overrides: Any) -> IncomingMessage:
    fields: dict[str, Any] = {
        "platform": "slack",
        "bot_id": "bot-1",
        "platform_user_id": "U1",
        "platform_chat_id": "C1:111.1",
        "chat_type": "group",
        "text": "hi",
        "message_id": "111.1",
        "platform_team_id": "T1",
    }
    fields.update(overrides)
    return IncomingMessage(**fields)


def _web(**returns: Any) -> MagicMock:
    client = MagicMock()
    for method in (
        "assistant_threads_setStatus",
        "chat_startStream",
        "chat_update",
        "reactions_add",
    ):
        setattr(client, method, AsyncMock(return_value=returns.get(method, {})))
    return client


class TestSlackStreamsItsAnswers:
    async def test_an_answer_streams_into_the_question_s_thread_for_the_asker(self) -> None:
        client = _web(chat_startStream={"ts": "222.2"})
        with patch.object(SlackAdapter, "_web", return_value=client):
            answer = await SlackAdapter().open_answer("xoxb", _incoming(), steps="timeline")

        assert isinstance(answer, SlackNativeAnswer)
        assert answer.handle == "222.2"
        assert client.chat_startStream.await_args.kwargs == {
            "channel": "C1",
            "thread_ts": "111.1",
            "recipient_user_id": "U1",
            "recipient_team_id": "T1",
            "task_display_mode": "timeline",
        }

    async def test_a_plan_is_headed_by_the_question(self) -> None:
        client = _web(chat_startStream={"ts": "222.2"})
        client.chat_appendStream = AsyncMock()
        with patch.object(SlackAdapter, "_web", return_value=client):
            answer = await SlackAdapter().open_answer(
                "xoxb", _incoming(text="Compare our Q3 numbers\nwith Q2"), steps="plan"
            )
        assert answer is not None
        assert client.chat_startStream.await_args.kwargs["task_display_mode"] == "plan"

        await answer.step(AnswerStep("1", "Searching the web…", "in_progress"))
        await answer.step(AnswerStep("1", "Searching the web…", "complete"))

        first, second = (call.kwargs["chunks"] for call in client.chat_appendStream.await_args_list)
        assert first[0] == {"type": "plan_update", "title": "Compare our Q3 numbers"}
        assert [chunk["type"] for chunk in second] == ["task_update"]

    async def test_no_thread_no_stream(self) -> None:
        client = _web()
        with patch.object(SlackAdapter, "_web", return_value=client):
            assert (
                await SlackAdapter().open_answer(
                    "xoxb", _incoming(platform_chat_id="C1"), steps="timeline"
                )
                is None
            )
        client.chat_startStream.assert_not_awaited()

    @pytest.mark.parametrize("started", [RuntimeError("not_allowed"), {"ok": True}])
    async def test_a_stream_slack_will_not_start_falls_back_to_editing(self, started: Any) -> None:
        client = _web()
        client.chat_startStream = AsyncMock(
            side_effect=started if isinstance(started, Exception) else None,
            return_value=None if isinstance(started, Exception) else started,
        )
        with patch.object(SlackAdapter, "_web", return_value=client):
            assert await SlackAdapter().open_answer("xoxb", _incoming(), steps="timeline") is None

    async def test_an_edited_answer_gets_its_thumbs_as_blocks(self) -> None:
        client = _web()
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().offer_feedback(
                "xoxb", OutgoingMessage("C1:111.1", "The answer"), "222.2", "run-1", bot_id="b"
            )

        update = client.chat_update.await_args.kwargs
        assert update["ts"] == "222.2"
        assert [block["type"] for block in update["blocks"]] == ["markdown", "context_actions"]

    async def test_the_question_gets_the_bot_s_reaction(self) -> None:
        client = _web()
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().acknowledge_message("xoxb", _incoming(), "eyes")
            await SlackAdapter().acknowledge_message("xoxb", _incoming(message_id=None), "eyes")

        client.reactions_add.assert_awaited_once_with(channel="C1", timestamp="111.1", name="eyes")

    def test_the_sender_s_workspace_is_read_off_the_event(self) -> None:
        payload = {
            "team_id": "T9",
            "event": {"type": "message", "text": "hi", "user": "U1", "channel": "C1", "ts": "1.1"},
        }
        incoming = SlackAdapter().parse_incoming(payload, "bot-1")
        assert incoming is not None
        assert incoming.platform_team_id == "T9"


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"id": "me", "username": "agent"}


class _Http:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def put(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("put", url, kwargs.get("json")))
        return _Response()

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("post", url, kwargs.get("json")))
        return _Response()

    async def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("get", url, None))
        return _Response()


def _mattermost() -> tuple[MattermostAdapter, _Http]:
    adapter = MattermostAdapter()
    http = _Http()
    adapter._http = http  # type: ignore[assignment]
    adapter.remember_server("bot-1", "https://mm.acme.com")
    return adapter, http


class TestMattermostThumbsReactionsAndAgent:
    async def test_an_answer_gets_signed_thumbs(self) -> None:
        adapter, http = _mattermost()

        await adapter.offer_feedback(
            "tok",
            OutgoingMessage("ch1", "The answer", api_base_url="https://mm.acme.com"),
            "post-1",
            "run-1",
            bot_id="bot-1",
        )

        method, url, body = http.calls[0]
        assert (method, url) == ("put", "https://mm.acme.com/api/v4/posts/post-1/patch")
        actions = body["props"]["attachments"][0]["actions"]
        assert [action["name"] for action in actions] == [":+1: Helpful", ":-1: Not helpful"]
        context = actions[0]["integration"]["context"]
        assert context["signature"] == sign_press("bot-1", context["value"])

    async def test_a_rating_takes_the_thumbs_off(self) -> None:
        adapter, http = _mattermost()
        press = IncomingPress(
            platform="mattermost",
            bot_id="bot-1",
            platform_user_id="u",
            platform_chat_id="ch1",
            value="aosfb:r:+",
            message_id="post-1",
            prompt_text="The answer",
        )

        await adapter.settle_feedback("tok", press, True)

        assert http.calls[0][2] == {
            "message": "The answer\n**:+1: Rated helpful**",
            "props": {"attachments": []},
        }

    async def test_the_question_gets_the_bot_s_reaction_as_the_bot(self) -> None:
        adapter, http = _mattermost()
        incoming = _incoming(platform="mattermost", platform_chat_id="ch1", message_id="post-9")

        await adapter.acknowledge_message("tok", incoming, "eyes")

        assert http.calls[-1] == (
            "post",
            "https://mm.acme.com/api/v4/reactions",
            {"user_id": "me", "post_id": "post-9", "emoji_name": "eyes"},
        )

    async def test_no_server_message_or_identity_means_no_reaction(self) -> None:
        adapter, http = _mattermost()
        await adapter.acknowledge_message("tok", _incoming(bot_id="unknown"), "eyes")
        await adapter.acknowledge_message("tok", _incoming(message_id=None), "eyes")
        with patch.object(adapter, "_own_user_id", AsyncMock(return_value=None)):
            await adapter.acknowledge_message("tok", _incoming(), "eyes")
        assert [call for call in http.calls if call[0] == "post"] == []

    def test_slash_agent_is_a_question_in_the_channel_it_was_typed_in(self) -> None:
        form = {
            "text": " what is our refund window? ",
            "channel_id": "ch1",
            "channel_name": "town-square",
            "user_id": "u1",
            "user_name": "ada",
            "team_id": "team1",
            "trigger_id": "trig",
        }
        incoming = MattermostAdapter.parse_command(form, "bot-1")
        assert incoming is not None
        assert (incoming.text, incoming.platform_chat_id, incoming.chat_type) == (
            "what is our refund window?",
            "ch1",
            "group",
        )
        assert incoming.addressed is True
        dm = MattermostAdapter.parse_command({**form, "channel_name": "u1__u2"}, "bot-1")
        assert dm is not None and dm.chat_type == "private"
        assert MattermostAdapter.parse_command({**form, "text": "  "}, "bot-1") is None


class TestTheMattermostCommandRoute:
    @staticmethod
    def _request(form: dict[str, str]) -> MagicMock:
        from urllib.parse import urlencode

        request = MagicMock()
        request.body = AsyncMock(return_value=urlencode(form).encode())
        return request

    async def _call(self, form: dict[str, str], *, token: str | None, bot: Any = True) -> Any:
        from app.api.routes.v1 import mattermost_webhook as route

        row = MagicMock(api_base_url="https://mm.acme.com") if bot else None
        service = MagicMock(find_active=AsyncMock(return_value=row))
        with (
            patch.object(route, "unseal_command_token", return_value=token),
            patch.object(route, "get_adapter", return_value=MattermostAdapter()),
            patch.object(route, "spawn") as spawn,
        ):
            spawn.side_effect = lambda coroutine, name: coroutine.close()
            result = await route.mattermost_command(uuid.uuid4(), self._request(form), service)
        return result, spawn

    async def test_a_verified_command_is_answered_in_the_background(self) -> None:
        result, spawn = await self._call(
            {"token": "cmd-token", "text": "hi", "channel_id": "ch1"}, token="cmd-token"
        )
        assert result == {}
        spawn.assert_called_once()

    async def test_an_empty_command_says_how_to_use_it(self) -> None:
        result, spawn = await self._call({"token": "cmd-token", "text": ""}, token="cmd-token")
        assert result["response_type"] == "ephemeral"
        spawn.assert_not_called()

    @pytest.mark.parametrize(("sent", "stored"), [("wrong", "cmd-token"), ("x", None)])
    async def test_an_unverified_command_is_refused(self, sent: str, stored: str | None) -> None:
        with pytest.raises(HTTPException) as refused:
            await self._call({"token": sent, "text": "hi", "channel_id": "c"}, token=stored)
        assert refused.value.status_code == 403

    async def test_an_unknown_bot_is_answered_with_nothing(self) -> None:
        result, spawn = await self._call({"text": "hi"}, token="t", bot=False)
        assert result == {}
        spawn.assert_not_called()


def test_the_manifest_is_org_ready_and_may_react() -> None:
    from app.services.channels.slack_manifest import slack_manifest

    bot = MagicMock(id=uuid.uuid4(), webhook_mode=True)
    bot.name = "Helper"
    manifest = slack_manifest(bot)
    assert manifest["settings"]["org_deploy_enabled"] is True
    assert manifest["settings"]["socket_mode_enabled"] is False
    assert manifest["settings"]["event_subscriptions"]["request_url"].endswith("/events")
    assert "reactions:write" in manifest["oauth_config"]["scopes"]["bot"]
    json.dumps(manifest)


class TestTelegramThumbsAndReactions:
    @pytest.fixture
    def bot(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        import contextlib

        from app.services.channels.telegram import TelegramAdapter

        fake = MagicMock(edit_message_reply_markup=AsyncMock(), set_message_reaction=AsyncMock())

        @contextlib.asynccontextmanager
        async def fake_bot(token: str, **_: Any):
            yield fake

        monkeypatch.setattr(TelegramAdapter, "_bot", staticmethod(fake_bot))
        return fake

    async def test_an_answer_gets_thumbs_and_loses_them_when_pressed(self, bot: MagicMock) -> None:
        from app.services.channels.base import read_feedback
        from app.services.channels.telegram import TelegramAdapter

        await TelegramAdapter().offer_feedback(
            "t", OutgoingMessage("42", "The answer"), "7", "run-1", bot_id="b"
        )
        keyboard = bot.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        buttons = keyboard.inline_keyboard[0]
        assert [read_feedback(button.callback_data) for button in buttons] == [
            ("run-1", True),
            ("run-1", False),
        ]

        press = IncomingPress(
            platform="telegram",
            bot_id="b",
            platform_user_id="u",
            platform_chat_id="42",
            value="aosfb:run-1:+",
            message_id="7",
        )
        await TelegramAdapter().settle_feedback("t", press, True)
        assert bot.edit_message_reply_markup.await_args.kwargs["reply_markup"] is None
        await TelegramAdapter().settle_feedback(
            "t",
            IncomingPress(
                platform="telegram",
                bot_id="b",
                platform_user_id="u",
                platform_chat_id="42",
                value="aosfb:run-1:+",
            ),
            True,
        )
        assert bot.edit_message_reply_markup.await_count == 2

    async def test_a_named_reaction_telegram_allows_is_set(self, bot: MagicMock) -> None:
        from app.services.channels.telegram import TelegramAdapter

        incoming = _incoming(platform="telegram", platform_chat_id="42", message_id="7")
        await TelegramAdapter().acknowledge_message("t", incoming, "eyes")
        await TelegramAdapter().acknowledge_message("t", incoming, "party_parrot")
        await TelegramAdapter().acknowledge_message("t", _incoming(message_id=None), "eyes")

        bot.set_message_reaction.assert_awaited_once()
        assert bot.set_message_reaction.await_args.kwargs["reaction"][0].emoji == "👀"


class TestWhatWasWrong:
    async def test_a_thumbs_down_in_slack_opens_the_modal(self) -> None:
        client = MagicMock(views_open=AsyncMock())
        press = IncomingPress(
            platform="slack",
            bot_id="b",
            platform_user_id="U1",
            platform_chat_id="C1",
            value="aosfb:run-1:-",
            trigger_id="trig",
        )
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().ask_feedback_comment("xoxb", press, "run-1", bot_id="b")
            await SlackAdapter().ask_feedback_comment(
                "xoxb", IncomingPress("slack", "b", "U1", "C1", "v"), "run-1", bot_id="b"
            )

        view = client.views_open.await_args.kwargs["view"]
        assert view["private_metadata"] == "run-1"
        client.views_open.assert_awaited_once()

    def test_the_slack_modal_comes_back_as_a_comment(self) -> None:
        from app.services.channels.slack_app import FEEDBACK_COMMENT, parse_feedback_comment

        def submitted(text: str, *, callback: str = FEEDBACK_COMMENT, run: str = "run-1") -> dict:
            return {
                "type": "view_submission",
                "user": {"id": "U1"},
                "view": {
                    "callback_id": callback,
                    "private_metadata": run,
                    "state": {"values": {"comment": {"comment": {"value": text}}}},
                },
            }

        comment = parse_feedback_comment(submitted("  Wrong dates  "), "b")
        assert comment is not None
        assert (comment.platform_user_id, comment.run_id, comment.text) == (
            "U1",
            "run-1",
            "Wrong dates",
        )
        assert parse_feedback_comment(submitted("   "), "b") is None
        assert parse_feedback_comment(submitted("x", callback="other"), "b") is None
        assert parse_feedback_comment(submitted("x", run=""), "b") is None
        assert parse_feedback_comment({"type": "block_actions"}, "b") is None

    async def test_a_thumbs_down_in_mattermost_opens_a_signed_dialog(self) -> None:
        adapter, http = _mattermost()
        press = IncomingPress(
            platform="mattermost",
            bot_id="bot-1",
            platform_user_id="u",
            platform_chat_id="c",
            value="aosfb:run-1:-",
            trigger_id="trig",
        )

        await adapter.ask_feedback_comment("tok", press, "run-1", bot_id="bot-1")
        await adapter.ask_feedback_comment(
            "tok", IncomingPress("mattermost", "bot-1", "u", "c", "v"), "run-1", bot_id="bot-1"
        )

        method, url, body = http.calls[0]
        assert url == "https://mm.acme.com/api/v4/actions/dialogs/open"
        assert body["dialog"]["state"] == f"run-1:{sign_press('bot-1', 'run-1')}"
        assert len(http.calls) == 1

    def test_only_a_signed_mattermost_dialog_is_a_comment(self) -> None:
        from app.services.channels.mattermost import FEEDBACK_DIALOG

        def submitted(state: str, text: str = "Wrong dates", **extra: Any) -> dict:
            return {
                "callback_id": FEEDBACK_DIALOG,
                "state": state,
                "user_id": "u1",
                "submission": {"comment": text},
                **extra,
            }

        signed = f"run-1:{sign_press('bot-1', 'run-1')}"
        comment = MattermostAdapter.parse_feedback_comment(submitted(signed), "bot-1")
        assert comment is not None and comment.run_id == "run-1"
        assert MattermostAdapter.parse_feedback_comment(submitted("run-1:forged"), "bot-1") is None
        assert MattermostAdapter.parse_feedback_comment(submitted(signed, " "), "bot-1") is None
        assert (
            MattermostAdapter.parse_feedback_comment(submitted(signed, cancelled=True), "bot-1")
            is None
        )


class TestTheMattermostDialogRoute:
    async def _call(self, payload: dict[str, Any], *, bot: Any = True) -> Any:
        from app.api.routes.v1 import mattermost_webhook as route

        request = MagicMock(json=AsyncMock(return_value=payload))
        service = MagicMock(find_active=AsyncMock(return_value=MagicMock() if bot else None))
        with patch.object(route, "spawn") as spawn:
            spawn.side_effect = lambda coroutine, name: coroutine.close()
            bot_id = uuid.UUID(int=1)
            return await route.mattermost_dialog(bot_id, request, service), spawn

    @staticmethod
    def _signed(text: str = "Wrong") -> dict[str, Any]:
        from app.services.channels.mattermost import FEEDBACK_DIALOG

        bot_id = str(uuid.UUID(int=1))
        return {
            "callback_id": FEEDBACK_DIALOG,
            "state": f"run-1:{sign_press(bot_id, 'run-1')}",
            "user_id": "u1",
            "submission": {"comment": text},
        }

    async def test_a_signed_answer_is_kept_in_the_background(self) -> None:
        result, spawn = await self._call(self._signed())
        assert result == {}
        spawn.assert_called_once()

    async def test_a_cancelled_dialog_or_an_unknown_bot_is_answered_with_nothing(self) -> None:
        cancelled, spawn = await self._call({"cancelled": True})
        unknown, _ = await self._call(self._signed(), bot=False)
        assert (cancelled, unknown) == ({}, {})
        spawn.assert_not_called()

    async def test_an_unsigned_answer_is_refused(self) -> None:
        with pytest.raises(HTTPException) as refused:
            await self._call({**self._signed(), "state": "run-1:forged"})
        assert refused.value.status_code == 403


def test_a_bot_that_connects_out_gets_socket_mode_and_no_urls() -> None:
    from app.services.channels.slack_manifest import slack_manifest

    bot = MagicMock(id=uuid.uuid4(), webhook_mode=False)
    bot.name = "Helper"
    manifest = slack_manifest(bot)

    assert manifest["settings"]["socket_mode_enabled"] is True
    assert "request_url" not in manifest["settings"]["event_subscriptions"]
    assert "request_url" not in manifest["settings"]["interactivity"]
    assert "url" not in manifest["features"]["slash_commands"][0]
