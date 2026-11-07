"""Native product tools use the same operation service as workflow nodes."""

from dataclasses import dataclass

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps


@dataclass
class NativeIntegration(AbstractCapability[AgentDeps]):
    toolset: FunctionToolset[AgentDeps]

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return self.toolset
