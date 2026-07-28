"""Tests for the Mattermost adapter.

Three things are worth pinning here, and all three are ways a chat bot fails
expensively rather than visibly:

- a bot must not answer its own posts (an infinite loop with a model bill),
- an outgoing webhook is authenticated by a shared token, compared in constant
  time and refused when absent — there is no signature to fall back on,
- a self-hosted platform needs its server URL, and a bot without one fails
  loudly rather than posting nowhere.
"""

import json

import pytest

from app.services.channels.base import OutgoingMessage
from app.services.channels.mattermost import MattermostAdapter


def _posted(**post: object) -> dict[str, object]:
    """A `posted` frame as Mattermost sends it — the post is a JSON *string*."""
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
        assert incoming.platform_chat_id == "c1"

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


class TestSending:
    @pytest.mark.anyio
    async def test_a_bot_with_no_server_url_fails_loudly(self):
        """Self-hosted: there is no default host to fall back to, and silently
        doing nothing would look like a bot that ignores people."""
        with pytest.raises(ValueError, match="no server URL"):
            await MattermostAdapter().send_message(
                "token", OutgoingMessage(platform_chat_id="c1", text="hi")
            )
