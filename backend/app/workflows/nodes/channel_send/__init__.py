"""`channel.send` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import ChannelBotConfig, check_bot
from app.workflows.nodes.channel_send._handler import ChannelSendInput, ChannelSendOutput, handle

register(
    NodeDefinition(
        id="channel.send",
        version=1,
        name="Send a message",
        category="channels",
        description="Post a message to a channel, or a thread in it, as one of your bots.",
        kind="action",
        config_schema=ChannelBotConfig,
        input_schema=ChannelSendInput,
        output_schema=ChannelSendOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ChannelSendOutput),
        ),
        effect_kind="write",
        retry_guarantee="none",
        handler=handle,
        resource_check=check_bot,
    )
)
