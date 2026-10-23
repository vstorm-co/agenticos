"""Letting an agent start the workflows its binding names, and read how they went."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.workflows._toolset import build_workflows_toolset

if TYPE_CHECKING:
    from app.agents.spec import AgentSpec

MAX_WORKFLOWS = 20

# Where the factory hands a run the workflows its spec binds (a page's actions are
# checked against them at publish), beside `workflow_ids_of`.
WORKFLOW_IDS_RESOURCE = "workflow_ids"


class WorkflowsConfig(BaseModel):
    """Which workflows an agent may start, and how long it waits for one."""

    model_config = ConfigDict(extra="forbid")

    workflow_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_WORKFLOWS,
        json_schema_extra={"x-resource": "workflow"},
        description="Published workflows that start by hand, by the API or by a call.",
    )
    wait_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        title="Wait for a run (seconds)",
        description="How long run_workflow waits for a run to finish before handing "
        "back its id to read later.",
    )

    @field_validator("workflow_ids")
    @classmethod
    def _each_once(cls, workflow_ids: list[UUID]) -> list[UUID]:
        if len(set(workflow_ids)) != len(workflow_ids):
            raise ValueError("A workflow is named once")
        return workflow_ids


def workflow_ids_of(spec: AgentSpec) -> tuple[UUID, ...]:
    """The workflows the spec's enabled `workflows` binding names.

    Empty when the capability is not bound or is switched off.
    """
    for binding in spec.capabilities:
        if binding.id == "workflows" and binding.enabled:
            return tuple(WorkflowsConfig.model_validate(binding.config).workflow_ids)
    return ()


@dataclass
class Workflows(AbstractCapability[AgentDepsT]):
    """Starts the workflows the binding names, as the member the run acts for.

    Which workflows is the binding's configuration - part of the published spec,
    which the model cannot rewrite. A call naming any other workflow is refused
    before anything starts, and the start itself checks the member's access as
    the API would.
    """

    workflow_ids: tuple[UUID, ...] = ()
    wait_seconds: int = 60

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The workflow tools, built once per capability instance - that is, per run."""
        if self._toolset is None:
            self._toolset = build_workflows_toolset(
                workflow_ids=self.workflow_ids, wait_seconds=self.wait_seconds
            )
        return self._toolset
