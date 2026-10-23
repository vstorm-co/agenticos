"""Each chat app's half of greeting a new member (#2301).

Found by address, greeted in a direct chat with the bot - and somebody the
platform cannot find, or whose address it may not read, is "not found", never an
error: the greeting is a courtesy, and the next platform still tries.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.channels.base import ChannelAdapter
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.teams import ConversationRef, TeamsAdapter
from app.services.channels.teams_auth import TeamsCredentials
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio

SERVICE = "https://smba.trafficmanager.net/emea/"


async def test_a_platform_with_no_way_to_find_people_greets_nobody():
    adapter: ChannelAdapter = TelegramAdapter()
    try:
        assert await adapter.welcome("t", "ada@acme.com", "hi", api_base_url=None) is False
    finally:
        await adapter.aclose()


class TestSlack:
    @staticmethod
    def _client(lookup):
        client = MagicMock()
        client.users_lookupByEmail = lookup
        client.conversations_open = AsyncMock(return_value={"channel": {"id": "D1"}})
        client.chat_postMessage = AsyncMock()
        return client

    async def test_found_by_address_and_greeted_in_a_direct_message(self):
        client = self._client(AsyncMock(return_value={"user": {"id": "U1"}}))
        with patch.object(SlackAdapter, "_web", return_value=client):
            assert await SlackAdapter().welcome("x", "ada@acme.com", "hi", api_base_url=None)

        client.conversations_open.assert_awaited_once_with(users="U1")
        client.chat_postMessage.assert_awaited_once_with(channel="D1", text="hi")

    @pytest.mark.parametrize("error", ["users_not_found", "missing_scope"])
    async def test_somebody_not_in_the_workspace_or_an_old_app_is_not_found(self, error):
        from slack_sdk.errors import SlackApiError

        response = MagicMock()
        response.get = lambda key, default=None: error if key == "error" else default
        client = self._client(AsyncMock(side_effect=SlackApiError("no", response)))
        with patch.object(SlackAdapter, "_web", return_value=client):
            assert (
                await SlackAdapter().welcome("x", "ada@acme.com", "hi", api_base_url=None) is False
            )
        client.chat_postMessage.assert_not_awaited()

    async def test_any_other_slack_refusal_is_raised_for_the_caller_to_log(self):
        from slack_sdk.errors import SlackApiError

        response = MagicMock()
        response.get = lambda key, default=None: "ratelimited" if key == "error" else default
        client = self._client(AsyncMock(side_effect=SlackApiError("no", response)))
        with patch.object(SlackAdapter, "_web", return_value=client), pytest.raises(SlackApiError):
            await SlackAdapter().welcome("x", "ada@acme.com", "hi", api_base_url=None)


class TestMattermost:
    @staticmethod
    def _adapter(handler) -> MattermostAdapter:
        adapter = MattermostAdapter()
        adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return adapter

    async def test_found_by_address_and_greeted_in_a_direct_channel(self):
        posted: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v4/users/email/ada%40acme.com" or path.endswith(
                "/users/email/ada@acme.com"
            ):
                return httpx.Response(200, json={"id": "u1"})
            if path == "/api/v4/users/me":
                return httpx.Response(200, json={"id": "bot"})
            if path == "/api/v4/channels/direct":
                assert json.loads(request.content) == ["bot", "u1"]
                return httpx.Response(201, json={"id": "dm"})
            if path == "/api/v4/posts":
                posted.append(json.loads(request.content))
                return httpx.Response(201, json={"id": "p"})
            return httpx.Response(500)

        adapter = self._adapter(handler)
        assert await adapter.welcome(
            "tok", "ada@acme.com", "hi", api_base_url="https://chat.acme.com/"
        )
        assert posted == [{"channel_id": "dm", "message": "hi"}]

    @pytest.mark.parametrize("status", [403, 404])
    async def test_a_server_that_hides_addresses_is_not_found(self, status):
        adapter = self._adapter(lambda _request: httpx.Response(status))
        assert await adapter.welcome("tok", "a@b.c", "hi", api_base_url="https://chat") is False

    async def test_a_bot_with_no_server_greets_nobody(self):
        assert await MattermostAdapter().welcome("tok", "a@b.c", "hi", api_base_url=None) is False


class TestTeams:
    @staticmethod
    def _adapter(handler) -> TeamsAdapter:
        adapter = TeamsAdapter()
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter.auth.access_token = AsyncMock(return_value="tok")
        return adapter

    @staticmethod
    def _token() -> str:
        return TeamsCredentials(app_id="app", tenant_id="tenant", client_secret="s").encode()

    async def test_found_in_a_teams_roster_and_greeted_in_a_personal_chat(self):
        opened: list[dict] = []
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/pagedmembers"):
                if "continuationToken" not in request.url.params:
                    return httpx.Response(
                        200,
                        json={
                            "members": [{"id": "29:other", "email": "bob@acme.com"}],
                            "continuationToken": "n",
                        },
                    )
                return httpx.Response(
                    200, json={"members": [{"id": "29:ada", "userPrincipalName": "Ada@Acme.com"}]}
                )
            if path.endswith("/v3/conversations"):
                opened.append(json.loads(request.content))
                return httpx.Response(201, json={"id": "a:personal"})
            if path.endswith("/activities"):
                sent.append(json.loads(request.content))
                return httpx.Response(201, json={"id": "1"})
            return httpx.Response(500)

        adapter = self._adapter(handler)
        ref = ConversationRef(
            conversation_id="19:team", service_url=SERVICE, conversation_type="channel"
        )
        adapter.know(ref)

        assert await adapter.welcome(
            self._token(), "ada@acme.com", "hi", api_base_url=None, places=[ref.key]
        )
        assert opened[0]["members"] == [{"id": "29:ada"}]
        assert opened[0]["bot"] == {"id": "28:app"}
        assert opened[0]["tenantId"] == "tenant"
        assert sent == [{"type": "message", "text": "hi"}]

    async def test_nobody_on_any_roster_and_a_foreign_service_are_not_greeted(self):
        adapter = self._adapter(lambda _request: httpx.Response(200, json={"members": []}))
        roster = ConversationRef(
            conversation_id="19:team", service_url=SERVICE, conversation_type="channel"
        )
        foreign = ConversationRef(
            conversation_id="19:evil",
            service_url="https://evil.example/",
            conversation_type="channel",
        )
        adapter.know(roster)
        adapter.know(foreign)

        assert (
            await adapter.welcome(
                self._token(),
                "ada@acme.com",
                "hi",
                api_base_url=None,
                places=[foreign.key, roster.key],
            )
            is False
        )
        assert (
            await adapter.welcome(self._token(), "ada@acme.com", "hi", api_base_url=None) is False
        )
