"""Schemas for scoring an answer against a dataset case.

Three things live here. The **check vocabulary** - what a case's `checks` may
say, validated when a case is written. A dataset's **scoring configuration** -
which scorers apply, which of them a case must pass, and the judge's rubric. And
a **score** - what each scorer found about one run's answer to one case, beside
a person's verdict on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import regex
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    Field,
    JsonValue,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.base import BaseSchema

MAX_PATTERN = 500
MAX_CHECK_VALUE = 2000
MAX_CRITERION = 1000

ScorerKind = Literal["check", "trajectory", "judge", "reference"]
ScorerStatus = Literal["pass", "fail", "skipped", "error"]
ReviewState = Literal["none", "pending", "done"]
ReviewSelect = Literal["none", "failed", "all"]


class TextCheck(BaseSchema):
    """A rule on the answer's text, or on one value inside a JSON answer.

    `path` reads into an answer that is JSON - `items.0.name` is the first item's
    name. Without one, the rule applies to the whole answer.
    """

    type: Literal["contains", "not_contains", "equals", "regex"]
    value: str = Field(min_length=1, max_length=MAX_CHECK_VALUE)
    path: str | None = Field(default=None, max_length=200)
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _pattern_compiles(self) -> TextCheck:
        if self.type == "regex":
            if len(self.value) > MAX_PATTERN:
                raise ValueError(f"A pattern is at most {MAX_PATTERN} characters")
            try:
                regex.compile(self.value)
            except regex.error as exc:
                raise ValueError(f"Not a valid regular expression: {exc}") from exc
        return self


class JsonSchemaCheck(BaseSchema):
    """The answer, or the value at `path`, is JSON matching a JSON Schema."""

    type: Literal["json_schema"]
    json_schema: dict[str, JsonValue] = Field(alias="schema")
    path: str | None = Field(default=None, max_length=200)

    @field_validator("json_schema")
    @classmethod
    def _schema_is_valid(cls, schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f"Not a valid JSON Schema: {exc.message}") from exc
        return schema


class CeilingCheck(BaseSchema):
    """The run cost no more than `value` dollars, or took no more than `value` ms."""

    type: Literal["max_cost_usd", "max_latency_ms"]
    value: float = Field(ge=0)


class JudgeCheck(BaseSchema):
    """A criterion for this case alone, graded by the eval judge.

    For what a rule cannot express - "refuses and does not reveal the customer's
    address" - beside the dataset's rubric, in the same judge call.
    """

    type: Literal["judge"]
    criterion: str = Field(min_length=1, max_length=MAX_CRITERION)


Check = Annotated[
    TextCheck | JsonSchemaCheck | CeilingCheck | JudgeCheck, Field(discriminator="type")
]
CHECK = TypeAdapter(Check)


class ChecksScorer(BaseSchema):
    """The checks on each case, and the ones every case of the dataset gets."""

    enabled: bool = True
    required: bool = True
    defaults: list[Check] = Field(default_factory=list, max_length=20)


class TrajectoryScorer(BaseSchema):
    """The tools the agent called against the case's expected calls."""

    enabled: bool = True
    required: bool = True


class RubricCriterion(BaseSchema):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=MAX_CRITERION)
    required: bool = True


class JudgeScorer(BaseSchema):
    """The eval judge grading every case on a rubric.

    Each criterion is graded from 1 to `scale_max` and passes at `pass_at` or
    above. `model_profile_id` runs the judge on another model than the one it
    publishes on.
    """

    enabled: bool = False
    model_profile_id: UUID | None = None
    scale_max: int = Field(default=5, ge=2, le=10)
    pass_at: int = Field(default=4, ge=1, le=10)
    criteria: list[RubricCriterion] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _pass_mark_on_the_scale(self) -> JudgeScorer:
        if self.pass_at > self.scale_max:
            raise ValueError("The pass mark cannot be above the top of the scale")
        names = [criterion.name for criterion in self.criteria]
        if len(set(names)) != len(names):
            raise ValueError("Two criteria share a name")
        return self


class ReferenceScorer(BaseSchema):
    """The judge comparing the answer with the case's reference answer."""

    enabled: bool = False
    required: bool = True


class ReviewScorer(BaseSchema):
    """Which scored results wait for a person: none, the ones that did not pass, or all."""

    select: ReviewSelect = "none"


class DatasetScoring(BaseSchema):
    """How a dataset's cases are scored. Each score keeps a copy of what it used."""

    checks: ChecksScorer = Field(default_factory=ChecksScorer)
    trajectory: TrajectoryScorer = Field(default_factory=TrajectoryScorer)
    judge: JudgeScorer = Field(default_factory=JudgeScorer)
    reference: ReferenceScorer = Field(default_factory=ReferenceScorer)
    review: ReviewScorer = Field(default_factory=ReviewScorer)


class ScorerResult(BaseSchema):
    """What one scorer found.

    `score` is normalized to 0..1. `reason_code` names why a scorer was skipped or
    failed to run - `ai_assistance_off`, `judge_unpublished`, `judge_budget` - so
    each can be shown, and fixed, on its own.
    """

    scorer: ScorerKind
    name: str
    required: bool
    status: ScorerStatus
    score: float | None = None
    reason: str
    reason_code: str | None = None
    judge_run_id: UUID | None = None


class CaseScoreCreate(BaseSchema):
    """Score a recorded run's answer against one case."""

    run_id: UUID
    version: int | None = Field(
        default=None,
        ge=1,
        description="The dataset version the case is read from; latest if omitted",
    )


class CaseVerdict(BaseSchema):
    """A person's verdict. `null` withdraws it, and the score waits for review again."""

    passed: bool | None
    note: str | None = Field(default=None, max_length=2000)


class JudgePin(BaseSchema):
    """Which judge graded a score.

    Two scores are graded alike only when every field matches. `rubric_hash`
    fingerprints what the judge was asked: each criterion it graded and the
    scale. `model_profile_id` is the model it ran on - the dataset's choice, or
    the one its version publishes on.
    """

    model_profile_id: UUID | None = None
    agent_version_id: UUID | None = None
    spec_version: int | None = None
    rubric_hash: str


class CaseScoreRead(BaseSchema):
    """One run's answer scored against one case.

    `passed` is what the scorers concluded; null means a required scorer could not
    run, so the case is unscored rather than passed. `human_passed` is a person's
    verdict, kept beside it. `outcome` is the one that counts: the person's when
    there is one, the scorers' otherwise.
    """

    id: UUID
    dataset_id: UUID
    case_id: UUID
    case_revision_id: UUID
    run_id: UUID | None = None
    results: list[ScorerResult]
    judge: JudgePin | None = None
    passed: bool | None = None
    review_state: ReviewState
    human_passed: bool | None = None
    human_note: str | None = None
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime

    @computed_field
    @property
    def outcome(self) -> bool | None:
        return self.human_passed if self.human_passed is not None else self.passed


class CaseScoreList(BaseSchema):
    items: list[CaseScoreRead]
    total: int


class PendingScore(CaseScoreRead):
    """A score in the review queue, with the dataset it belongs to."""

    dataset_name: str


class PendingDataset(BaseSchema):
    """How many scores wait in one dataset, by what the scorers concluded."""

    dataset_id: UUID
    name: str
    failed: int = 0
    unscored: int = 0
    passed: int = 0


class ReviewQueue(BaseSchema):
    """Scores waiting for a verdict: a page of them, oldest first, and every
    dataset that holds any, most waiting first."""

    items: list[PendingScore]
    total: int
    datasets: list[PendingDataset]
