"""Direct messages between agents, visible in the console.

One thread per pair of agents, in one organization. A message is stored, never
delivered as a run: the recipient reads it in the console, or through these
tools on its next run. That is the whole point - multi-agent work that used to
happen inside a delegation, where only the parent ever saw it, is now a thread
anyone who may run either agent can open.
"""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.agent_messages._capability import AgentMessages
from app.agents.capabilities.agent_messages._toolset import (
    LIST_DESCRIPTION,
    REACT_DESCRIPTION,
    READ_DESCRIPTION,
    SEND_DESCRIPTION,
)

__all__ = ["AgentMessages", "AgentMessagesConfig"]


class AgentMessagesConfig(BaseModel):
    """How this agent messages other agents."""

    max_message_chars: int = Field(
        title="Longest message",
        default=16_000,
        ge=100,
        le=16_000,
        description=(
            "The longest message this agent may send, in characters. 16,000 is "
            "the console's ceiling as well, so a thread reads the same however "
            "the message was sent; lower it for an agent that should keep its "
            "messages short."
        ),
    )
    allow_attachments: bool = Field(
        title="Allow file attachments",
        default=True,
        description=(
            "Whether this agent may send files it already uploaded along with its "
            "messages. Off means text only; files already attached stay readable."
        ),
    )


@register(
    id="agent_messages",
    name="Agent messages",
    category="reasoning",
    description=(
        "Send a message to another agent, read what it wrote back, and react - "
        "in a thread the console shows."
    ),
    tools=(
        CapabilityToolInfo(
            id="agent_send_message", description=SEND_DESCRIPTION, side_effecting=True
        ),
        CapabilityToolInfo(
            id="agent_read_messages",
            description=READ_DESCRIPTION,
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(
            id="agent_list_threads",
            description=LIST_DESCRIPTION,
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(id="agent_react", description=REACT_DESCRIPTION, side_effecting=True),
    ),
    config_schema=AgentMessagesConfig,
    scopes=("agents:message",),
    side_effecting=False,
)
def _build(ctx: CapabilityBuildContext) -> AgentMessages:
    config = ctx.config if isinstance(ctx.config, AgentMessagesConfig) else AgentMessagesConfig()
    return AgentMessages(
        max_message_chars=config.max_message_chars,
        allow_attachments=config.allow_attachments,
    )
