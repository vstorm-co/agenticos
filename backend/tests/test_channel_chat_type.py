"""The `chat_type` every adapter persists is drawn from one two-word vocabulary.

Telegram used to emit its own `supergroup` and `channel` while Slack and
Mattermost collapsed everything but a DM to `group`, so `channel_sessions.chat_type`
held a different vocabulary per platform - and a consumer reading `chat_type ==
"group"`, the natural thing, would silently miss every Telegram room (#556). All
three adapters now emit `private` or `group`; Mattermost's own mapping is pinned
in `test_mattermost_channel.py`, and this pins Telegram, the one that changed.
"""

import pytest

from app.services.channels.telegram import TelegramAdapter


@pytest.mark.parametrize(
    ("telegram_type", "expected"),
    [
        ("private", "private"),
        ("group", "group"),
        ("supergroup", "group"),
        ("channel", "group"),
    ],
)
def test_telegram_folds_every_room_type_to_group(telegram_type: str, expected: str) -> None:
    parsed = TelegramAdapter().parse_incoming(
        {"message": {"chat": {"id": 1, "type": telegram_type}, "from": {"id": 2}, "text": "hi"}},
        "bot-1",
    )

    assert parsed is not None
    assert parsed.chat_type == expected
