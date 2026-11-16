"""Caller-scoped operations on explicitly granted messaging connections."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.agents.capabilities.channel_tools._directory import HistoryPage

RESOURCE = "channel_actions"
CAPABILITY_ID = "channel_actions"
TOOLS = frozenset(
    {
        "list_chat_connections",
        "find_chat_channels",
        "read_chat_messages",
        "send_chat_message",
        "react_to_chat_message",
    }
)
CROSS_CHANNEL_PLATFORMS = frozenset({"mattermost", "slack"})
REACTION_PLATFORMS = frozenset({"mattermost", "slack", "telegram", "discord", "imessage"})
PLATFORMS = CROSS_CHANNEL_PLATFORMS | REACTION_PLATFORMS


def platform_actions(platform: str) -> frozenset[str]:
    """Expose only operations implemented by the selected transport."""
    if platform in CROSS_CHANNEL_PLATFORMS:
        return TOOLS
    if platform in REACTION_PLATFORMS:
        return frozenset({"list_chat_connections", "react_to_chat_message"})
    return frozenset()


class ChannelActionsPort(Protocol):
    async def react(
        self,
        bot_id: UUID,
        channel_id: str,
        message_id: str,
        emojis: list[str],
        *,
        reaction_only: bool,
    ) -> str: ...

    async def connections(self) -> str: ...

    async def find(self, bot_id: UUID, query: str, limit: int, cursor: str | None) -> str: ...

    async def read(
        self,
        bot_id: UUID,
        channel_id: str,
        *,
        thread_id: str | None,
        query: str,
        after: AwareDatetime | None,
        before: AwareDatetime | None,
        author_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> HistoryPage: ...

    async def send(
        self, bot_id: UUID, channel_id: str, *, text: str, thread_id: str | None
    ) -> str: ...


class ReactionReceipt(BaseModel):
    kind: Literal["channel_reaction"] = "channel_reaction"
    bot_id: UUID
    channel_id: str
    message_id: str
    applied: list[str]
    failed: list[str]
    not_attempted: list[str] = Field(default_factory=list)
    reaction_only: bool
