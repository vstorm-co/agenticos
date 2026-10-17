"""Claude Code or Codex, working in the agent's sandbox at the model's request."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.coding_agent._harness import Harness
from app.agents.capabilities.coding_agent._toolset import build_coding_toolset


@dataclass
class CodingAgent(AbstractCapability[AgentDepsT]):
    """Hands software work to a coding harness running in the run's sandbox.

    See the package `README.md` for why the harness is driven headless through
    the sandbox's shell rather than over ACP, and why its approval is one
    decision per change.
    """

    harness: Harness = "claude_code"
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: int = 900
    # Unsealed from the vault by the factory; `repr=False` for the reason
    # `ImageGeneration.api_key` gives - a repr reaches log lines and tracebacks.
    api_key: str | None = field(default=None, repr=False)
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_coding_toolset(
                harness=self.harness,
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                timeout_seconds=self.timeout_seconds,
            )
        return self._toolset
