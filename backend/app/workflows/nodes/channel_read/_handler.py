"""`<platform>.messages.read`: the latest messages in a channel, or in one thread of it.

What the bot may read on its platform, newest last: Slack and Mattermost let a
bot read a channel it is in. Telegram does not let a bot read history at all,
so it has no such step. See `app.workflows.nodes._channels`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.channels.base import ChannelAdapter
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._channels import (
    ChannelBotConfig,
    NodeHandler,
    Platform,
    failed,
    with_bot,
)


class ChannelReadConfig(ChannelBotConfig):
    """The bot, and how many messages to read."""

    limit: int = Field(
        default=50, ge=1, le=200, title="Messages to read", description="At most this many"
    )


class ChannelReadInput(BaseModel):
    """Which channel, and which thread in it, if one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str = Field(min_length=1, max_length=255, title="Channel")
    thread_id: str | None = Field(
        default=None, max_length=255, title="Thread", description="Read this thread instead"
    )


class ChannelMessage(BaseModel):
    """One message: who wrote it, what it says, and when."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author: str
    text: str
    posted_at: datetime | None = None
    post_id: str | None = None


class ChannelReadOutput(BaseModel):
    """The messages, oldest first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[ChannelMessage, ...]


def handler_on(platform: Platform) -> NodeHandler:
    """The step for one platform: the same call, made only as a bot of that platform."""

    async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
        """Read the channel as the step's bot."""
        if not isinstance(config, ChannelReadConfig) or not isinstance(
            node_input, ChannelReadInput
        ):
            return failed("CHANNEL_NOT_CONFIGURED", "This step needs a bot and a channel")

        async def read(adapter: ChannelAdapter, token: str, base_url: str | None) -> NodeResult:
            posts = await adapter.channel_history(
                token,
                node_input.channel_id,
                api_base_url=base_url,
                limit=config.limit,
                thread_id=node_input.thread_id,
            )
            return Completed[ChannelReadOutput](
                output=ChannelReadOutput(
                    messages=tuple(
                        ChannelMessage(
                            author=post.author,
                            text=post.text,
                            posted_at=post.posted_at,
                            post_id=post.post_id,
                        )
                        for post in posts
                    )
                )
            )

        return await with_bot(config, platform, read)

    return handle
