"""`data.value`: hold one value - an object, a list or a scalar - for later steps.

The value is typed into the node as JSON or bound whole from an earlier output,
and handed on unchanged as `value`. Later steps read it, or a path into it such
as `value.customer.email`. It is set once per run: a step output is never
overwritten, so this is a named constant, not a variable another step can change.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, JsonValue, WithJsonSchema

from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError


class DataValueInput(BaseModel):
    """The value to hold: typed in as JSON, or bound from an earlier output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Keep the editor free-form while validating the durable JSON boundary.
    value: Annotated[JsonValue, WithJsonSchema({})]


class DataValueOutput(BaseModel):
    """What `out` carries: the value, unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Keep the editor free-form while validating the durable JSON boundary.
    value: Annotated[JsonValue, WithJsonSchema({})]


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand the value on unchanged, or fail when the step has none.

    Publishing refuses a graph whose `value` is not bound, so `node_input` is
    only missing for a draft run of a step nobody has set up yet.
    """
    if not isinstance(node_input, DataValueInput):
        return Failed(
            error=WorkflowError(code="DATA_NOT_SET", message="This Data step has no value")
        )
    return Completed[DataValueOutput](output=DataValueOutput(value=node_input.value))
