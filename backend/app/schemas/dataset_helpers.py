"""Dataset-owned configuration for the platform's evaluation pipelines."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import BaseSchema

type PipelineInstructions = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class DatasetHelper(BaseSchema):
    """A model and the dataset's guidance, added below the platform's rules for the helper.

    Null inherits the tested model, or adds no guidance. Who last changed the
    guidance and when is recorded by the server; a value sent for either is ignored.
    """

    model_profile_id: UUID | None = None
    instructions: PipelineInstructions | None = None
    instructions_updated_by: UUID | None = None
    instructions_updated_at: datetime | None = None


class DatasetHelpers(BaseSchema):
    """Helpers are pipeline configuration, not agents in a member's catalog."""

    generator: DatasetHelper = Field(default_factory=DatasetHelper)
    improver: DatasetHelper = Field(default_factory=DatasetHelper)


class DatasetHelperDefaults(BaseSchema):
    """The platform's rules for each helper, which a dataset's guidance is added below."""

    judge: str
    generator: str
    improver: str
