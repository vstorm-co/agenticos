"""Bounded evidence from one decision; never a generalized instruction."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import BaseSchema

Alternative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class DecisionEpisode(BaseSchema):
    situation: str = Field(min_length=1, max_length=1200)
    choice: str = Field(min_length=1, max_length=600)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=8)
    expected_outcome: str | None = Field(default=None, max_length=1200)
    actual_outcome: str | None = Field(default=None, max_length=1200)
    correction: str | None = Field(default=None, max_length=1200)


class ImproveCaseReview(BaseSchema):
    """The human-reviewed fields that leave personal memory as a case in a dataset."""

    confirmed: Literal[True]
    dataset_id: UUID
    input: str = Field(min_length=1, max_length=32000)
    reference_answer: str = Field(min_length=1, max_length=32000)
