"""`logic.merge`: rejoin the two branches of a `logic.if` into one path.

Exactly one of its incoming branches ran - publishing refuses a merge whose
inputs do not leave one `logic.if` through different ports - and neither
branch dominates the merge, so rule 4 lets it bind to neither. The dispatcher
therefore hands it the output of the branch that did run
(`DispatchContext.arrived_output`), and the merge passes that on under
`value`. What reaches `value` differs by branch, so a node downstream reads
fields of it by path and is checked when it is dispatched.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, NodeResult


class LogicMergeOutput(BaseModel):
    """The output of whichever branch reached the merge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: dict[str, Any] | None = None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Pass on the output the arriving branch produced."""
    return Completed[LogicMergeOutput](
        output=LogicMergeOutput(value=context.current().arrived_output)
    )
