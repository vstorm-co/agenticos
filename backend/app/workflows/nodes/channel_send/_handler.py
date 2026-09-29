"""`channel.send`: post a message to a channel as one of the organization's bots.

The text is sent as the bot, through the same adapter its replies go through,
to a channel - or a thread in it - the step is bound to. A platform's own
formatting applies: Slack's mrkdwn, Mattermost's Markdown, Telegram's plain
text. See `app.workflows.nodes._channels`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.channels.base import ChannelAdapter, OutgoingMessage
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._channels import ChannelBotConfig, failed, with_bot


class ChannelSendInput(BaseModel):
    """Where the message goes, and what it says."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str = Field(min_length=1, max_length=255, description="The platform's channel id")
    text: str = Field(min_length=1, max_length=40_000)
    thread_id: str | None = Field(
        default=None, max_length=255, description="Answer inside this thread instead"
    )


class ChannelSendOutput(BaseModel):
    """Where the message was sent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str
    thread_id: str | None = None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Send the message as the step's bot."""
    if not isinstance(config, ChannelBotConfig) or not isinstance(node_input, ChannelSendInput):
        return failed("CHANNEL_NOT_CONFIGURED", "This step needs a bot, a channel and a text")

    async def send(adapter: ChannelAdapter, token: str, base_url: str | None) -> NodeResult:
        await adapter.send_message(
            token,
            OutgoingMessage(
                platform_chat_id=node_input.channel_id,
                text=node_input.text,
                reply_to_message_id=node_input.thread_id,
                api_base_url=base_url,
            ),
        )
        return Completed[ChannelSendOutput](
            output=ChannelSendOutput(
                channel_id=node_input.channel_id, thread_id=node_input.thread_id
            )
        )

    return await with_bot(config, send)
