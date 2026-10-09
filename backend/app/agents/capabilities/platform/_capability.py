"""Operating AgenticOS itself, as the person the run acts for."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.platform._toolset import build_toolset


@dataclass
class PlatformOperations(AbstractCapability[AgentDepsT]):
    """Lets an agent find and manage the organization's agents, runs, knowledge
    and members, with exactly the permissions of whoever it is acting for."""

    credential: SecretStr
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_toolset(self.credential.get_secret_value())
        return self._toolset
