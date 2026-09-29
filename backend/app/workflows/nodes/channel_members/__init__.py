"""`channel.members` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot
from app.workflows.nodes.channel_members._handler import (
    ChannelMembersConfig,
    ChannelMembersInput,
    ChannelMembersOutput,
    handle,
)

register(
    NodeDefinition(
        id="channel.members",
        version=1,
        name="List people",
        category="channels",
        description="List the people in a channel, with the ids a mention takes.",
        kind="action",
        config_schema=ChannelMembersConfig,
        input_schema=ChannelMembersInput,
        output_schema=ChannelMembersOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ChannelMembersOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_bot,
    )
)
