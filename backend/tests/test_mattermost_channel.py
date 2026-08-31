"""Tests for the Mattermost adapter.

Three things are worth pinning here, and all three are ways a chat bot fails
expensively rather than visibly:

- a bot must not answer its own posts (an infinite loop with a model bill),
- an outgoing webhook is authenticated by a shared token, compared in constant
  time and refused when absent - there is no signature to fall back on,
- a self-hosted platform needs its server URL, and a bot without one fails
  loudly rather than posting nowhere.
"""

import json

import httpx
import pytest

from app.services.channels.base import OutgoingMessage
from app.services.channels.mattermost import MattermostAdapter, decode_webhook_body


def _posted(**post: object) -> dict[str, object]:
    """A `posted` frame as Mattermost sends it - the post is a JSON *string*."""
    body = {"id": "p1", "user_id": "u1", "channel_id": "c1", "message": "hello", **post}
    return {
        "event": "posted",
        "data": {"post": json.dumps(body), "channel_type": "D", "sender_name": "@kacper"},
    }


class TestNormalisation:
    def test_a_direct_message_arrives_as_a_private_chat(self):
        incoming = MattermostAdapter().parse_incoming(_posted(), "bot-1")

        assert incoming is not None
        assert incoming.chat_type == "private"
        assert incoming.platform == "mattermost"
        assert incoming.text == "hello"
        assert incoming.platform_username == "kacper"

    def test_a_thread_reply_gets_its_own_conversation_id(self):
        """Folded into `platform_chat_id` the way Slack's is, so one thread is
        one conversation without the router knowing what a thread is."""
        incoming = MattermostAdapter().parse_incoming(_posted(root_id="root-9"), "bot-1")

        assert incoming is not None
        assert incoming.platform_chat_id == "c1:root-9"

    def test_the_bots_own_post_is_ignored(self):
        """Answering it is an infinite loop, and each turn costs a model call."""
        frame = _posted()
        data = frame["data"]
        assert isinstance(data, dict)
        data["post"] = json.dumps({**json.loads(data["post"]), "props": {"from_bot": "true"}})

        assert MattermostAdapter().parse_incoming(frame, "bot-1") is None

    def test_an_empty_message_is_ignored(self):
        assert MattermostAdapter().parse_incoming(_posted(message="   "), "bot-1") is None

    def test_a_malformed_frame_is_skipped_rather_than_fatal(self):
        frame = {"event": "posted", "data": {"post": "not json"}}
        assert MattermostAdapter().parse_incoming(frame, "bot-1") is None

    def test_a_webhook_payload_normalises_the_same_way(self):
        """The two entry points differ in shape and in nothing else."""
        incoming = MattermostAdapter().parse_incoming(
            {
                "token": "t",
                "user_id": "u1",
                "user_name": "kacper",
                "channel_id": "c1",
                "channel_name": "town-square",
                "post_id": "p1",
                "text": "hello",
            },
            "bot-1",
        )

        assert incoming is not None
        assert incoming.chat_type == "group"
        # Its own post, because the reply will open a thread rooted there (#1339).
        assert incoming.platform_chat_id == "c1:p1"

    def test_a_webhook_from_a_direct_message_channel_is_private(self):
        """Mattermost names a DM channel after both user ids joined by `__`;
        the webhook payload has no channel type to read."""
        incoming = MattermostAdapter().parse_incoming(
            {"user_id": "u1", "user_name": "k", "channel_name": "u1__u2", "text": "hi"},
            "bot-1",
        )

        assert incoming is not None
        assert incoming.chat_type == "private"


class TestWebhookAuthentication:
    def test_the_token_in_the_body_is_what_authenticates(self):
        adapter = MattermostAdapter()
        body = json.dumps({"token": "shared-token", "text": "hi"})

        assert adapter.verify_webhook_signature({}, "shared-token", body) is True

    def test_a_wrong_token_is_refused(self):
        adapter = MattermostAdapter()
        body = json.dumps({"token": "other", "text": "hi"})

        assert adapter.verify_webhook_signature({}, "shared-token", body) is False

    def test_no_secret_configured_means_refused_rather_than_open(self):
        """Mattermost does not sign the body, so an unset secret is an endpoint
        anybody on the internet can post to."""
        adapter = MattermostAdapter()

        assert adapter.verify_webhook_signature({}, "", '{"token": "anything"}') is False

    def test_a_form_encoded_body_is_read_too(self):
        adapter = MattermostAdapter()

        assert adapter.verify_webhook_signature({}, "tok", "token=tok&text=hi") is True


class TestWebhookBodyDecoding:
    """One decode for both halves of receiving a webhook.

    The token check and the message have to read the same body the same way;
    when they did not, a body one of them could read and the other could not
    authenticated and then delivered nothing.
    """

    def test_the_message_survives_a_body_the_header_described_wrongly(self):
        """The regression: JSON arriving as `application/x-www-form-urlencoded`.

        The token check has always found this - it tries JSON first - so the
        request authenticates. Decoding the message from the declared type
        instead made it an empty payload, a 200, and a dropped message.
        """
        raw = json.dumps({"token": "tok", "text": "hi", "user_name": "kacper"})

        assert decode_webhook_body(raw) == {
            "token": "tok",
            "text": "hi",
            "user_name": "kacper",
        }

    def test_a_form_body_decodes_to_its_first_value_per_key(self):
        assert decode_webhook_body("token=tok&text=hi") == {"token": "tok", "text": "hi"}

    def test_a_body_that_is_neither_is_empty_rather_than_an_error(self):
        """A malformed body must not raise: the endpoint answers 200 to
        everything, and an exception here would be a 500 Mattermost retries."""
        assert decode_webhook_body("") == {}

    def test_json_that_is_not_an_object_is_empty(self):
        """`parse_incoming` reads keys off whatever this returns."""
        assert decode_webhook_body("[1, 2, 3]") == {}


class TestSending:
    @pytest.mark.anyio
    async def test_a_bot_with_no_server_url_fails_loudly(self):
        """Self-hosted: there is no default host to fall back to, and silently
        doing nothing would look like a bot that ignores people."""
        with pytest.raises(ValueError, match="no server URL"):
            await MattermostAdapter().send_message(
                "token", OutgoingMessage(platform_chat_id="c1", text="hi")
            )

    @pytest.mark.anyio
    async def test_a_server_url_with_a_trailing_slash_still_posts_to_one_slash(self, monkeypatch):
        """Operators type `https://mattermost.acme.com/` about half the time.

        `{base}/api/v4/posts` then carries two slashes, Mattermost answers 301 to
        the single-slash form, and httpx does not follow a redirect on a POST -
        so the reply is lost with an `HTTPStatusError` in the log rather than an
        answer in the thread. Found against a real server on the first message it
        ever received.
        """
        posted: dict[str, str] = {}

        class _Response:
            def raise_for_status(self) -> None:
                return None

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

            async def post(self, url: str, **_kwargs: object) -> _Response:
                posted["url"] = url
                return _Response()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _Client())

        await MattermostAdapter().send_message(
            "token",
            OutgoingMessage(
                platform_chat_id="c1", text="hi", api_base_url="https://mattermost.acme.com/"
            ),
        )

        assert posted["url"] == "https://mattermost.acme.com/api/v4/posts"

    @pytest.mark.anyio
    async def test_two_sends_reuse_one_http_client(self, monkeypatch):
        """One client per adapter, not one per call: a streamed turn is dozens of
        REST calls to one host, and a fresh client each time throws the pool away
        before it is reused, paying a handshake every time (#952)."""
        made = 0
        posts: list[str] = []

        class _Response:
            def raise_for_status(self) -> None:
                return None

        class _Client:
            async def post(self, url: str, **_kwargs: object) -> _Response:
                posts.append(url)
                return _Response()

        def _make(**_kwargs: object) -> _Client:
            nonlocal made
            made += 1
            return _Client()

        monkeypatch.setattr(httpx, "AsyncClient", _make)

        adapter = MattermostAdapter()
        for _ in range(2):
            await adapter.send_message(
                "token",
                OutgoingMessage(
                    platform_chat_id="c1", text="hi", api_base_url="https://mattermost.acme.com"
                ),
            )

        assert made == 1  # built once, in __init__, not per send
        assert posts == [
            "https://mattermost.acme.com/api/v4/posts",
            "https://mattermost.acme.com/api/v4/posts",
        ]


class TestAMentionAndTheThreadItOpensAreOneConversation:
    """The bug #1339 fixed: they used to be two.

    The reply to a channel mention opens a thread rooted at that message. Keyed
    on the bare channel, the first turn and every turn after it landed in
    different conversations - so the agent answered a question and then, in the
    thread it had just created, had no memory of it.
    """

    def test_a_channel_message_keys_on_the_thread_its_reply_will_open(self):
        incoming = MattermostAdapter().parse_incoming(
            {
                "event": "posted",
                "data": {
                    "post": json.dumps(
                        {"id": "p1", "user_id": "u1", "channel_id": "c1", "message": "hi"}
                    ),
                    "channel_type": "O",
                    "sender_name": "@kacper",
                },
            },
            "bot-1",
        )

        assert incoming is not None
        assert incoming.platform_chat_id == "c1:p1"

    def test_the_reply_in_that_thread_keys_on_the_same_conversation(self):
        """The second turn resolves the session the first turn created."""
        first = MattermostAdapter().parse_incoming(
            {
                "event": "posted",
                "data": {
                    "post": json.dumps(
                        {"id": "p1", "user_id": "u1", "channel_id": "c1", "message": "hi"}
                    ),
                    "channel_type": "O",
                    "sender_name": "@kacper",
                },
            },
            "bot-1",
        )
        second = MattermostAdapter().parse_incoming(
            {
                "event": "posted",
                "data": {
                    "post": json.dumps(
                        {
                            "id": "p2",
                            "root_id": "p1",
                            "user_id": "u1",
                            "channel_id": "c1",
                            "message": "and then?",
                        }
                    ),
                    "channel_type": "O",
                    "sender_name": "@kacper",
                },
            },
            "bot-1",
        )

        assert first is not None and second is not None
        assert first.platform_chat_id == second.platform_chat_id == "c1:p1"

    def test_two_unrelated_mentions_in_one_channel_do_not_share_a_conversation(self):
        def _at_root(post_id: str):
            return MattermostAdapter().parse_incoming(
                {
                    "event": "posted",
                    "data": {
                        "post": json.dumps(
                            {"id": post_id, "user_id": "u1", "channel_id": "c1", "message": "hi"}
                        ),
                        "channel_type": "O",
                        "sender_name": "@kacper",
                    },
                },
                "bot-1",
            )

        one, two = _at_root("p1"), _at_root("p9")

        assert one is not None and two is not None
        assert one.platform_chat_id != two.platform_chat_id

    def test_a_direct_message_opens_a_thread_like_anywhere_else(self):
        """It used to key on the chat, making a DM one conversation for ever: it
        never rolls over, so it passes the context window in days and every turn
        pays for the whole history. A thread per question is a per-topic context
        instead. The cost is that a new message at the bottom of the DM starts
        fresh - continuing means replying inside the thread, which the next test
        is the other half of.
        """
        first = MattermostAdapter().parse_incoming(_posted(id="p1"), "bot-1")
        second = MattermostAdapter().parse_incoming(_posted(id="p2"), "bot-1")

        assert first is not None and second is not None
        assert first.platform_chat_id == "c1:p1"
        assert second.platform_chat_id == "c1:p2"

    def test_a_reply_inside_a_direct_messages_thread_rejoins_it(self):
        opened = MattermostAdapter().parse_incoming(_posted(id="p1"), "bot-1")
        later = MattermostAdapter().parse_incoming(_posted(id="p8", root_id="p1"), "bot-1")

        assert opened is not None and later is not None
        assert later.platform_chat_id == opened.platform_chat_id
