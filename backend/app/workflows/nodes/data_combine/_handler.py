"""`data.combine`: make one list of two - one after the other, or item by item.

`append` puts the second list after the first. `by_position` merges the objects
at the same position, as far as the shorter list goes. `by_key` merges into each
object of the first list the object of the second with the same value under
`key`; an object with no match is kept as it is, and a key the second list holds
twice takes its last object. Where both objects have a field, the second's wins.
"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

MAX_ITEMS = 10_000


class DataCombineConfig(BaseModel):
    """How the two lists become one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["append", "by_position", "by_key"] = "append"
    key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="The field both lists' objects are matched by, for by_key",
    )

    @model_validator(mode="after")
    def _a_key_to_match_by(self) -> Self:
        if self.mode == "by_key" and self.key is None:
            raise ValueError("Combining by key needs the field to match by")
        return self


class DataCombineInput(BaseModel):
    """The two lists, bound from earlier steps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    first: list[Any] = Field(default_factory=list, max_length=MAX_ITEMS)
    second: list[Any] = Field(default_factory=list, max_length=MAX_ITEMS)


class DataCombineOutput(BaseModel):
    """The one list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[Any]


def _objects(items: list[Any]) -> list[dict[str, Any]] | None:
    return items if all(isinstance(item, dict) for item in items) else None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Combine the two lists the way the config says."""
    combine = config if isinstance(config, DataCombineConfig) else DataCombineConfig()
    first = node_input.first if isinstance(node_input, DataCombineInput) else []
    second = node_input.second if isinstance(node_input, DataCombineInput) else []
    if combine.mode == "append":
        return Completed[DataCombineOutput](output=DataCombineOutput(items=[*first, *second]))
    left, right = _objects(first), _objects(second)
    if left is None or right is None:
        return Failed(
            error=WorkflowError(
                code="COMBINE_NEEDS_OBJECTS",
                message="Combining item by item needs both lists to hold objects",
            )
        )
    if combine.mode == "by_position":
        items = [{**one, **other} for one, other in zip(left, right, strict=False)]
    else:
        by_key = {other.get(combine.key): other for other in right if combine.key in other}
        items = [{**one, **by_key.get(one.get(combine.key), {})} for one in left]
    return Completed[DataCombineOutput](output=DataCombineOutput(items=items))
