"""Giving an agent a page it can publish, and update behind the same link."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.artifacts._toolset import PAGE_CONTRACT, build_artifacts_toolset


@dataclass
class Artifacts(AbstractCapability[AgentDepsT]):
    """Lets an agent publish a self-contained page as a shared, versioned artifact.

    See the package `README.md` for what an artifact is, why the name is the
    identity, and why the page is served in a sandbox with no network.
    """

    table_grants: Mapping[UUID, frozenset[str]]
    workflow_ids: frozenset[UUID] = frozenset()
    screenshot: bool = True
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> str:
        """The page contract: skeleton, classes, icons and bound data, before the first page.

        The tool text alone reached a model that skipped the `artifact-pages` skill,
        and every page it wrote looked broken; this reaches it whether or not the
        skill is bound. Static, so the cached prompt prefix keeps it.
        """
        return PAGE_CONTRACT

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_artifacts_toolset(
                table_grants=self.table_grants,
                workflow_ids=self.workflow_ids,
                screenshot=self.screenshot,
            )
        return self._toolset
