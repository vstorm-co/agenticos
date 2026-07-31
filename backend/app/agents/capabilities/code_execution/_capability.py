"""Running small Python programs in a restricted sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.code_execution._sandbox import (
    DEFAULT_MAX_MEMORY_MB,
    DEFAULT_TIMEOUT_SECS,
)
from app.agents.capabilities.code_execution._toolset import build_toolset


@dataclass
class CodeExecution(AbstractCapability[AgentDepsT]):
    """Lets an agent compute rather than guess.

    The sandbox is deliberately restricted: no network, no filesystem, a small
    stdlib subset. That is what makes this safe to grant broadly - the failure
    mode of a general sandbox is remote code execution.

    The limits are the binding's, not the deployment's: an agent that crunches
    real datasets gets more room in its own config without every other agent's
    sandbox growing with it.
    """

    timeout_secs: float = DEFAULT_TIMEOUT_SECS
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_toolset(
                timeout_secs=self.timeout_secs, max_memory_mb=self.max_memory_mb
            )
        return self._toolset
