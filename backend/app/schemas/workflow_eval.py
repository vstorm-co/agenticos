"""A model step's evals: its cases, and how a try of them went."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.core.config import settings
from app.schemas.base import BaseSchema
from app.workflows.graph.model import pinned_output_fits

ExpectationKind = Literal["contains", "not_contains", "equals"]

MAX_CASES = 50
"""The most cases one step holds: a try starts a test run for each."""


class EvalExpectation(BaseSchema):
    """What the step's answer should say.

    `field` is a path into the step's output - `text`, `category`,
    `structured.amount` - read as text, or the whole output as JSON when empty.
    Matching ignores case and the space around the value: an eval checks what a
    model said, not how it was capitalised.
    """

    kind: ExpectationKind = "contains"
    field: str | None = Field(
        default="text",
        max_length=200,
        pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$",
        description="Where in the output to look; the whole output when null",
    )
    value: str = Field(min_length=1, max_length=2000)


class EvalCaseCreate(BaseSchema):
    """A case: an input the step should handle, and what its answer should say."""

    name: str = Field(min_length=1, max_length=120)
    run_input: dict[str, Any] = Field(
        default_factory=dict, description="What the test run starts with, as Test step's"
    )
    outputs: dict[UUID, dict[str, Any]] = Field(
        default_factory=dict,
        description="Known output of the steps before this one, by step id, as Test step's",
    )
    expectation: EvalExpectation

    @field_validator("outputs")
    @classmethod
    def _outputs_fit(cls, value: dict[UUID, dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
        for output in value.values():
            pinned_output_fits(output)
        known = json.dumps(list(value.values()), separators=(",", ":"), ensure_ascii=False)
        if len(known.encode()) > settings.WORKFLOW_RUN_MAX_INPUT_BYTES:
            raise ValueError(
                f"Known outputs may take at most {settings.WORKFLOW_RUN_MAX_INPUT_BYTES} bytes"
            )
        return value


class EvalCaseRead(EvalCaseCreate):
    id: UUID
    node_instance_id: UUID
    created_at: datetime | None = None


class EvalResult(BaseSchema):
    """How one case fared in a try."""

    eval_id: UUID
    name: str
    workflow_run_id: UUID | None = Field(
        default=None, description="The test run that tried it; null when it was refused"
    )
    status: str = Field(description="The run's status, or `refused` when none started")
    passed: bool | None = Field(
        default=None, description="Whether the answer said what was expected; null while running"
    )
    actual: str | None = Field(
        default=None, description="What the step answered at the path looked at, clipped"
    )
    reason: str | None = Field(default=None, description="Why it failed without an answer")
    cost_usd: float = 0.0


class EvalRunRead(BaseSchema):
    """One try of a step's cases, judged as the runs stand now."""

    id: UUID
    node_instance_id: UUID
    created_at: datetime | None = None
    results: list[EvalResult]
    passed: int
    failed: int
    pending: int
    cost_usd: float


class EvalCaseList(BaseSchema):
    """A step's cases, and its latest try."""

    items: list[EvalCaseRead]
    latest: EvalRunRead | None = None
