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
    AliasPath,
    ConfigDict,
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
ToolOrderModeLiteral = Literal["any", "in_order", "exact"]


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


_NAMED_SUBSCHEMAS = ("properties", "$defs", "definitions", "dependentSchemas")
_SUBSCHEMAS = (
    "items",
    "prefixItems",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "additionalItems",
    "contains",
    "propertyNames",
)


def _refused_keyword(schema: JsonValue) -> str | None:
    """The first keyword the schema check will not run, or `None`.

    A pattern runs through `re` inside the validator, with no deadline, so it
    belongs in a `regex` check; a reference outside the schema cannot be resolved.
    """
    if isinstance(schema, list):
        return next((found for item in schema if (found := _refused_keyword(item))), None)
    if not isinstance(schema, dict):
        return None
    for keyword in ("pattern", "patternProperties"):
        if keyword in schema:
            return keyword
    for keyword in ("$ref", "$dynamicRef"):
        reference = schema.get(keyword)
        if reference is not None and not str(reference).startswith("#"):
            return keyword
    for keyword in _NAMED_SUBSCHEMAS:
        named = schema.get(keyword)
        if isinstance(named, dict) and (found := _refused_keyword(list(named.values()))):
            return found
    return next(
        (found for keyword in _SUBSCHEMAS if (found := _refused_keyword(schema.get(keyword)))),
        None,
    )


class JsonSchemaCheck(BaseSchema):
    """The answer, or the value at `path`, is JSON matching a JSON Schema.

    `pattern` and `patternProperties` are refused - a `regex` check is the place
    for a pattern - and so is a `$ref` outside the schema itself.
    """

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
        refused = _refused_keyword(schema)
        if refused in ("pattern", "patternProperties"):
            raise ValueError(f"`{refused}` is not supported here; use a regex check with a path")
        if refused is not None:
            raise ValueError(f"`{refused}` may only point inside the schema (start with #)")
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
    """The judge grading every case on a rubric.

    `agent_id` is the dataset's own judge, one of the organization's judges;
    null is the platform's default eval judge. Each criterion is graded from 1
    to `scale_max` and passes at `pass_at` or above. `model_profile_id` runs the
    judge on another model than the one it publishes on.
    """

    enabled: bool = False
    agent_id: UUID | None = None
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
    each can be shown, and fixed, on its own. `unverified_quotes` are the parts of
    the answer the judge quoted that the answer does not hold.
    """

    scorer: ScorerKind
    name: str
    required: bool
    status: ScorerStatus
    score: float | None = None
    reason: str
    reason_code: str | None = None
    unverified_quotes: list[str] = Field(default_factory=list)
    judge_run_id: UUID | None = None


class ExpectedToolCall(BaseSchema):
    """A tool the agent should call, and the arguments that must match.

    `args` is a subset: a call passes when every key given here is present with
    this value, whatever else the agent also sent. Empty means only the tool name
    is checked.
    """

    tool: str = Field(min_length=1, max_length=200)
    args: dict[str, JsonValue] = Field(default_factory=dict)


class CaseCheck(BaseSchema):
    """One rule a case's answer is scored against, named by `type`.

    Only the shape is fixed here: an object with a `type`, and that rule's own
    parameters beside it. Which types exist and what each requires belongs to
    scoring (`app.schemas.scoring.Check`), checked when a case is written - and a
    stored check it no longer accepts is still read, and scored as an error.
    """

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True, extra="allow"
    )
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    type: str = Field(min_length=1, max_length=64)


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

    Two scores are graded alike only when every field matches. `agent_id` is the
    judge agent, `rubric_hash` fingerprints what it was asked: each criterion it
    graded and the scale. `model_profile_id` is the model it ran on - the
    dataset's choice, or the one its version publishes on.
    """

    agent_id: UUID | None = None
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

    What the case expected - `question`, `reference_answer`,
    `expected_tool_calls`, `checks` - is the scored revision's, which a later
    edit of the case does not change. `answer` is what the run answered, kept
    with the score so it reads without the run. `agent_id`, `agent_version_id`
    and `run_model` are the scored run's; `agent_name` and `agent_version` are
    filled where scores are listed. `eval_run_id` is the eval run that scored
    it, null for a score asked for by hand.
    """

    id: UUID
    dataset_id: UUID
    case_id: UUID
    case_revision_id: UUID
    question: str = Field(validation_alias=AliasPath("case_revision", "input"))
    reference_answer: str | None = Field(
        default=None, validation_alias=AliasPath("case_revision", "reference_answer")
    )
    expected_tool_calls: list[ExpectedToolCall] = Field(
        default_factory=list, validation_alias=AliasPath("case_revision", "expected_tool_calls")
    )
    order_mode: ToolOrderModeLiteral = Field(
        default="any", validation_alias=AliasPath("case_revision", "order_mode")
    )
    checks: list[CaseCheck] = Field(
        default_factory=list, validation_alias=AliasPath("case_revision", "checks")
    )
    answer: str | None = None
    run_id: UUID | None = None
    run_model: str | None = Field(default=None, validation_alias=AliasPath("run", "model_label"))
    agent_id: UUID | None = Field(default=None, validation_alias=AliasPath("run", "agent_id"))
    agent_version_id: UUID | None = Field(
        default=None, validation_alias=AliasPath("run", "agent_version_id")
    )
    agent_name: str | None = None
    agent_version: int | None = None
    eval_run_id: UUID | None = None
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


class JudgeCreate(BaseSchema):
    """A judge of a dataset's own, made from the default judge's definition."""

    name: str = Field(min_length=1, max_length=128)
    instructions: str = Field(min_length=1, max_length=20_000)
    model_profile_id: UUID | None = Field(
        default=None, description="The model it runs on; the organization's oldest if omitted"
    )


class ReviewRequest(BaseSchema):
    """Scores of one dataset to put in the review queue."""

    score_ids: list[UUID] = Field(min_length=1, max_length=500)


class ReviewRequested(BaseSchema):
    """What a review request changed: `queued` newly waiting, `already` waiting or decided."""

    queued: int
    already: int


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
