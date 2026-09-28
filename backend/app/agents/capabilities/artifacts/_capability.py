"""Giving an agent a page it can publish, and update behind the same link."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.artifacts._toolset import build_artifacts_toolset


@dataclass
class Artifacts(AbstractCapability[AgentDepsT]):
    """Lets an agent publish a self-contained page as a shared, versioned artifact.

    See the package `README.md` for what an artifact is, why the name is the
    identity, and why the page is served in a sandbox with no network.
    """

    # The run's workspace backend when one is open, so a page the agent built on
    # disk can be published as the file it is. `None` for an agent without the
    # sandbox capability, which publishes content it passes inline instead.
    workspace_backend: Any | None = field(default=None, repr=False, compare=False)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_artifacts_toolset(workspace_backend=self.workspace_backend)
        return self._toolset
