"""The Teams adapter: reading activities, and answering through the Bot Connector (#1985).

The Connector is an `httpx.MockTransport` that records every call, so what is
asserted is the request Teams would receive: the conversation and thread it is
addressed to, the token it carries, and what a card or a file looks like.
"""

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import httpx2
import pytest

from app.core.pinned_http import PinnedAsyncClient
from app.services.channels import teams
from app.services.channels.base import (
    ChannelChoice,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.teams import (
    FILE_CONSENT_CARD,
    FILE_DOWNLOAD_INFO,
    MESSAGE_LIMIT_BYTES,
    ConversationRef,
    TeamsAdapter,
    _chunks,
    chat_id_of,
    conversation_key,
    conversation_of,
    teams_adapter,
)
from app.services.channels.teams_auth import TeamsCredentials

pytestmark = pytest.mark.anyio

APP_ID = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
SERVICE = "https://smba.trafficmanager.net/emea/"
PERSONAL = "a:1" + "x" * 140
CHANNEL = "19:abc@thread.tacv2"
TOKEN = TeamsCredentials(APP_ID, TENANT, "secret").encode()


@asynccontextmanager
async def _no_db() -> AsyncIterator[MagicMock]:
    """The session the adapter opens to read a conversation; the repository is patched."""
    yield MagicMock()


def _activity(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "message",
        "id": "1700000000001",
        "serviceUrl": SERVICE,
        "channelId": "msteams",
        "from": {"id": "29:pairwise", "name": "Ada", "aadObjectId": "aad-ada"},
        "recipient": {"id": f"28:{APP_ID}", "name": "Support"},
        "conversation": {"id": PERSONAL, "conversationType": "personal", "tenantId": TENANT},
        "text": "hello",
    }
    return {**base, **overrides}


def _in_channel(conversation_id: str = CHANNEL, **overrides: Any) -> dict[str, Any]:
    return _activity(
        conversation={"id": conversation_id, "conversationType": "channel", "tenantId": TENANT},
        channelData={"channel": {"name": "General"}, "team": {"name": "Platform"}},
        **overrides,
    )


class _Connector:
    """A Bot Connector that records what it was asked and answers each call."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.answers: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        if url.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        for fragment, response in self.answers.items():
            if fragment in url:
                return response
        return httpx.Response(200, json={"id": "sent-1"})

    def posts(self) -> list[httpx.Request]:
        return [call for call in self.calls if "/v3/conversations/" in str(call.url)]

    @staticmethod
    def body(call: httpx.Request) -> dict[str, Any]:
        return json.loads(call.content)


class _Outside:
    """Addresses outside the Connector - SharePoint - recording what reached them."""

    def __init__(self) -> None:
        self.calls: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        return httpx2.Response(200, content=b"file-bytes")


@pytest.fixture
def connector() -> _Connector:
    return _Connector()


@pytest.fixture
def outside() -> _Outside:
    return _Outside()


@pytest.fixture
def resolves_to(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """What each outside name resolves to; a public address unless a test says otherwise."""
    answers: dict[str, str] = {}

    def fake(host: str, port: int, **_kwargs: object) -> list[tuple]:
        return [(2, 1, 6, "", (answers.get(host, "52.108.0.10"), port))]

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake)
    return answers


@pytest.fixture
def adapter(connector: _Connector, outside: _Outside, resolves_to: dict[str, str]) -> TeamsAdapter:
    built = TeamsAdapter()
    built._client = httpx.AsyncClient(transport=httpx.MockTransport(connector))
    built._outside = PinnedAsyncClient(
        timeout=httpx2.Timeout(5.0), transport=httpx2.MockTransport(outside)
    )
    built.auth._client = built._client
    built.remember(
        "bot-1",
        TeamsCredentials.decode(TOKEN),
        ConversationRef(PERSONAL, SERVICE, "personal", TENANT),
    )
    built.know(ConversationRef(CHANNEL, SERVICE, "channel", TENANT, "General"))
    return built


class TestReadingAnActivity:
    @pytest.mark.security
    @pytest.mark.parametrize("flood", ["<" * 50_000, "<at" * 50_000, "<at>a" * 50_000])
    def test_markup_nobody_closes_is_read_in_linear_time(self, flood: str) -> None:
        """CodeQL on #2324: each scan used to run to the end of the text from every
        `<`, quadratic in a message the sender writes. Seconds at this size then;
        the suite's timeout is the bound now."""
        assert teams._plain(flood + " <b>end</b>", []).endswith(" end")

    def test_mentions_and_markup_come_out_as_written(self) -> None:
        text = '<at>Support</at> hi <b>there</b> &amp; <at id="1">Ada Lovelace</at>'
        assert teams._plain(text, ["<at>Support</at>"]) == "hi there & @Ada Lovelace"

    def test_a_conversation_is_known_by_a_short_key_without_colons(self) -> None:
        key = conversation_key(PERSONAL)
        assert len(key) == 32 and ":" not in key
        assert conversation_key(PERSONAL) == key

    def test_a_personal_chat_is_one_conversation(self) -> None:
        """No threads in a chat: every message continues the same conversation."""
        assert chat_id_of(_activity()) == conversation_key(PERSONAL)
        assert chat_id_of(_activity(id="other")) == conversation_key(PERSONAL)

    def test_a_new_channel_post_roots_its_own_thread(self) -> None:
        assert chat_id_of(_in_channel()) == f"{conversation_key(CHANNEL)}:1700000000001"

    def test_a_reply_in_a_channel_thread_keys_on_the_thread(self) -> None:
        activity = _in_channel(f"{CHANNEL};messageid=1699999999999", id="1700000000005")
        assert chat_id_of(activity) == f"{conversation_key(CHANNEL)}:1699999999999"

    def test_the_conversation_drops_the_thread_and_keeps_where_it_lives(self) -> None:
        ref = conversation_of(_in_channel(f"{CHANNEL};messageid=1"))
        assert ref == ConversationRef(CHANNEL, SERVICE, "channel", TENANT, "General")

    @pytest.mark.parametrize(
        "activity", [{"type": "message"}, {"conversation": {"id": "x"}, "serviceUrl": 3}]
    )
    def test_an_activity_naming_no_conversation_has_none(self, activity: dict) -> None:
        assert conversation_of(activity) is None
        assert chat_id_of(activity) is None

    def test_the_sender_is_their_entra_object_id(self, adapter: TeamsAdapter) -> None:
        incoming = adapter.parse_incoming(_activity(), "bot-1")
        assert incoming is not None
        assert incoming.platform_user_id == "aad-ada"
        assert incoming.chat_type == "private"
        assert incoming.addressed is None

    def test_the_bots_own_mention_is_removed_and_others_kept(self, adapter: TeamsAdapter) -> None:
        activity = _in_channel(
            text="<at>Support</at> ask <at>Bob</at> about &amp; the plan",
            entities=[
                {
                    "type": "mention",
                    "mentioned": {"id": f"28:{APP_ID}"},
                    "text": "<at>Support</at>",
                },
                {"type": "mention", "mentioned": {"id": "29:bob"}, "text": "<at>Bob</at>"},
            ],
        )
        incoming = adapter.parse_incoming(activity, "bot-1")
        assert incoming is not None
        assert incoming.text == "ask @Bob about & the plan"
        assert incoming.addressed is True
        assert incoming.chat_type == "group"

    def test_a_channel_message_not_naming_the_bot_is_not_addressed(
        self, adapter: TeamsAdapter
    ) -> None:
        incoming = adapter.parse_incoming(_in_channel(text="just chatting"), "bot-1")
        assert incoming is not None and incoming.addressed is False

    def test_files_and_pasted_pictures_arrive_as_attachments(self, adapter: TeamsAdapter) -> None:
        activity = _activity(
            text="",
            attachments=[
                {"contentType": "text/html", "content": "<p>dup</p>"},
                {
                    "contentType": FILE_DOWNLOAD_INFO,
                    "name": "q3.pdf",
                    "content": {"downloadUrl": "https://tenant.sharepoint.com/q3.pdf"},
                },
                {"contentType": FILE_DOWNLOAD_INFO, "name": "nourl.pdf", "content": {}},
                {"contentType": "image/png", "contentUrl": f"{SERVICE}v3/attachments/1"},
            ],
        )
        incoming = adapter.parse_incoming(activity, "bot-1")
        assert incoming is not None
        assert [(a.filename, a.mime_type) for a in incoming.attachments] == [
            ("q3.pdf", "application/pdf"),
            ("image.png", "image/png"),
        ]

    @pytest.mark.parametrize(
        "activity",
        [
            _activity(type="conversationUpdate"),
            _activity(text=""),
            _activity(**{"from": {}}),
            {"type": "message", "from": {"id": "29:x"}},
        ],
    )
    def test_nothing_to_answer_is_nothing(self, adapter: TeamsAdapter, activity: dict) -> None:
        assert adapter.parse_incoming(activity, "bot-1") is None


class TestAPressOnACard:
    def _invoke(self, **value: Any) -> dict[str, Any]:
        return _activity(
            type="invoke",
            name="adaptiveCard/action",
            replyToId="card-1",
            value={"action": {"type": "Action.Execute", "verb": "aos", **value}},
        )

    @pytest.mark.security
    def test_it_is_recorded_against_who_pressed(self, adapter: TeamsAdapter) -> None:
        press = adapter.parse_press(self._invoke(data={"aos": "aos:p1:0"}), "bot-1")
        assert press == IncomingPress(
            platform="teams",
            bot_id="bot-1",
            platform_user_id="aad-ada",
            platform_chat_id=conversation_key(PERSONAL),
            value="aos:p1:0",
            platform_username="Ada",
            message_id="card-1",
        )

    @pytest.mark.parametrize(
        "activity",
        [
            _activity(type="invoke", name="fileConsent/invoke"),
            _activity(
                type="invoke",
                name="adaptiveCard/action",
                value={"action": {"verb": "other", "data": {"aos": "x"}}},
            ),
            _activity(
                type="invoke",
                name="adaptiveCard/action",
                value={"action": {"verb": "aos", "data": {"aos": 3}}},
            ),
            _activity(
                type="invoke",
                name="adaptiveCard/action",
                value={"action": {"verb": "aos", "data": {"aos": "x"}}},
                **{"from": {}},
            ),
        ],
    )
    def test_anything_else_is_not_a_press(self, adapter: TeamsAdapter, activity: dict) -> None:
        assert adapter.parse_press(activity, "bot-1") is None


class TestAnswering:
    async def test_a_reply_goes_to_the_conversation_with_the_bots_token(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        await adapter.send_message(
            TOKEN, OutgoingMessage(platform_chat_id=conversation_key(PERSONAL), text="**hi**")
        )

        (post,) = connector.posts()
        assert str(post.url) == f"{SERVICE}v3/conversations/{PERSONAL}/activities"
        assert post.headers["authorization"] == "Bearer bot-token"
        assert connector.body(post) == {
            "type": "message",
            "text": "**hi**",
            "textFormat": "markdown",
            "attachments": [],
        }

    async def test_a_channel_answer_lands_in_its_thread(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        chat = f"{conversation_key(CHANNEL)}:1700000000001"
        await adapter.send_message(TOKEN, OutgoingMessage(platform_chat_id=chat, text="ok"))

        (post,) = connector.posts()
        assert f"/v3/conversations/{CHANNEL};messageid=1700000000001/activities" in str(post.url)

    async def test_a_long_answer_is_split_and_the_picture_rides_the_last_piece(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        text = ("line of text\n" * 4000)[: MESSAGE_LIMIT_BYTES + 500]
        await adapter.send_message(
            TOKEN,
            OutgoingMessage(
                platform_chat_id=conversation_key(PERSONAL), text=text, image_png=b"PNG"
            ),
        )

        first, last = connector.posts()
        assert connector.body(first)["attachments"] == []
        (picture,) = connector.body(last)["attachments"]
        assert picture["contentUrl"] == f"data:image/png;base64,{base64.b64encode(b'PNG').decode()}"
        assert connector.body(first)["text"] + connector.body(last)["text"] == text

    async def test_a_picture_with_no_text_is_still_posted(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        await adapter.send_message(
            TOKEN,
            OutgoingMessage(
                platform_chat_id=conversation_key(PERSONAL),
                text="",
                attachments=[OutgoingAttachment("chart.webp", b"W", "image/webp")],
            ),
        )
        (post,) = connector.posts()
        assert connector.body(post)["attachments"][0]["contentType"] == "image/webp"

    async def test_a_file_in_a_channel_is_named_not_dropped(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        await adapter.send_message(
            TOKEN,
            OutgoingMessage(
                platform_chat_id=f"{conversation_key(CHANNEL)}:1",
                text="",
                attachments=[OutgoingAttachment("q3.xlsx", b"data", "application/vnd.ms-excel")],
            ),
        )
        (post,) = connector.posts()
        assert "q3.xlsx" in connector.body(post)["text"]

    async def test_a_file_in_a_personal_chat_waits_for_consent(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        redis = MagicMock(set=AsyncMock(return_value=True))
        with patch.object(teams, "_pending_files", redis):
            await adapter.send_message(
                TOKEN,
                OutgoingMessage(
                    platform_chat_id=conversation_key(PERSONAL),
                    text="",
                    attachments=[OutgoingAttachment("q3.xlsx", b"data", "application/x")],
                ),
            )

        (post,) = connector.posts()
        (card,) = connector.body(post)["attachments"]
        assert card["contentType"] == FILE_CONSENT_CARD
        assert card["content"]["sizeInBytes"] == 4
        key, stored = redis.set.await_args.args
        assert key == f"teams:file:{card['content']['acceptContext']['pending']}"
        assert base64.b64decode(stored) == b"data"

    async def test_an_unknown_conversation_cannot_be_answered(self, adapter: TeamsAdapter) -> None:
        with (
            patch(
                "app.repositories.teams_conversation_repo.get_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch("app.db.session.get_db_context", new=_no_db),
            pytest.raises(ChannelNotConfigured),
        ):
            await adapter.send_message(TOKEN, OutgoingMessage(platform_chat_id="f" * 32, text="x"))

    async def test_a_conversation_is_read_back_after_a_restart(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        row = MagicMock(
            conversation_id="19:later@thread.v2",
            service_url=SERVICE,
            conversation_type="groupChat",
            tenant_id=TENANT,
        )
        row.name = "Ops"
        with (
            patch(
                "app.repositories.teams_conversation_repo.get_by_key",
                new=AsyncMock(return_value=row),
            ),
            patch("app.db.session.get_db_context", new=_no_db),
        ):
            await adapter.send_message(
                TOKEN,
                OutgoingMessage(platform_chat_id=conversation_key("19:later@thread.v2"), text="x"),
            )
        (post,) = connector.posts()
        assert "/v3/conversations/19:later@thread.v2/activities" in str(post.url)

    @pytest.mark.security
    async def test_a_service_that_is_not_a_connector_never_gets_the_token(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        adapter.know(ConversationRef("19:x", "https://attacker.example/", "channel"))
        with pytest.raises(ChannelNotConfigured):
            await adapter.send_message(
                TOKEN, OutgoingMessage(platform_chat_id=conversation_key("19:x"), text="x")
            )
        assert connector.calls == []

    async def test_a_reply_is_begun_then_rewritten_in_place(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        chat = conversation_key(PERSONAL)
        handle = await adapter.begin_reply(TOKEN, OutgoingMessage(platform_chat_id=chat, text="…"))
        await adapter.update_reply(TOKEN, OutgoingMessage(platform_chat_id=chat, text="done"), "a1")

        assert handle == "sent-1"
        put = connector.posts()[-1]
        assert put.method == "PUT" and str(put.url).endswith("/activities/a1")
        assert connector.body(put)["text"] == "done"

    async def test_typing_is_shown_for_a_bot_it_has_heard_from(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        chat = conversation_key(PERSONAL)
        await adapter.typing("bot-1", OutgoingMessage(platform_chat_id=chat, text=""))
        await adapter.typing("never-heard", OutgoingMessage(platform_chat_id=chat, text=""))

        (post,) = connector.posts()
        assert connector.body(post) == {"type": "typing"}

    async def test_typing_that_fails_is_silent(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        connector.answers["/activities"] = httpx.Response(502)
        await adapter.typing(
            "bot-1", OutgoingMessage(platform_chat_id=conversation_key(PERSONAL), text="")
        )


class TestApprovalsAsCards:
    async def test_each_choice_is_a_button_that_posts_back(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        await adapter.send_prompt(
            TOKEN,
            PromptMessage(
                platform_chat_id=conversation_key(PERSONAL),
                text="Send the invoice?",
                choices=[
                    ChannelChoice("Approve", "aos:p:0", "primary"),
                    ChannelChoice("Reject", "aos:p:1", "danger"),
                    ChannelChoice("Later", "aos:p:2"),
                ],
            ),
        )

        (post,) = connector.posts()
        card = connector.body(post)["attachments"][0]["content"]
        assert card["body"][0]["text"] == "Send the invoice?"
        assert [(a["type"], a["data"], a.get("style")) for a in card["actions"]] == [
            ("Action.Execute", {"aos": "aos:p:0"}, "positive"),
            ("Action.Execute", {"aos": "aos:p:1"}, "destructive"),
            ("Action.Execute", {"aos": "aos:p:2"}, None),
        ]

    async def test_the_pressed_card_becomes_what_was_chosen(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        press = IncomingPress(
            "teams", "bot-1", "aad-ada", conversation_key(PERSONAL), "aos:p:0", message_id="c1"
        )
        await adapter.settle_prompt(TOKEN, press, "Approved by Ada")
        await adapter.settle_prompt(TOKEN, IncomingPress("teams", "b", "u", "c", "v"), "x")

        (put,) = connector.posts()
        assert str(put.url).endswith("/activities/c1")
        assert connector.body(put)["text"] == "Approved by Ada"


class TestAFileThePersonAccepted:
    def _consent(
        self, action: str, upload_url: str = "https://tenant-my.sharepoint.com/up"
    ) -> dict:
        return _activity(
            type="invoke",
            name="fileConsent/invoke",
            value={
                "action": action,
                "context": {"pending": "p1", "name": "q3.xlsx"},
                "uploadInfo": {
                    "uploadUrl": upload_url,
                    "contentUrl": "https://tenant-my.sharepoint.com/q3.xlsx",
                    "name": "q3.xlsx",
                    "uniqueId": "u1",
                    "fileType": "xlsx",
                },
            },
        )

    async def test_it_is_uploaded_and_posted(
        self, adapter: TeamsAdapter, connector: _Connector, outside: _Outside
    ) -> None:
        redis = MagicMock(getdel=AsyncMock(return_value=base64.b64encode(b"data").decode()))
        with patch.object(teams, "_pending_files", redis):
            await adapter.complete_file_consent(
                TOKEN, self._consent("accept"), conversation_key(PERSONAL)
            )

        (upload,) = outside.calls
        assert upload.method == "PUT" and upload.content == b"data"
        assert "authorization" not in upload.headers
        assert upload.headers["content-range"] == "bytes 0-3/4"
        (post,) = connector.posts()
        assert connector.body(post)["attachments"][0]["name"] == "q3.xlsx"

    @pytest.mark.parametrize(
        ("action", "stored", "url"),
        [
            ("decline", "ZGF0YQ==", "https://tenant-my.sharepoint.com/up"),
            ("accept", None, "https://tenant-my.sharepoint.com/up"),
            ("accept", "ZGF0YQ==", "http://insecure.example/up"),
        ],
    )
    async def test_a_decline_an_expired_file_or_an_insecure_upload_ends_quietly(
        self,
        adapter: TeamsAdapter,
        connector: _Connector,
        action: str,
        stored: str | None,
        url: str,
    ) -> None:
        redis = MagicMock(getdel=AsyncMock(return_value=stored))
        with patch.object(teams, "_pending_files", redis):
            await adapter.complete_file_consent(
                TOKEN, self._consent(action, url), conversation_key(PERSONAL)
            )
        assert connector.calls == []

    @pytest.mark.security
    async def test_an_upload_address_on_the_deployments_network_is_never_reached(
        self,
        adapter: TeamsAdapter,
        connector: _Connector,
        outside: _Outside,
        resolves_to: dict[str, str],
    ) -> None:
        """CodeQL on #2324: the address is the Teams client's to write, so a
        modified client could aim the bot's PUT at an internal service."""
        resolves_to["tenant-my.sharepoint.com"] = "10.0.0.5"
        redis = MagicMock(getdel=AsyncMock(return_value="ZGF0YQ=="))
        with patch.object(teams, "_pending_files", redis):
            await adapter.complete_file_consent(
                TOKEN, self._consent("accept"), conversation_key(PERSONAL)
            )

        assert outside.calls == []
        assert connector.posts() == []

    async def test_without_a_store_there_is_nothing_to_upload(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        with patch.object(teams, "_pending_files", None):
            await adapter.complete_file_consent(
                TOKEN, self._consent("accept"), conversation_key(PERSONAL)
            )
        assert connector.calls == []


class TestWhoIsInTheConversation:
    async def test_the_roster_is_read_page_by_page(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        pages = iter(
            [
                {"members": [{"aadObjectId": "a1", "name": "Ada"}], "continuationToken": "t"},
                {"members": [{"id": "29:b", "name": "Bob", "email": "bob@acme.com"}]},
            ]
        )

        def roster(request: httpx.Request) -> httpx.Response:
            connector.calls.append(request)
            if "oauth2" in str(request.url):
                return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
            return httpx.Response(200, json=next(pages))

        adapter._client._transport = httpx.MockTransport(roster)
        members = await adapter.channel_members(
            TOKEN, f"{conversation_key(CHANNEL)}:1", api_base_url=None, limit=10
        )

        assert [(m.user_id, m.display_name, m.username) for m in members] == [
            ("a1", "Ada", None),
            ("29:b", "Bob", "bob@acme.com"),
        ]

    async def test_details_name_the_channel_and_count_its_members(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        connector.answers["pagedmembers"] = httpx.Response(
            200, json={"members": [{"aadObjectId": "a"}, {"aadObjectId": "b"}]}
        )
        details = await adapter.channel_details(
            TOKEN, f"{conversation_key(CHANNEL)}:1", api_base_url=None
        )
        assert (details.name, details.member_count, details.is_private) == ("General", 2, False)

    @pytest.mark.parametrize(("status", "member"), [(200, True), (404, False)])
    async def test_one_person_is_looked_up_directly(
        self, adapter: TeamsAdapter, connector: _Connector, status: int, member: bool
    ) -> None:
        connector.answers["/members/aad-ada"] = httpx.Response(status, json={})
        assert (
            await adapter.is_channel_member(
                TOKEN, conversation_key(CHANNEL), "aad-ada", api_base_url=None
            )
            is member
        )


class TestLinkingThroughTheDirectory:
    """An unlinked sender is linked only where the deployment signs people in with
    Entra in the bot's own tenant (#1419)."""

    def _incoming(self) -> IncomingMessage:
        return IncomingMessage(
            platform="teams",
            bot_id="bot-1",
            platform_user_id="aad-ada",
            platform_chat_id=conversation_key(PERSONAL),
            chat_type="private",
            text="hi",
        )

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("issuer", "member", "expected"),
        [
            (
                f"https://login.microsoftonline.com/{TENANT}/v2.0",
                {"email": "Ada@Acme.com", "tenantId": TENANT},
                "ada@acme.com",
            ),
            (
                f"https://login.microsoftonline.com/{TENANT}/v2.0",
                {"userPrincipalName": "ada@acme.com"},
                "ada@acme.com",
            ),
            ("https://accounts.google.com", {"email": "ada@acme.com"}, None),
            ("https://login.microsoftonline.com/another/v2.0", {"email": "ada@acme.com"}, None),
            (
                f"https://login.microsoftonline.com/{TENANT}/v2.0",
                {"email": "ada@acme.com", "tenantId": "another"},
                None,
            ),
            (f"https://login.microsoftonline.com/{TENANT}/v2.0", {}, None),
        ],
    )
    async def test_only_the_deployments_own_tenant_vouches(
        self,
        adapter: TeamsAdapter,
        connector: _Connector,
        monkeypatch: pytest.MonkeyPatch,
        issuer: str,
        member: dict,
        expected: str | None,
    ) -> None:
        monkeypatch.setattr(teams.settings, "OIDC_ISSUER", issuer)
        connector.answers["/members/aad-ada"] = httpx.Response(200, json=member)
        assert await adapter.vouched_email(TOKEN, self._incoming()) == expected

    @pytest.mark.security
    async def test_a_conversation_in_another_tenant_vouches_for_nobody(
        self, adapter: TeamsAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            teams.settings, "OIDC_ISSUER", f"https://login.microsoftonline.com/{TENANT}/v2.0"
        )
        adapter.know(ConversationRef("a:guest", SERVICE, "personal", "another"))
        incoming = self._incoming()
        incoming.platform_chat_id = conversation_key("a:guest")
        assert await adapter.vouched_email(TOKEN, incoming) is None

    async def test_a_roster_that_will_not_answer_vouches_for_nobody(
        self, adapter: TeamsAdapter, connector: _Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            teams.settings, "OIDC_ISSUER", f"https://login.microsoftonline.com/{TENANT}/v2.0"
        )
        connector.answers["/members/aad-ada"] = httpx.Response(403)
        assert await adapter.vouched_email(TOKEN, self._incoming()) is None


class TestDownloadingWhatWasSent:
    async def test_a_shared_file_is_fetched_without_the_bots_token(
        self, adapter: TeamsAdapter, connector: _Connector, outside: _Outside
    ) -> None:
        data = await adapter.download_attachment(
            TOKEN, IncomingAttachment("q3.pdf", "application/pdf", 0, "https://t.sharepoint.com/f")
        )
        (call,) = outside.calls
        assert "authorization" not in call.headers
        assert connector.calls == []
        assert data == b"file-bytes"

    @pytest.mark.security
    async def test_a_shared_file_on_the_deployments_network_is_refused(
        self, adapter: TeamsAdapter, outside: _Outside, resolves_to: dict[str, str]
    ) -> None:
        """A file's address is the sender's to write; it is SSRF-checked like any other."""
        resolves_to["files.internal"] = "169.254.169.254"
        with pytest.raises(ValueError):
            await adapter.download_attachment(
                TOKEN, IncomingAttachment("x.pdf", "application/pdf", 0, "https://files.internal/x")
            )
        assert outside.calls == []

    @pytest.mark.security
    async def test_a_shared_file_stating_no_size_is_abandoned_past_the_ceiling(
        self, adapter: TeamsAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(teams, "_download_ceiling", lambda: 4)
        with pytest.raises(ValueError, match="larger than"):
            await adapter.download_attachment(
                TOKEN,
                IncomingAttachment("q3.pdf", "application/pdf", 0, "https://t.sharepoint.com/f"),
            )

    async def test_a_pasted_picture_is_fetched_with_it(
        self, adapter: TeamsAdapter, connector: _Connector
    ) -> None:
        await adapter.download_attachment(
            TOKEN, IncomingAttachment("p.png", "image/png", 0, f"{SERVICE}v3/attachments/1")
        )
        assert connector.calls[-1].headers["authorization"] == "Bearer bot-token"

    @pytest.mark.security
    async def test_a_file_stating_no_size_is_abandoned_past_the_ceiling(
        self, adapter: TeamsAdapter, connector: _Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pasted picture states no size, so only the download itself can bound it (Codex on #2324)."""
        monkeypatch.setattr(teams, "_download_ceiling", lambda: 1024)
        connector.answers["/v3/attachments/big"] = httpx.Response(200, content=b"x" * 4096)
        with pytest.raises(ValueError, match="larger than"):
            await adapter.download_attachment(
                TOKEN, IncomingAttachment("p.png", "image/png", 0, f"{SERVICE}v3/attachments/big")
            )

    def test_the_ceiling_admits_whatever_either_caller_would_keep(self) -> None:
        from app.core.config import settings
        from app.services.transcription import MAX_BYTES

        assert teams._download_ceiling() >= MAX_BYTES
        assert teams._download_ceiling() >= settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024

    async def test_only_https_is_fetched(self, adapter: TeamsAdapter) -> None:
        with pytest.raises(ValueError, match="HTTPS"):
            await adapter.download_attachment(
                TOKEN, IncomingAttachment("x", "text/plain", 0, "http://insecure.example/x")
            )


class TestTheParts:
    async def test_there_is_nothing_to_poll_or_register(self, adapter: TeamsAdapter) -> None:
        await adapter.start_polling("bot-1", TOKEN)
        await adapter.stop_polling("bot-1")
        assert await adapter.register_webhook(TOKEN, "https://x/messages", None) is False
        assert await adapter.delete_webhook(TOKEN) is False

    @pytest.mark.security
    def test_a_shared_secret_never_verifies_a_teams_request(self, adapter: TeamsAdapter) -> None:
        assert adapter.verify_webhook_signature({}, "secret", "{}") is False

    def test_a_split_never_cuts_a_character_in_half(self) -> None:
        text = "ż" * MESSAGE_LIMIT_BYTES
        pieces = _chunks(text)
        assert "".join(pieces) == text
        assert all(len(piece.encode("utf-8")) <= MESSAGE_LIMIT_BYTES for piece in pieces)

    async def test_the_adapter_is_registered_on_first_use(self) -> None:
        from app.services.channels import _adapters

        with patch.dict(_adapters, {}, clear=True):
            first = teams_adapter()
            assert teams_adapter() is first
        await first.aclose()
