"""What the Discord adapter says and reads, without a socket (#2079)."""

import pytest

from app.services.channels.base import CHANNEL_COMMANDS, ChannelChoice
from app.services.channels.discord_protocol import (
    ADMINISTRATOR,
    ASK,
    ASK_ABOUT,
    INTENTS,
    MESSAGE_LIMIT,
    VIEW_CHANNEL,
    Recent,
    attachment_type,
    can_view,
    chunks,
    close_refusal,
    commands,
    comment_form,
    components,
    identify,
    interaction_user,
    pressed_value,
    read_comment,
    resume,
    session_lost,
    thread_name,
    without_mention,
)

GUILD = "100"
OWNER = "1"
USER = "2"
ROLE = "300"


class TestGateway:
    def test_identify_asks_for_messages_their_text_and_direct_messages(self):
        payload = identify("tok")
        assert payload["op"] == 2
        assert payload["d"]["token"] == "tok"
        assert payload["d"]["intents"] == INTENTS == 37377

    def test_resume_names_the_session_and_where_it_stopped(self):
        assert resume("tok", "sess", 42) == {
            "op": 6,
            "d": {"token": "tok", "session_id": "sess", "seq": 42},
        }

    def test_a_rejected_token_or_intent_is_an_operator_s_to_fix(self):
        assert "token" in (close_refusal(4004) or "")
        assert "Message Content Intent" in (close_refusal(4014) or "")

    @pytest.mark.parametrize("code", [None, 1000, 1006, 4000, 4007, 4009])
    def test_any_other_close_is_reconnected(self, code: int | None):
        assert close_refusal(code) is None

    @pytest.mark.parametrize(
        ("code", "lost"), [(4007, True), (4009, True), (4000, False), (None, False)]
    )
    def test_only_a_bad_sequence_or_a_timeout_loses_the_session(self, code: int | None, lost: bool):
        assert session_lost(code) is lost


class TestCommands:
    def test_ask_the_channel_commands_and_the_message_command_are_registered(self):
        registered = commands()
        names = [command["name"] for command in registered]
        assert names[0] == ASK
        assert registered[0]["options"][0]["required"] is True
        assert names[-1] == ASK_ABOUT
        assert registered[-1]["type"] == 3
        assert set(names[1:-1]) == {name for name, _ in CHANNEL_COMMANDS} - {"start"}

    def test_no_command_follows_an_install_to_a_user_s_own_account(self):
        assert {tuple(command["integration_types"]) for command in commands()} == {(0,)}


class TestChunks:
    def test_a_short_answer_is_one_message(self):
        assert chunks("hello") == ["hello"]
        assert chunks("") == [""]

    def test_a_long_answer_is_cut_at_a_line(self):
        text = "a" * 1500 + "\n" + "b" * 1000
        assert chunks(text) == ["a" * 1500, "b" * 1000]

    def test_without_a_line_it_is_cut_at_a_word(self):
        text = "a" * 1500 + " " + "b" * 1000
        assert chunks(text) == ["a" * 1500, "b" * 1000]

    def test_without_either_it_is_cut_at_the_limit(self):
        pieces = chunks("x" * 4500)
        assert [len(piece) for piece in pieces] == [MESSAGE_LIMIT, MESSAGE_LIMIT, 500]


class TestThreadName:
    def test_the_first_line_names_the_thread_without_mentions(self):
        assert (
            thread_name("<@123> what is the refund window?\nmore") == "what is the refund window?"
        )

    def test_a_quote_reads_as_its_text(self):
        assert thread_name("\n> the quoted line") == "the quoted line"

    def test_nothing_to_name_it_by_is_a_conversation(self):
        assert thread_name("<@123>") == "Conversation"

    def test_a_long_first_line_is_clipped_to_discord_s_limit(self):
        name = thread_name("word " * 40)
        assert len(name) == 100
        assert name.endswith("…")


def test_only_the_bot_s_own_mention_is_taken_out():
    assert without_mention("<@42> ask <@!42> <@7> about it", "42") == "ask <@7> about it"


def test_taking_the_mention_out_keeps_the_lines_and_the_code():
    text = "<@42> why does this fail?\n```py\nif x:\n    run()\n```"
    assert without_mention(text, "42") == "why does this fail?\n```py\nif x:\n    run()\n```"


@pytest.mark.parametrize(
    ("content_type", "filename", "expected"),
    [
        ("image/webp", "image.png", "image/png"),
        ("image/png", "photo.jpeg", "image/jpeg"),
        ("image/png", "image.png", "image/png"),
        ("image/webp", "photo", "image/webp"),
        ("image/png", "notes.txt", "image/png"),
        ("application/pdf", "image.png", "application/pdf"),
        (None, "image.png", "application/octet-stream"),
    ],
)
def test_only_an_image_type_contradicting_an_image_name_takes_the_name_s(
    content_type: str | None, filename: str, expected: str
):
    assert attachment_type(content_type, filename) == expected


class TestComponents:
    def test_choices_are_buttons_five_to_a_row_coloured_by_style(self):
        choices = [
            ChannelChoice(label="Approve", value="aos:1:0", style="primary"),
            ChannelChoice(label="Reject", value="aos:1:1", style="danger"),
            *(ChannelChoice(label=f"c{index}", value=f"v{index}") for index in range(4)),
        ]
        rows = components(choices)
        assert [len(row["components"]) for row in rows] == [5, 1]
        styles = [button["style"] for button in rows[0]["components"]]
        assert styles == [1, 4, 2, 2, 2]
        assert rows[0]["components"][0]["custom_id"] == "aos:1:0"

    def test_a_long_label_is_clipped_to_what_a_button_holds(self):
        [row] = components([ChannelChoice(label="x" * 90, value="v")])
        assert len(row["components"][0]["label"]) == 80

    def test_past_twenty_five_choices_they_are_selects(self):
        choices = [ChannelChoice(label="y" * 120, value=f"v{index}") for index in range(30)]
        rows = components(choices)
        selects = [row["components"][0] for row in rows]
        assert [select["type"] for select in selects] == [3, 3]
        assert [len(select["options"]) for select in selects] == [25, 5]
        assert len(selects[0]["options"][0]["label"]) == 100
        assert selects[1]["options"][0]["value"] == "v25"

    def test_no_more_than_five_selects(self):
        rows = components([ChannelChoice(label="c", value=f"v{i}") for i in range(200)])
        assert len(rows) == 5


class TestPressedValue:
    def test_a_button_carries_its_id(self):
        assert pressed_value({"component_type": 2, "custom_id": "aos:1:0"}) == "aos:1:0"

    def test_a_select_carries_the_chosen_option(self):
        assert (
            pressed_value({"component_type": 3, "custom_id": "aossel:0", "values": ["v3"]}) == "v3"
        )

    def test_an_empty_select_or_no_id_is_nothing(self):
        assert pressed_value({"component_type": 3, "values": []}) is None
        assert pressed_value({"component_type": 2}) is None


class TestCommentForm:
    def test_the_form_carries_the_run_it_is_about(self):
        form = comment_form("run1")
        assert form["type"] == 9
        assert form["data"]["custom_id"] == "aosfc:run1"

    def test_a_submitted_form_is_read_back(self):
        submitted = {
            "custom_id": "aosfc:run1",
            "components": [{"components": [{"custom_id": "comment", "value": " too vague "}]}],
        }
        assert read_comment(submitted) == ("run1", "too vague")

    def test_another_form_an_empty_comment_or_no_run_is_nothing(self):
        assert read_comment({"custom_id": "other"}) is None
        assert read_comment({"custom_id": "aosfc:run1", "components": []}) is None
        assert (
            read_comment(
                {
                    "custom_id": "aosfc:",
                    "components": [{"components": [{"custom_id": "x", "value": "a"}]}],
                }
            )
            is None
        )


def test_the_actor_is_the_member_in_a_server_and_the_user_in_a_direct_message():
    assert interaction_user({"member": {"user": {"id": "1"}}}) == {"id": "1"}
    assert interaction_user({"user": {"id": "2"}}) == {"id": "2"}
    assert interaction_user({}) == {}


class TestCanView:
    def _view(
        self,
        *,
        user_id: str = USER,
        roles: dict[str, int] | None = None,
        member_roles: list[str] | None = None,
        overwrites: list[dict[str, object]] | None = None,
    ) -> bool:
        return can_view(
            user_id=user_id,
            guild_id=GUILD,
            owner_id=OWNER,
            roles={GUILD: VIEW_CHANNEL, ROLE: 0} if roles is None else roles,
            member_roles=[ROLE] if member_roles is None else member_roles,
            overwrites=overwrites or [],
        )

    def test_everyone_sees_a_channel_with_no_overwrites(self):
        assert self._view()

    def test_the_owner_sees_everything(self):
        assert self._view(user_id=OWNER, roles={GUILD: 0})

    def test_an_administrator_sees_everything(self):
        assert self._view(
            roles={GUILD: 0, ROLE: ADMINISTRATOR},
            overwrites=[{"id": GUILD, "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"}],
        )

    def test_a_private_channel_hides_from_everyone(self):
        assert not self._view(overwrites=[{"id": GUILD, "type": 0, "deny": str(VIEW_CHANNEL)}])

    def test_a_role_overwrite_lets_its_members_back_in(self):
        assert self._view(
            overwrites=[
                {"id": GUILD, "type": 0, "deny": str(VIEW_CHANNEL)},
                {"id": ROLE, "type": 0, "allow": str(VIEW_CHANNEL)},
            ]
        )

    def test_a_member_overwrite_has_the_last_word(self):
        assert not self._view(
            overwrites=[
                {"id": ROLE, "type": 0, "allow": str(VIEW_CHANNEL)},
                {"id": USER, "type": 1, "deny": str(VIEW_CHANNEL)},
            ]
        )

    def test_a_member_s_role_missing_from_the_guild_grants_nothing(self):
        assert not self._view(roles={GUILD: 0}, member_roles=["999"])


def test_the_cache_forgets_its_oldest_entry():
    recent: Recent[int] = Recent(2)
    recent.put("a", 1)
    recent.put("b", 2)
    recent.put("a", 3)
    recent.put("c", 4)
    assert "b" not in recent
    assert recent.get("a") == 3
    assert recent.get("c") == 4
    assert recent.get("b") is None
