"""Validation for one grapheme-cluster emoji in shared-room reactions."""

import pytest
from pydantic import ValidationError

from app.schemas.room_reaction import RoomMessageReactionCreate


@pytest.mark.parametrize(
    "emoji",
    ["👍", "👨‍👩‍👧‍👦", "👩🏽‍💻", "🇸🇬", "1️⃣", "🏳️‍🌈"],
)
def test_accepts_one_emoji_grapheme(emoji: str) -> None:
    assert RoomMessageReactionCreate(emoji=emoji).emoji == emoji


@pytest.mark.parametrize("emoji", ["👍✅", "👍🏻👍🏻", "hello", "1", "👍 ✅"])
def test_rejects_multiple_or_non_emoji_graphemes(emoji: str) -> None:
    with pytest.raises(ValidationError, match="one emoji"):
        RoomMessageReactionCreate(emoji=emoji)


@pytest.mark.parametrize("emoji", [" 👍 ", "\t👍\n"])
def test_trims_surrounding_whitespace_like_other_request_fields(emoji: str) -> None:
    assert RoomMessageReactionCreate(emoji=emoji).emoji == "👍"
