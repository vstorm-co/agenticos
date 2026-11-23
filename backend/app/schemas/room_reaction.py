"""Shared-room reactions: one emoji, per-person storage, aggregate transcript reads."""

import unicodedata

import regex
from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

MAX_EMOJI_CHARS = 32
"""Maximum Unicode code points in a reaction, including joiners and selectors."""

MAX_DISTINCT_REACTIONS_PER_MESSAGE = 20

_EMOJI_BASE = regex.compile(r"(?:\p{Extended_Pictographic}|\p{Emoji_Presentation})")
_FLAG = regex.compile(r"\A\p{Regional_Indicator}{2}\Z")
_KEYCAP = regex.compile(r"\A[#*0-9]\uFE0F?\u20E3\Z")


class RoomMessageReactionCreate(BaseSchema):
    """Set one human reaction on a room message."""

    emoji: str = Field(min_length=1, max_length=MAX_EMOJI_CHARS)

    @field_validator("emoji")
    @classmethod
    def one_emoji_grapheme(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if (
            len(normalized) > MAX_EMOJI_CHARS
            or any(character.isspace() for character in normalized)
            or regex.fullmatch(r"\X", normalized) is None
            or not (
                _EMOJI_BASE.search(normalized)
                or _FLAG.fullmatch(normalized)
                or _KEYCAP.fullmatch(normalized)
            )
        ):
            raise ValueError("Reaction must be one emoji")
        return normalized


class RoomMessageReactionRead(BaseSchema):
    """An emoji and its aggregate count on a message."""

    emoji: str
    count: int = Field(ge=1)
    reacted_by_me: bool


class RoomMessageReactionsRead(BaseSchema):
    """Current reaction aggregates for one authorized room message."""

    reactions: list[RoomMessageReactionRead] = Field(default_factory=list)
