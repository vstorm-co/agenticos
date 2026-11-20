"""An external agent uses the existing Desktop ACP task lifecycle."""

from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.external_acp._toolset import build_acp_toolset
from app.agents.deps import AgentDeps
from app.agents.pi_keys import NativeKeyProvider


@dataclass
class ExternalAcp(AbstractCapability[AgentDeps]):
    """Delegate a task to a program admitted by this Desktop owner."""

    agent_id: str
    timeout_seconds: int = 900
    auth_method: str | None = None
    model_id: str | None = None
    api_provider: NativeKeyProvider | None = None
    secret_id: UUID | None = None
    platform_tools: bool = False

    def get_instructions(self) -> str:
        return (
            "Use run_acp_agent to hand a whole task to the configured external agent on the person's computer. "
            "It has its own tools, account and model settings. Its native tools can change files and run commands; "
            "this integration does not promise read-only confinement. "
            + (
                "Its platform bridge exposes only the tools admitted to this run, with platform approval and budget checks. "
                if self.platform_tools
                else "Your platform tools are not exposed to it. "
            )
            + "Use inspect_acp_agent to read the current account model choices before suggesting a model. A catalog does not prove inference entitlement or remaining quota. Use a named session to continue its work. Report the returned answer and failures. "
            "Subscription or API charges belong to its configured account; the platform cannot price them."
        )

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return build_acp_toolset(
            self.agent_id,
            self.timeout_seconds,
            auth_method=self.auth_method,
            model_id=self.model_id,
            api_provider=self.api_provider,
            secret_id=self.secret_id,
            platform_tools=self.platform_tools,
        )
