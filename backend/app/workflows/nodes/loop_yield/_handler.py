"""`loop.yield`: where one `control.foreach` iteration ends, and what it hands back.

A sink inside the body. Its bound `value` is this iteration's entry in the
loop's `results`, in input order; an iteration that never reaches it - its
branch was not taken - contributes `null`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.workflows.contracts.results import Completed, NodeResult


class LoopYieldInput(BaseModel):
    """What this iteration contributes to the loop's results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None


class LoopYieldOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    value = node_input.value if isinstance(node_input, LoopYieldInput) else None
    return Completed[LoopYieldOutput](output=LoopYieldOutput(value=value))
