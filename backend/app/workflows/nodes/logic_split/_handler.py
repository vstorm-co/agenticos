"""`logic.split`: send the run down every branch at once.

Each branch is a named output port, and the step after it runs beside the steps on the
others. Nothing here chooses: every branch is always taken, which is why a Split takes
no condition and cannot route its errors (`validate._split_problems`) - a Split that
failed did not start any branch. The branches meet again at a step with several inputs:
a Merge that waits for all of them, or any step that has them as its inputs, provided
publishing finds each branch certain to reach it.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.workflows.contracts.definition import Port
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._port_names import refuse_clash

MAX_BRANCHES = 20
_RESERVED = frozenset({"in"})


class SplitBranch(BaseModel):
    """One named way out, always taken."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", description="The branch's port id")

    @field_validator("name")
    @classmethod
    def _not_a_port_already(cls, name: str) -> str:
        return refuse_clash(name, _RESERVED)


class LogicSplitConfig(BaseModel):
    """The branches the run is sent down together."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branches: tuple[SplitBranch, ...] = Field(
        min_length=2,
        max_length=MAX_BRANCHES,
        description="The branches, each a named output port; at least two, each with its own name",
    )

    @model_validator(mode="after")
    def _distinct_names(self) -> Self:
        names = [branch.name for branch in self.branches]
        if len(set(names)) != len(names):
            raise ValueError("Each branch needs a name of its own")
        return self


class LogicSplitOutput(BaseModel):
    """Nothing: a Split hands nothing on, each branch's steps bind to what ran before it."""

    model_config = ConfigDict(frozen=True, extra="forbid")


STATIC_PORTS = (Port(id="in", label="In", kind="input", schema=None),)


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`in` and one output per branch, in order. Any step may follow a branch."""
    branches = config.branches if isinstance(config, LogicSplitConfig) else ()
    return (
        *STATIC_PORTS,
        *(
            Port(id=branch.name, label=branch.name, kind="output", schema=None)
            for branch in branches
        ),
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Complete: the dispatcher takes every non-error port of a step that selects none."""
    return Completed[LogicSplitOutput](output=LogicSplitOutput())
