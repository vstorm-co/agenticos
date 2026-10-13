"""Binding a channel directory to one bot, one server and one channel.

The join between `app.agents.capabilities.channel_tools`, which declares what an
agent may ask, and the adapters, which know how to ask it. It exists so the
capability never holds a token and never chooses a channel: both are decided
here, from the row the message arrived on, before the agent is built.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)
from app.services.channels.base import ChannelAdapter

TOOL_METHODS: dict[str, str] = {
    "get_channel_info": "channel_details",
    "list_channel_members": "channel_members",
    "search_channels": "search_channels",
    "read_channel_history": "channel_history",
}
"""Which adapter method answers each registered tool.

One mapping, read by `supported_tools` below and by the drift test that keeps
`PLATFORM_TOOLS` honest - so a fifth tool cannot be added to the capability
without something naming the method that would answer it.
"""

PLATFORM_TOOLS: dict[str, tuple[str, ...]] = {
    "slack": (
        "get_channel_info",
        "list_channel_members",
        "search_channels",
        "read_channel_history",
    ),
    "mattermost": (
        "get_channel_info",
        "list_channel_members",
        "search_channels",
        "read_channel_history",
    ),
    # Telegram gives a bot no directory of chats to search and no way to read
    # messages it was not sent, and `getChatAdministrators` is the whole of what
    # it may list. The other two are absent rather than present-and-refusing:
    # this list is what the Builder offers, and offering a checkbox whose only
    # effect is a tool that says "Telegram cannot do that" is a worse answer
    # than not offering it.
    "telegram": ("get_channel_info", "list_channel_members"),
}
"""What each platform can actually answer, as the Builder offers it.

Declared rather than derived so it can be read without an adapter registered -
the exposure service validates against it on every write, and the API serves it
to the Builder. `tests/test_channel_tools.py` compares it against the adapter
classes in both directions, so an implementation added without a row here, or a
row here for a method nobody overrode, fails naming the platform.
"""


def supported_tools(adapter: type[ChannelAdapter]) -> frozenset[str]:
    """The tools this adapter class actually implements.

    An adapter implements one by overriding the base method; the base raises
    `ChannelDirectoryUnsupported`, which is what a platform without an
    equivalent should say. Read off the class rather than declared a second
    time, because a declaration beside an implementation is a declaration that
    outlives it.
    """
    return frozenset(
        tool_id
        for tool_id, method in TOOL_METHODS.items()
        if getattr(adapter, method) is not getattr(ChannelAdapter, method)
    )


@dataclass(frozen=True)
class BoundChannelDirectory:
    """One channel, ready to be asked about.

    Frozen, and holding the channel id rather than taking one per call: this is
    the object handed to a capability, and a capability that could be asked
    about a different channel is one the model could ask about a different
    channel.
    """

    adapter: ChannelAdapter
    bot_token: str
    channel_id: str
    api_base_url: str | None = None
    thread_id: str | None = None
    """The thread this run is answering in, where the platform has threads.

    Bound like the channel and for the same reason. It is *not* an argument to
    `history`: a model that could name the thread could name another one, and the
    conversation an agent may read is the one it was spoken to in.
    """

    async def details(self) -> ChannelDetails:
        return await self.adapter.channel_details(
            self.bot_token, self.channel_id, api_base_url=self.api_base_url
        )

    async def members(self, *, limit: int) -> list[ChannelMember]:
        return await self.adapter.channel_members(
            self.bot_token, self.channel_id, api_base_url=self.api_base_url, limit=limit
        )

    async def search(self, query: str, *, limit: int) -> list[ChannelSummary]:
        return await self.adapter.search_channels(
            self.bot_token,
            self.channel_id,
            api_base_url=self.api_base_url,
            query=query,
            limit=limit,
        )

    async def history(self, *, limit: int) -> list[ChannelPost]:
        return await self.adapter.channel_history(
            self.bot_token,
            self.channel_id,
            api_base_url=self.api_base_url,
            limit=limit,
            thread_id=self.thread_id,
        )
