"""`channel.read` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot
from app.workflows.nodes.channel_read._handler import (
    ChannelReadConfig,
    ChannelReadInput,
    ChannelReadOutput,
    handle,
)

register(
    NodeDefinition(
        id="channel.read",
        version=1,
        name="Read messages",
        category="channels",
        description="Read the latest messages in a channel or a thread, as one of your bots.",
        kind="action",
        config_schema=ChannelReadConfig,
        input_schema=ChannelReadInput,
        output_schema=ChannelReadOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ChannelReadOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_bot,
    )
)
