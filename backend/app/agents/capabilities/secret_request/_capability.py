"""Ask the person for a secret, mid-run, instead of working around its absence."""

from dataclasses import dataclass, field

from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities.secret_request._toolset import SecretRequestToolset
from app.agents.deps import AgentDeps


@dataclass
class SecretRequestCapability(AbstractCapability[AgentDeps]):
    """The `request_secret` tool, parked until the person provides the secret."""

    _toolset: SecretRequestToolset[AgentDeps] | None = field(default=None, init=False, repr=False)

    def get_toolset(self) -> SecretRequestToolset[AgentDeps]:
        if self._toolset is None:
            self._toolset = SecretRequestToolset[AgentDeps]()
        return self._toolset
