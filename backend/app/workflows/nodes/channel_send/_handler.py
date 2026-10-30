"""`<platform>.message.send`: post a message to a channel as one of the organization's bots.

The text is sent as the bot, through the same adapter its replies go through,
to a channel - or a thread in it - the step is bound to. A platform's own
formatting applies: Slack's mrkdwn, Mattermost's Markdown, Telegram's plain
text. See `app.workflows.nodes._channels`.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.services.channels.base import ChannelAdapter, OutgoingMessage, thread_key
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._channels import (
    ChannelBotConfig,
    NodeHandler,
    Platform,
    failed,
    with_bot,
)


class ChannelSendInput(BaseModel):
    """Where the message goes, and what it says."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str = Field(
        min_length=1, max_length=255, title="Channel", description="The platform's channel id"
    )
    text: str = Field(min_length=1, max_length=40_000, title="Message")
    thread_id: str | None = Field(
        default=None,
        max_length=255,
        title="Thread",
        description=(
            "The thread to answer in: a Slack thread's timestamp, a Mattermost root post's id, "
            "a Telegram forum topic"
        ),
    )


class ChannelSendOutput(BaseModel):
    """Where the message was sent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str
    thread_id: str | None = None


def handler_on(platform: Platform) -> NodeHandler:
    """The step for one platform: the same call, made only as a bot of that platform."""

    async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
        """Send the message as the step's bot."""
        if not isinstance(config, ChannelBotConfig) or not isinstance(node_input, ChannelSendInput):
            return failed("CHANNEL_NOT_CONFIGURED", "This step needs a bot, a channel and a text")

        thread_id = node_input.thread_id or ""
        if ":" in node_input.channel_id:
            return failed(
                "CHANNEL_TARGET_INVALID",
                "A channel id has no ':' in it - bind the trigger's channel_id",
                platform=platform,
            )
        if ":" in thread_id:
            return failed(
                "CHANNEL_TARGET_INVALID",
                "A thread id has no ':' in it - bind the trigger's thread_id",
                platform=platform,
            )
        if (
            platform == "telegram"
            and thread_id
            and not (thread_id.isascii() and thread_id.isdigit())
        ):
            return failed(
                "CHANNEL_TARGET_INVALID",
                "A Telegram thread is a forum topic's number - bind the trigger's thread_id",
                platform=platform,
            )

        async def send(adapter: ChannelAdapter, token: str, base_url: str | None) -> NodeResult:
            await adapter.send_message(
                token,
                OutgoingMessage(
                    platform_chat_id=thread_key(
                        node_input.channel_id, thread_id=thread_id, message_id=None
                    ),
                    text=node_input.text,
                    api_base_url=base_url,
                ),
            )
            return Completed[ChannelSendOutput](
                output=ChannelSendOutput(
                    channel_id=node_input.channel_id, thread_id=node_input.thread_id
                )
            )

        return await with_bot(config, platform, send)

    return handle
