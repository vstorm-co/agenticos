"""The messaging actions granted on this agent's current bot bindings."""

from dataclasses import dataclass

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.channel_actions._contract import ChannelActionsPort
from app.agents.capabilities.channel_actions._toolset import build_channel_actions
from app.agents.deps import AgentDeps


@dataclass
class ChannelActions(AbstractCapability[AgentDeps]):
    port: ChannelActionsPort
    tools: frozenset[str]

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return build_channel_actions(self.port, self.tools)
