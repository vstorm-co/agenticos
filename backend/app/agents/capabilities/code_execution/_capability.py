"""Running small Python programs in a restricted sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.code_execution._toolset import build_toolset


@dataclass
class CodeExecution(AbstractCapability[AgentDepsT]):
    """Lets an agent compute rather than guess.

    The sandbox is deliberately restricted: no network, no filesystem, a small
    stdlib subset. That is what makes this safe to grant broadly - the failure
    mode of a general sandbox is remote code execution.
    """

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_toolset()
        return self._toolset
