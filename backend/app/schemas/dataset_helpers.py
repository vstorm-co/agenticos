"""Dataset-owned configuration for the platform's evaluation pipelines."""

from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, Field

from app.schemas.base import BaseSchema


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("Instructions must contain text")
    return value


type PipelineInstructions = Annotated[
    str, Field(min_length=1, max_length=20_000), AfterValidator(_not_blank)
]


class DatasetHelper(BaseSchema):
    """A model and instructions; null inherits the tested model or code instructions."""

    model_profile_id: UUID | None = None
    instructions: PipelineInstructions | None = None


class DatasetHelpers(BaseSchema):
    """Helpers are pipeline configuration, not agents in a member's catalog."""

    generator: DatasetHelper = Field(default_factory=DatasetHelper)
    improver: DatasetHelper = Field(default_factory=DatasetHelper)


class DatasetHelperDefaults(BaseSchema):
    """The code-defined instructions shown before a dataset overrides them."""

    judge: str
    generator: str
    improver: str
