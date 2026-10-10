"""A Slack bot as a Slack app: buttons, the assistant pane, App Home, `/agent` (#2067)."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from app.api.routes.v1.slack_webhook import slack_commands, slack_events, slack_interactions
from app.services.channels.base import ChannelChoice, IncomingPress, PromptMessage
from app.services.channels.slack import SlackAdapter
from app.services.channels.slack_app import (
    SUGGESTED_PROMPTS,
    SlackSurfaces,
    parse_command,
    parse_press,
    parse_shortcut,
)
from app.services.channels.slack_manifest import SHORTCUT_ID, slack_manifest

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()


def _web() -> MagicMock:
    client = MagicMock()
    for method in (
        "chat_postMessage",
        "chat_update",
        "assistant_threads_setStatus",
        "assistant_threads_setSuggestedPrompts",
        "views_publish",
        "chat_unfurl",
    ):
        setattr(client, method, AsyncMock(return_value={"ts": "1.5"}))
    return client


class TestButtonsInSlack:
    async def test_a_prompt_is_a_section_and_a_row_of_styled_buttons_in_its_thread(self):
        client = _web()
        prompt = PromptMessage(
            platform_chat_id="C1:1.0",
            text="Approve it?",
            choices=[
                ChannelChoice(label="Approve", value="aos:1:0", style="primary"),
                ChannelChoice(label="x" * 90, value="aos:1:1"),
            ],
        )
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().send_prompt("xoxb", prompt)

        sent = client.chat_postMessage.await_args.kwargs
        assert (sent["channel"], sent["thread_ts"]) == ("C1", "1.0")
        buttons = sent["blocks"][1]["elements"]
        assert buttons[0] == {
            "type": "button",
            "action_id": "aos_0",
            "text": {"type": "plain_text", "text": "Approve"},
            "value": "aos:1:0",
            "style": "primary",
        }
        assert len(buttons[1]["text"]["text"]) == 75 and "style" not in buttons[1]

    async def test_a_prompt_at_the_top_of_a_channel_is_not_threaded(self):
        client = _web()
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().send_prompt(
                "xoxb", PromptMessage(platform_chat_id="D1", text="?", choices=[])
            )

        assert "thread_ts" not in client.chat_postMessage.await_args.kwargs

    async def test_a_pressed_prompt_keeps_its_question_and_loses_its_buttons(self):
        client = _web()
        press = IncomingPress(
            platform="slack",
            bot_id="b",
            platform_user_id="U",
            platform_chat_id="C1:1.0",
            value="v",
            message_id="2.0",
            prompt_text="How formal?",
        )
        with patch.object(SlackAdapter, "_web", return_value=client):
            await SlackAdapter().settle_prompt("xoxb", press, "Answered: Casual")
            press.prompt_text = None
            await SlackAdapter().settle_prompt("xoxb", press, "Skipped.")
            press.message_id = None
            await SlackAdapter().settle_prompt("xoxb", press, "Skipped.")

        first, second = client.chat_update.await_args_list
        assert first.kwargs["text"] == "How formal?\n*Answered: Casual*"
        assert first.kwargs["ts"] == "2.0" and first.kwargs["channel"] == "C1"
        assert second.kwargs["text"] == "*Skipped.*"


class TestTheAssistantPane:
    async def test_a_threaded_reply_says_the_agent_is_thinking_first(self):
        client = _web()
        with patch.object(SlackAdapter, "_web", return_value=client):
            handle = await SlackAdapter().begin_reply(
                "xoxb", MagicMock(platform_chat_id="D1:1.0", text="…")
            )

        assert handle == "1.5"
        assert client.assistant_threads_setStatus.await_args.kwargs == {
            "channel_id": "D1",
            "thread_ts": "1.0",
            "status": "is thinking…",
        }

    async def test_a_thread_that_is_not_an_assistant_thread_still_gets_its_answer(self):
        client = _web()
        client.assistant_threads_setStatus.side_effect = RuntimeError("not_allowed")
        with patch.object(SlackAdapter, "_web", return_value=client):
            handle = await SlackAdapter().begin_reply(
                "xoxb", MagicMock(platform_chat_id="C1:1.0", text="…")
            )

        assert handle == "1.5"


def _bot() -> MagicMock:
    bot = MagicMock(id=uuid.uuid4(), organization_id=ORG)
    bot.name = "Support"
    return bot


class TestSurfaces:
    async def _handle(self, payload: dict[str, Any], **patches: Any) -> MagicMock:
        client = _web()
        module = "app.services.channels.slack_app"
        with (
            patch(f"{module}._client", return_value=client),
            patch(f"{module}.unseal_bot_token", return_value="xoxb"),
            patch(
                f"{module}.agent_exposure_repo.bound_to_bot",
                new=AsyncMock(return_value=patches.get("binding")),
            ),
            patch(f"{module}.agent_repo.get", new=AsyncMock(return_value=patches.get("agent"))),
            patch(
                f"{module}.channel_identity_repo.get_by_platform_user",
                new=AsyncMock(return_value=patches.get("identity")),
            ),
            patch(
                f"{module}.agent_run_repo.count_pending_approval_runs",
                new=AsyncMock(return_value=patches.get("waiting", 0)),
            ),
        ):
            await SlackSurfaces(MagicMock()).handle(payload, _bot())
        return client

    def _agent(self) -> MagicMock:
        agent = MagicMock(description="Answers refund questions")
        agent.name = "Refunds"
        return agent

    async def test_app_home_names_the_agent_and_what_waits_on_a_linked_person(self):
        client = await self._handle(
            {"event": {"type": "app_home_opened", "tab": "home", "user": "U1"}},
            binding=MagicMock(agent_id=uuid.uuid4()),
            agent=self._agent(),
            identity=MagicMock(user_id=uuid.uuid4()),
            waiting=2,
        )

        view = client.views_publish.await_args.kwargs["view"]
        text = json.dumps(view)
        assert view["type"] == "home"
        assert "*Refunds*\\nAnswers refund questions" in text
        assert "*2* of your runs wait for an approval" in text
        assert "Ask the AI Architect" in text

    async def test_app_home_asks_an_unlinked_person_to_link(self):
        client = await self._handle(
            {"event": {"type": "app_home_opened", "tab": "home", "user": "U1"}}
        )

        text = json.dumps(client.views_publish.await_args.kwargs["view"])
        assert "/link" in text and "Refunds" not in text

    async def test_app_home_with_nothing_waiting_says_so(self):
        client = await self._handle(
            {"event": {"type": "app_home_opened", "tab": "home", "user": "U1"}},
            identity=MagicMock(user_id=uuid.uuid4()),
        )

        assert "Nothing of yours is waiting" in json.dumps(
            client.views_publish.await_args.kwargs["view"]
        )

    async def test_the_messages_tab_is_not_home(self):
        client = await self._handle(
            {"event": {"type": "app_home_opened", "tab": "messages", "user": "U1"}}
        )

        client.views_publish.assert_not_awaited()

    async def test_a_new_assistant_thread_is_offered_prompts(self):
        client = await self._handle(
            {
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"channel_id": "D1", "thread_ts": "1.0"},
                }
            }
        )

        sent = client.assistant_threads_setSuggestedPrompts.await_args.kwargs
        assert (sent["channel_id"], sent["thread_ts"]) == ("D1", "1.0")
        assert len(sent["prompts"]) == len(SUGGESTED_PROMPTS)

    async def test_a_console_link_to_an_agent_of_this_organization_unfurls(self):
        agent_id = uuid.uuid4()
        with patch("app.services.channels.slack_app.settings.FRONTEND_URL", "https://console.acme"):
            client = await self._handle(
                {
                    "event": {
                        "type": "link_shared",
                        "channel": "C1",
                        "message_ts": "1.0",
                        "links": [
                            {"url": f"https://console.acme/agents/{agent_id}"},
                            {"url": f"https://elsewhere.example/agents/{agent_id}"},
                            {"url": "https://console.acme/runs"},
                        ],
                    }
                },
                agent=self._agent(),
            )

        unfurls = client.chat_unfurl.await_args.kwargs["unfurls"]
        assert list(unfurls) == [f"https://console.acme/agents/{agent_id}"]
        assert unfurls[f"https://console.acme/agents/{agent_id}"]["title"] == "Refunds"

    async def test_a_link_to_an_agent_of_another_organization_does_not_unfurl(self):
        with patch("app.services.channels.slack_app.settings.FRONTEND_URL", "https://console.acme"):
            client = await self._handle(
                {
                    "event": {
                        "type": "link_shared",
                        "links": [{"url": f"https://console.acme/agents/{uuid.uuid4()}"}],
                    }
                },
                agent=None,
            )

        client.chat_unfurl.assert_not_awaited()

    def test_the_client_speaks_with_the_bot_s_own_token(self):
        from app.services.channels.slack_app import _client

        assert _client("xoxb-1").token == "xoxb-1"

    async def test_nothing_to_unfurl_calls_nothing(self):
        client = await self._handle(
            {"event": {"type": "link_shared", "links": [{"url": "https://x.example"}]}}
        )

        client.chat_unfurl.assert_not_awaited()

    async def test_a_failure_is_logged_and_not_raised(self):
        client = _web()
        client.views_publish.side_effect = RuntimeError("boom")
        with (
            patch("app.services.channels.slack_app._client", return_value=client),
            patch("app.services.channels.slack_app.unseal_bot_token", return_value="xoxb"),
            patch(
                "app.services.channels.slack_app.agent_exposure_repo.bound_to_bot",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.channels.slack_app.channel_identity_repo.get_by_platform_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            await SlackSurfaces(MagicMock()).handle(
                {"event": {"type": "app_home_opened", "tab": "home", "user": "U1"}}, _bot()
            )


class TestParsing:
    def test_a_button_press_carries_who_where_and_what(self):
        press = parse_press(
            {
                "type": "block_actions",
                "user": {"id": "U1", "username": "ada"},
                "channel": {"id": "C1"},
                "message": {"ts": "2.0", "thread_ts": "1.0", "text": "Approve it?"},
                "actions": [{"value": "aos:abc:0"}],
            },
            "bot-1",
        )

        assert press == IncomingPress(
            platform="slack",
            bot_id="bot-1",
            platform_user_id="U1",
            platform_chat_id="C1:1.0",
            value="aos:abc:0",
            platform_username="ada",
            message_id="2.0",
            prompt_text="Approve it?",
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {"type": "view_submission"},
            {"type": "block_actions", "actions": []},
            {"type": "block_actions", "actions": [{"url": "https://x"}]},
        ],
    )
    def test_anything_but_a_valued_button_is_not_a_press(self, payload: dict[str, Any]):
        assert parse_press(payload, "bot-1") is None

    def test_a_press_outside_a_thread_keys_on_the_channel(self):
        press = parse_press(
            {
                "type": "block_actions",
                "channel": {"id": "D1"},
                "container": {"message_ts": "3.0"},
                "actions": [{"value": "v"}],
            },
            "b",
        )

        assert press is not None
        assert (press.platform_chat_id, press.message_id) == ("D1", "3.0")

    def test_the_message_shortcut_asks_about_the_message_in_its_thread(self):
        incoming = parse_shortcut(
            {
                "type": "message_action",
                "callback_id": SHORTCUT_ID,
                "trigger_id": "T1",
                "user": {"id": "U1"},
                "channel": {"id": "C1"},
                "message": {"ts": "5.0", "text": "Our invoice is late\nagain"},
            },
            "bot-1",
        )

        assert incoming is not None
        assert incoming.text == "Help me with this message:\n> Our invoice is late\n> again"
        assert incoming.platform_chat_id == "C1:5.0"
        assert (incoming.chat_type, incoming.addressed) == ("group", True)

    def test_another_shortcut_is_not_ours(self):
        assert parse_shortcut({"type": "message_action", "callback_id": "x"}, "b") is None

    def test_agent_command_is_a_message_addressed_to_the_bot(self):
        incoming = parse_command(
            {"text": " refund window? ", "channel_id": "D9", "user_id": "U1", "trigger_id": "T"},
            "bot-1",
        )

        assert incoming is not None
        assert (incoming.text, incoming.chat_type, incoming.addressed) == (
            "refund window?",
            "private",
            True,
        )

    @pytest.mark.parametrize("form", [{"text": "", "channel_id": "C1"}, {"text": "hi"}])
    def test_an_empty_command_is_nothing(self, form: dict[str, str]):
        assert parse_command(form, "bot-1") is None


class TestTheManifest:
    def test_it_points_every_request_at_this_bot_on_this_deployment(self):
        bot = _bot()
        with (
            patch(
                "app.services.channels.slack_manifest.settings.PUBLIC_BASE_URL", "https://api.acme/"
            ),
            patch(
                "app.services.channels.slack_manifest.settings.FRONTEND_URL", "https://console.acme"
            ),
        ):
            manifest = slack_manifest(bot)

        settings_ = manifest["settings"]
        assert settings_["event_subscriptions"]["request_url"] == (
            f"https://api.acme/api/v1/slack/{bot.id}/events"
        )
        assert settings_["interactivity"]["request_url"] == (
            f"https://api.acme/api/v1/slack/{bot.id}/interactions"
        )
        assert manifest["features"]["slash_commands"][0]["url"].endswith("/commands")
        assert manifest["features"]["shortcuts"][0]["callback_id"] == SHORTCUT_ID
        assert manifest["features"]["unfurl_domains"] == ["console.acme"]
        assert "assistant:write" in manifest["oauth_config"]["scopes"]["bot"]
        assert "assistant_thread_started" in settings_["event_subscriptions"]["bot_events"]

    def test_a_console_with_no_host_unfurls_nothing(self):
        with patch("app.services.channels.slack_manifest.settings.FRONTEND_URL", ""):
            assert slack_manifest(_bot())["features"]["unfurl_domains"] == []


_ROUTES = "app.api.routes.v1._slack_requests"
_WEBHOOK = "app.api.routes.v1.slack_webhook"


def _form_request(form: dict[str, str]) -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=urlencode(form).encode())
    request.headers = {}
    return request


def _bot_service(bot: MagicMock | None) -> MagicMock:
    return MagicMock(find_active=AsyncMock(return_value=bot))


class TestTheRequestURLs:
    @pytest.fixture(autouse=True)
    def _signed(self):
        adapter = MagicMock()
        adapter.verify_webhook_signature.return_value = True
        with (
            patch(f"{_ROUTES}.get_adapter", return_value=adapter),
            patch(f"{_ROUTES}.unseal_slack_signing_secret", return_value="secret"),
            patch(f"{_WEBHOOK}.spawn") as spawn,
        ):
            self.spawn = spawn
            self.adapter = adapter
            yield

    def _payload(self, payload: dict[str, Any]) -> MagicMock:
        return _form_request({"payload": json.dumps(payload)})

    async def test_a_press_is_handled_in_the_background(self):
        await slack_interactions(
            uuid.uuid4(),
            self._payload(
                {"type": "block_actions", "channel": {"id": "C"}, "actions": [{"value": "v"}]}
            ),
            _bot_service(MagicMock()),
        )

        assert self.spawn.call_args.kwargs["name"].startswith("slack_press:")
        self.spawn.call_args.args[0].close()

    async def test_a_shortcut_is_run_as_a_message(self):
        await slack_interactions(
            uuid.uuid4(),
            self._payload(
                {"type": "message_action", "callback_id": SHORTCUT_ID, "message": {"text": "x"}}
            ),
            _bot_service(MagicMock()),
        )

        assert self.spawn.call_args.kwargs["name"].startswith("slack_shortcut:")
        self.spawn.call_args.args[0].close()

    async def test_anything_else_is_acknowledged_and_dropped(self):
        response = await slack_interactions(
            uuid.uuid4(), self._payload({"type": "view_closed"}), _bot_service(MagicMock())
        )

        assert response.status_code == 200
        self.spawn.assert_not_called()

    async def test_an_unknown_bot_is_answered_empty(self):
        response = await slack_interactions(
            uuid.uuid4(), self._payload({"type": "block_actions"}), _bot_service(None)
        )
        commands = await slack_commands(uuid.uuid4(), _form_request({}), _bot_service(None))

        assert (response.status_code, commands.status_code) == (200, 200)

    @pytest.mark.security
    async def test_an_unsigned_press_is_refused(self):
        self.adapter.verify_webhook_signature.return_value = False

        with pytest.raises(HTTPException) as refused:
            await slack_interactions(
                uuid.uuid4(), self._payload({"type": "block_actions"}), _bot_service(MagicMock())
            )

        assert refused.value.status_code == 403
        self.spawn.assert_not_called()

    async def test_agent_command_runs_and_an_empty_one_explains_itself(self):
        await slack_commands(
            uuid.uuid4(),
            _form_request({"text": "hi", "channel_id": "C1", "user_id": "U1"}),
            _bot_service(MagicMock()),
        )
        assert self.spawn.call_args.kwargs["name"].startswith("slack_command:")
        self.spawn.call_args.args[0].close()

        empty = await slack_commands(
            uuid.uuid4(), _form_request({"channel_id": "C1"}), _bot_service(MagicMock())
        )
        assert empty["response_type"] == "ephemeral"

    async def test_a_surface_event_is_not_routed_as_a_message(self):
        adapter = MagicMock()
        adapter.verify_webhook_signature.return_value = True
        payload = {"type": "event_callback", "event": {"type": "app_home_opened"}}
        request = MagicMock()
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.json = AsyncMock(return_value=payload)
        request.headers = {}
        with (
            patch(f"{_WEBHOOK}.get_adapter", return_value=adapter),
            patch(f"{_WEBHOOK}.unseal_slack_signing_secret", return_value="secret"),
        ):
            await slack_events(uuid.uuid4(), request, _bot_service(MagicMock()))

        assert self.spawn.call_args.kwargs["name"].startswith("slack_surface:")
        self.spawn.call_args.args[0].close()
        adapter.parse_incoming.assert_not_called()


class TestSocketMode:
    async def test_presses_shortcuts_and_commands_reach_the_same_handlers(self):
        adapter = SlackAdapter()
        with (
            patch(
                "app.worker.background.channel.process_channel_press", new=AsyncMock()
            ) as pressed,
            patch("app.worker.background.channel.process_channel_event", new=AsyncMock()) as asked,
        ):
            await adapter._handle_interaction(
                "interactive",
                {"type": "block_actions", "channel": {"id": "C"}, "actions": [{"value": "v"}]},
                "b",
            )
            await adapter._handle_interaction(
                "interactive",
                {"type": "message_action", "callback_id": SHORTCUT_ID, "message": {"text": "x"}},
                "b",
            )
            await adapter._handle_interaction(
                "slash_commands", {"text": "hi", "channel_id": "C1", "user_id": "U"}, "b"
            )
            await adapter._handle_interaction("slash_commands", {"text": ""}, "b")
            await adapter._handle_interaction("interactive", {"type": "view_closed"}, "b")

        assert pressed.await_count == 1
        assert asked.await_count == 2

    async def test_a_surface_event_over_the_socket_is_handled_as_one(self):
        with patch(
            "app.worker.background.channel.process_slack_surface", new=AsyncMock()
        ) as surface:
            await SlackAdapter()._handle_event({"event": {"type": "link_shared"}}, "b")

        surface.assert_awaited_once()
