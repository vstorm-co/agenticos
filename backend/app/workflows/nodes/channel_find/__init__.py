"""`channel.find` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot
from app.workflows.nodes.channel_find._handler import (
    ChannelFindConfig,
    ChannelFindInput,
    ChannelFindOutput,
    handle,
)

register(
    NodeDefinition(
        id="channel.find",
        version=1,
        name="Find channels",
        category="channels",
        description="Find channels by name, within the reach of one of your bots.",
        kind="action",
        config_schema=ChannelFindConfig,
        input_schema=ChannelFindInput,
        output_schema=ChannelFindOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ChannelFindOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_bot,
    )
)
