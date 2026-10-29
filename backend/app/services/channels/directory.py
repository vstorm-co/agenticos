"""Binding a channel directory to one bot, one server and one channel.

The join between `app.agents.capabilities.channel_tools`, which declares what an
agent may ask, and the adapters, which know how to ask it. It exists so the
capability never holds a token and never chooses a channel: both are decided
here, from the row the message arrived on, before the agent is built.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools import (
    ChannelDestination,
    ChannelDetails,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)
from app.core.exceptions import BadRequestError
from app.db.models.agent_exposure import AgentExposure
from app.repositories import channel_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import (
    ChannelAdapter,
    OutgoingAttachment,
    OutgoingMessage,
    split_thread,
)
from app.services.channels.teams import inline_image_supported

TOOL_METHODS: dict[str, str] = {
    "send_channel_file": "send_message",
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
        "send_channel_file",
        "get_channel_info",
        "list_channel_members",
        "search_channels",
        "read_channel_history",
    ),
    "mattermost": (
        "send_channel_file",
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
    "telegram": ("get_channel_info", "list_channel_members", "send_channel_file"),
    # The Bot Connector answers a conversation's roster, and nothing that would
    # search a tenant's channels or read what was said before the bot was asked.
    "teams": ("get_channel_info", "list_channel_members", "send_channel_file"),
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
    bot_id: UUID | None = None
    private_chat: bool = False
    thread_id: str | None = None
    """The thread this run is answering in, where the platform has threads.

    Bound like the channel and for the same reason. It is *not* an argument to
    `history`: a model that could name the thread could name another one, and the
    conversation an agent may read is the one it was spoken to in.
    """

    @property
    def destination(self) -> ChannelDestination | None:
        if self.bot_id is None:
            return None
        return ChannelDestination(
            bot_id=self.bot_id,
            platform_chat_id=self.channel_id + (":" + self.thread_id if self.thread_id else ""),
            private_chat=self.private_chat,
        )

    async def send_file(self, *, filename: str, content: bytes, mime_type: str) -> str:
        teams_file = self.adapter.platform == "teams" and not inline_image_supported(
            content, mime_type
        )
        if teams_file and not self.private_chat:
            return "File delivery refused: Teams accepts ordinary bot files only in a personal chat. Ask the user to request it there."
        await self.adapter.send_message(
            self.bot_token,
            OutgoingMessage(
                platform_chat_id=self.channel_id + (":" + self.thread_id if self.thread_id else ""),
                text="",
                attachments=[OutgoingAttachment(filename, content, mime_type)],
                api_base_url=self.api_base_url,
            ),
        )

        if teams_file:
            return f"Offered {filename!r} in this personal Teams chat. The recipient must accept it before upload; do not claim delivery yet."
        return f"Submitted {filename!r} to this conversation; the platform accepted the attachment."

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

    async def history(
        self, *, limit: int, scope: Literal["thread", "channel"] = "thread"
    ) -> list[ChannelPost]:
        return await self.adapter.channel_history(
            self.bot_token,
            self.channel_id,
            api_base_url=self.api_base_url,
            limit=limit,
            thread_id=self.thread_id if scope == "thread" else None,
        )


async def restore_directory(
    db: AsyncSession,
    *,
    organization_id: UUID,
    surface: str,
    exposure: AgentExposure | None,
    destination: ChannelDestination | None,
) -> BoundChannelDirectory | None:
    """Restore only the original bot and conversation, with its current sealed credential."""
    if destination is None:
        return None
    if exposure is None or not exposure.is_active or exposure.channel_bot_id != destination.bot_id:
        raise BadRequestError(
            message="The original channel binding is no longer available",
            details={
                "exposure_id": None if exposure is None else str(exposure.id),
                "bot_id": str(destination.bot_id),
            },
        )
    bot = await channel_bot_repo.get_for_org(
        db, destination.bot_id, organization_id=organization_id
    )
    if bot is None or not bot.is_active or bot.platform != surface:
        raise BadRequestError(
            message="The original channel bot is no longer available",
            details={"bot_id": str(destination.bot_id), "surface": surface},
        )
    channel_id, thread_id = split_thread(destination.platform_chat_id)
    return BoundChannelDirectory(
        adapter=get_adapter(surface),
        bot_token=unseal_bot_token(bot),
        bot_id=bot.id,
        channel_id=channel_id,
        thread_id=thread_id or None,
        private_chat=destination.private_chat,
        api_base_url=bot.api_base_url,
    )
