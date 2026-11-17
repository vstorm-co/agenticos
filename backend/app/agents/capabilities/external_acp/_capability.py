"""An external agent uses the existing Desktop ACP task lifecycle."""

from dataclasses import dataclass

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.external_acp._toolset import build_acp_toolset
from app.agents.deps import AgentDeps


@dataclass
class ExternalAcp(AbstractCapability[AgentDeps]):
    """Delegate a task to a program admitted by this Desktop owner."""

    agent_id: str
    timeout_seconds: int = 900

    def get_instructions(self) -> str:
        return (
            "Use run_acp_agent to hand a whole task to the configured external agent on the person's computer. "
            "It has its own tools, account and model settings. Its native tools can change files and run commands; "
            "this integration does not promise read-only confinement or expose your platform tools to it. "
            "Use a named session to continue its work. Report the returned answer and failures. "
            "Subscription or API charges belong to its configured account; the platform cannot price them."
        )

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return build_acp_toolset(self.agent_id, self.timeout_seconds)
