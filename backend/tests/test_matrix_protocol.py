"""What the Matrix adapter says and reads, without a homeserver (#2081)."""

from typing import Any

import httpx
import pytest

from app.services.channels.base import channel_key, split_thread, thread_key
from app.services.channels.matrix_protocol import (
    MESSAGE_LIMIT,
    attachment_of,
    chunks,
    edit_content,
    error_code,
    file_content,
    html,
    media_url,
    names,
    read_message,
    retry_after,
    room_key,
    room_of,
    text_content,
    with_latest_edit,
    without_mention,
    without_reply_fallback,
)

BOT = "@agent:example.org"
ROOM = "!abc:example.org"


def _event(content: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "m.room.message",
        "event_id": "$question",
        "sender": "@ada:example.org",
        "origin_server_ts": 1_700_000_000_000,
        "content": {"msgtype": "m.text", "body": "hello", **content},
    }
    event.update(overrides)
    return event


class TestRoomKeys:
    def test_a_room_id_survives_being_folded_with_a_thread(self):
        """The colon in a room id is what `split_thread` cuts on, so it must not reach it."""
        key = thread_key(room_key(ROOM), thread_id="", message_id="$question")
        channel, thread = split_thread(key)
        assert room_of(channel) == ROOM
        assert room_of(channel_key(key)) == ROOM
        assert thread == "$question"

    def test_a_room_id_without_a_server_part_is_unchanged(self):
        assert room_key("!31hneApxJ_1o-63DmFrpeqnkFfWppnzWso1JvH3ogLM") == (
            "!31hneApxJ_1o-63DmFrpeqnkFfWppnzWso1JvH3ogLM"
        )

    @pytest.mark.parametrize("key", ["@ada%3Aexample.org", "general", "!" + "a" * 300])
    def test_anything_but_a_room_is_refused(self, key: str):
        with pytest.raises(ValueError):
            room_of(key)


class TestReading:
    def test_a_message_is_read_with_its_thread_and_mentions(self):
        message = read_message(
            _event(
                {
                    "body": "Agent: what is the refund window?",
                    "m.mentions": {"user_ids": [BOT]},
                    "m.relates_to": {
                        "rel_type": "m.thread",
                        "event_id": "$root",
                        "is_falling_back": True,
                        "m.in_reply_to": {"event_id": "$root"},
                    },
                }
            )
        )
        assert message is not None
        assert message.thread_root == "$root"
        assert message.mentioned == frozenset({BOT})
        assert message.text == "Agent: what is the refund window?"

    @pytest.mark.parametrize(
        "content",
        [
            {"msgtype": "m.notice"},
            {"m.relates_to": {"rel_type": "m.replace", "event_id": "$before"}},
            {"msgtype": "m.image", "body": "photo.png"},
            {"msgtype": "m.file", "body": "secret.pdf", "file": {"url": "mxc://x/y"}},
            {"body": None},
        ],
        ids=["notice", "edit", "image-without-url", "encrypted-file", "redacted"],
    )
    def test_what_the_bot_never_answers_is_not_read(self, content: dict[str, Any]):
        assert read_message(_event(content)) is None

    def test_a_reply_loses_the_quote_older_clients_put_above_it(self):
        message = read_message(
            _event(
                {
                    "body": "> <@bob:example.org> the old question\n\nand the new one",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}},
                }
            )
        )
        assert message is not None
        assert message.text == "and the new one"
        assert message.thread_root is None

    def test_only_a_leading_quote_is_taken_off(self):
        assert without_reply_fallback("no quote\n> later") == "no quote\n> later"
        assert without_reply_fallback(">not a fallback") == ">not a fallback"

    def test_a_file_is_a_handle_on_the_bots_own_homeserver(self):
        message = read_message(
            _event(
                {
                    "msgtype": "m.file",
                    "body": "report.pdf",
                    "url": "mxc://example.org/AbCd123",
                    "info": {"mimetype": "application/pdf", "size": 2048},
                }
            )
        )
        assert message is not None and message.text == ""
        attachment = attachment_of(message, "https://matrix.example.org")
        assert attachment is not None
        assert attachment.handle == (
            "https://matrix.example.org/_matrix/client/v1/media/download/example.org/AbCd123"
        )
        assert (attachment.filename, attachment.mime_type, attachment.size) == (
            "report.pdf",
            "application/pdf",
            2048,
        )
        assert attachment.author_id == "@ada:example.org"

    def test_a_voice_note_says_how_long_it_is(self):
        message = read_message(
            _event(
                {
                    "msgtype": "m.audio",
                    "body": "Voice message.ogg",
                    "url": "mxc://example.org/voice",
                    "info": {"mimetype": "audio/ogg", "size": 10, "duration": 4200},
                }
            )
        )
        assert message is not None
        attachment = attachment_of(message, "https://hs")
        assert attachment is not None and attachment.duration_seconds == 4.2

    def test_a_content_uri_with_a_path_is_refused(self):
        with pytest.raises(ValueError):
            media_url("https://hs", "mxc://example.org/../../admin")

    def test_the_latest_edit_is_what_a_history_reads(self):
        event = _event(
            {"body": "…", "m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}},
            unsigned={
                "m.relations": {
                    "m.replace": {"content": {"m.new_content": {"msgtype": "m.text", "body": "42"}}}
                }
            },
        )
        message = read_message(with_latest_edit(event))
        assert message is not None
        assert (message.text, message.thread_root) == ("42", "$root")


class TestAddressing:
    def test_m_mentions_naming_the_bot_addresses_it(self):
        message = read_message(_event({"body": "Agent: hi", "m.mentions": {"user_ids": [BOT]}}))
        assert message is not None and names(message, BOT, "Agent") is True

    @pytest.mark.parametrize(
        "body",
        ["@AgenticOS (dev) what can you do?", "hey @agent, a question", f"{BOT}: hi"],
        ids=["display-name", "localpart", "user-id"],
    )
    def test_a_typed_handle_addresses_the_bot_without_a_pill(self, body: str):
        """Some clients send a typed `@name` as plain text with an empty `m.mentions` (#2081).

        Read as the router reads a typed `@agent-slug`: an explicit handle is
        somebody addressing the bot, pill or not.
        """
        message = read_message(_event({"body": body, "m.mentions": {}}))
        assert message is not None and names(message, BOT, "AgenticOS (dev)") is True

    @pytest.mark.parametrize(
        "body",
        [
            "AgenticOS (dev) without the at",
            "ping @agent-ops please",
            "mail agent@example.org",
            "a robot",
        ],
    )
    def test_a_name_without_its_handle_or_another_handle_does_not(self, body: str):
        message = read_message(_event({"body": body, "m.mentions": {}}))
        assert message is not None and names(message, BOT, "AgenticOS (dev)") is False

    def test_a_handle_inside_code_is_not_a_mention(self):
        message = read_message(_event({"body": "run `@agent help`", "m.mentions": {}}))
        assert message is not None and names(message, BOT, None) is False

    def test_an_older_client_is_read_by_the_pill_it_wrote(self):
        message = read_message(
            _event(
                {
                    "body": "Agent: hi",
                    "format": "org.matrix.custom.html",
                    "formatted_body": f'<a href="https://matrix.to/#/{BOT}">Agent</a>: hi',
                }
            )
        )
        assert message is not None and names(message, BOT, None) is True

    def test_the_bots_name_leaves_the_question_and_code_keeps_its_lines(self):
        text = "Agent: run this\n```\nprint(1)\n```"
        assert without_mention(text, BOT, "Agent") == "run this\n```\nprint(1)\n```"

    def test_the_bots_name_mid_sentence_is_kept(self):
        assert without_mention("ask the Agent team", BOT, "Agent") == "ask the Agent team"

    def test_a_user_id_mention_is_removed_wherever_it_is(self):
        assert without_mention(f"{BOT}: hi", BOT, None) == "hi"

    def test_a_typed_handle_leaves_the_question(self):
        assert without_mention("@AgenticOS (dev) what can you do?", BOT, "AgenticOS (dev)") == (
            "what can you do?"
        )
        assert without_mention("thanks @agent, that works", BOT, None) == "thanks , that works"


class TestWriting:
    def test_a_reply_goes_into_its_thread_and_notifies_nobody(self):
        content = text_content("**done**", root="$root")
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$root"
        assert content["m.relates_to"]["m.in_reply_to"] == {"event_id": "$root"}
        assert content["m.mentions"] == {}
        assert content["formatted_body"] == "<p><strong>done</strong></p>"

    def test_the_models_html_is_escaped_not_sent_as_markup(self):
        assert "<script>" not in html("<script>alert(1)</script>")

    def test_an_edit_replaces_its_target_and_carries_no_thread_of_its_own(self):
        content = edit_content("final", target="$answer")
        assert content["m.relates_to"] == {"rel_type": "m.replace", "event_id": "$answer"}
        assert content["m.new_content"]["body"] == "final"
        assert "m.relates_to" not in content["m.new_content"]
        assert content["m.new_content"]["m.mentions"] == {}

    def test_an_image_is_shown_inline_and_another_file_is_offered(self):
        assert file_content("a.png", "image/png", 3, "mxc://h/a", root=None)["msgtype"] == "m.image"
        assert file_content("a.csv", "text/csv", 3, "mxc://h/b", root=None)["msgtype"] == "m.file"

    def test_a_long_answer_is_cut_at_a_line_within_the_limit(self):
        text = ("line\n" * 2000).strip()
        pieces = chunks(text)
        assert len(pieces) > 1
        assert all(len(piece) <= MESSAGE_LIMIT for piece in pieces)
        assert "".join(pieces).replace("\n", "") == text.replace("\n", "")

    def test_an_edit_of_a_full_piece_fits_one_event(self):
        """Four-byte characters, three copies and the JSON around them: still under 64 KiB."""
        import json

        piece = chunks("😀" * 10_000)[0]
        assert (
            len(json.dumps(edit_content(piece, target="$a"), ensure_ascii=False).encode()) < 65_536
        )


class TestErrors:
    def test_the_errcode_is_read_from_the_body(self):
        response = httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN"})
        assert error_code(response) == "M_UNKNOWN_TOKEN"
        assert error_code(httpx.Response(502, text="bad gateway")) is None

    def test_a_rate_limit_says_how_long_to_wait(self):
        assert retry_after(httpx.Response(429, json={"retry_after_ms": 1500})) == 1.5
        assert retry_after(httpx.Response(429, headers={"Retry-After": "3"}, text="")) == 3.0
        assert retry_after(httpx.Response(429, text="")) == 1.0
