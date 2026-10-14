"""Schemas for datasets, their versions and their cases."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, ValidationError, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from app.schemas.base import BaseSchema
from app.schemas.resource_grant import VisibilityLiteral
from app.schemas.scoring import CHECK, DatasetScoring

CaseSourceLiteral = Literal["manual", "import", "conversation", "synthetic"]
DatasetChangeLiteral = Literal["add", "edit", "remove", "import", "generate"]
DatasetSort = Literal["name", "updated"]
DatasetFileFormat = Literal["csv", "jsonl"]
ToolOrderModeLiteral = Literal["any", "in_order", "exact"]

# One field of a case. Generous enough for a long conversation turn or a whole
# reference document, bounded so one import row cannot be a hundred megabytes.
MAX_CASE_TEXT = 32_000
MAX_HISTORY_TURNS = 200
MAX_TAGS = 20

NO_EXPECTATION = (
    "Say what the answer is tested against: a reference answer, a counter-example, "
    "an expected tool call or a check"
)


class CaseMessage(BaseSchema):
    """One earlier turn of a conversation the case continues."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CASE_TEXT)


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


def _known_checks(checks: list[CaseCheck]) -> list[CaseCheck]:
    """Refuse a check scoring does not know, or one whose parameters it would refuse."""
    for check in checks:
        CHECK.validate_python(check.model_dump(by_alias=True))
    return checks


def _clean_tags(tags: list[str]) -> list[str]:
    """Tags trimmed, deduplicated and order-kept, refusing one a CSV cannot hold.

    A comma separates tags in the CSV form, so a tag holding one would come back
    from an export as two.
    """
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip()
        if not value:
            continue
        if "," in value:
            raise ValueError("A tag cannot contain a comma")
        if len(value) > 64:
            raise ValueError("A tag is at most 64 characters")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > MAX_TAGS:
        raise ValueError(f"A case takes at most {MAX_TAGS} tags")
    return cleaned


class DatasetCaseContent(BaseSchema):
    """Everything a person writes about one case.

    The input is the turn the agent answers. `history` makes it a conversation
    prefix: the turns before it, oldest first, which the agent is handed as the
    conversation so far.
    """

    input: str = Field(min_length=1, max_length=MAX_CASE_TEXT)
    history: list[CaseMessage] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    reference_answer: str | None = Field(default=None, max_length=MAX_CASE_TEXT)
    counter_example: str | None = Field(
        default=None,
        max_length=MAX_CASE_TEXT,
        description="An answer known to be wrong, so a judge has something to compare against",
    )
    expected_tool_calls: list[ExpectedToolCall] = Field(default_factory=list, max_length=50)
    order_mode: ToolOrderModeLiteral = Field(
        default="any",
        description=(
            "How the agent's calls are matched against the expected ones: `any` order, "
            "`in_order` with other calls allowed between, or `exact`"
        ),
    )
    checks: list[CaseCheck] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        return _clean_tags(tags)

    @field_validator("checks")
    @classmethod
    def _checks(cls, checks: list[CaseCheck]) -> list[CaseCheck]:
        return _known_checks(checks)

    @model_validator(mode="after")
    def _expects_something(self) -> DatasetCaseContent:
        """Refuse a case with only an input: nothing could score the answer to it.

        Reported against `reference_answer`, the first of the four, so a form
        has an input to mark and an import names a field on the row.
        """
        if self.reference_answer or self.counter_example or self.expected_tool_calls or self.checks:
            return self
        raise ValidationError.from_exception_data(
            type(self).__name__,
            [
                InitErrorDetails(
                    type=PydanticCustomError("no_expectation", NO_EXPECTATION),
                    loc=("reference_answer",),
                    input=self.reference_answer,
                )
            ],
        )


class DatasetCaseCreate(DatasetCaseContent):
    """A case written by hand."""


class DatasetCaseUpdate(BaseSchema):
    """An edit to a case. What is left out keeps its value; the edit is a new version."""

    input: str | None = Field(default=None, min_length=1, max_length=MAX_CASE_TEXT)
    history: list[CaseMessage] | None = Field(default=None, max_length=MAX_HISTORY_TURNS)
    reference_answer: str | None = Field(default=None, max_length=MAX_CASE_TEXT)
    counter_example: str | None = Field(default=None, max_length=MAX_CASE_TEXT)
    expected_tool_calls: list[ExpectedToolCall] | None = Field(default=None, max_length=50)
    order_mode: ToolOrderModeLiteral | None = None
    checks: list[CaseCheck] | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str] | None) -> list[str] | None:
        return None if tags is None else _clean_tags(tags)

    @field_validator("checks")
    @classmethod
    def _checks(cls, checks: list[CaseCheck] | None) -> list[CaseCheck] | None:
        return None if checks is None else _known_checks(checks)


class EditedCaseContent(DatasetCaseContent):
    """An edit merged onto a stored case.

    The stored tags and checks are kept as they were written, so a rule that
    tightened since does not refuse an edit to another field; the case as a whole
    must still expect something.
    """

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        # Stored tags were cleaned on the way in; re-cleaning on the way out
        # would turn a later tightening of the rule into a listing that 500s.
        return tags

    @field_validator("checks")
    @classmethod
    def _checks(cls, checks: list[CaseCheck]) -> list[CaseCheck]:
        # The same reason: a check stored before a rule tightened is still read.
        return checks


class StoredCaseContent(EditedCaseContent):
    """A case's content as a stored revision holds it, read without re-judging it."""

    @model_validator(mode="after")
    def _expects_something(self) -> StoredCaseContent:
        # Cases stored before a case had to expect something still list and export.
        return self


class DatasetCaseRead(StoredCaseContent):
    """One case as a version holds it.

    `case_id` is the case across its edits; `id` is this revision of it, which is
    what a version and an eval result point at.
    """

    id: UUID
    case_id: UUID
    source: CaseSourceLiteral
    source_run_id: UUID | None = None
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None
    source_document_id: UUID | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime


class DatasetCaseList(BaseSchema):
    items: list[DatasetCaseRead]
    total: int
    version: int = Field(description="The version these cases are from; 0 before any case exists")


class DatasetCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=120, description="Unique per organization")
    description: str | None = Field(default=None, max_length=500)


class DatasetUpdate(BaseSchema):
    """What the dataset is called and for. Not versioned: no case changes."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class DatasetTagCount(BaseSchema):
    tag: str
    cases: int


class DatasetStats(BaseSchema):
    """What the newest version's cases test against, counted.

    One case can count under several of the expectations - a reference answer
    and a check, say - so those four do not sum to the case count; the sources do.
    """

    with_reference: int = Field(default=0, description="Cases with a reference answer")
    with_counter_example: int = Field(default=0, description="Cases with a counter-example")
    with_tool_calls: int = Field(default=0, description="Cases expecting at least one tool call")
    with_checks: int = Field(default=0, description="Cases with at least one check")
    by_source: dict[CaseSourceLiteral, int] = Field(
        default_factory=lambda: dict.fromkeys(get_args(CaseSourceLiteral), 0)
    )
    top_tags: list[DatasetTagCount] = Field(
        default_factory=list, description="The most used tags, most used first"
    )


class DatasetRead(BaseSchema):
    id: UUID
    name: str
    description: str | None = None
    visibility: VisibilityLiteral
    owner_user_id: UUID | None = None
    latest_version: int
    case_count: int
    can_edit: bool = Field(
        default=False, description="Whether the caller may change this dataset's cases"
    )
    pending_proposals: int = Field(
        default=0,
        description="Generated cases waiting for a decision; 0 for a caller who may not decide",
    )
    scoring: DatasetScoring = Field(
        default_factory=DatasetScoring, description="How this dataset's cases are scored"
    )
    stats: DatasetStats = Field(default_factory=DatasetStats)
    created_at: datetime
    updated_at: datetime | None = None


class DatasetList(BaseSchema):
    items: list[DatasetRead]
    total: int


class DatasetVersionRead(BaseSchema):
    id: UUID
    number: int
    case_count: int
    change: DatasetChangeLiteral
    changed_cases: int
    created_by_user_id: UUID | None = None
    created_at: datetime


class DatasetVersionList(BaseSchema):
    items: list[DatasetVersionRead]
    total: int


class DatasetCaseFromMessage(BaseSchema):
    """An answer from a conversation or from Activity, to be added as a case."""

    message_id: UUID = Field(description="The assistant message to turn into a case")
    answer_as: Literal["counter_example", "reference_answer"] = Field(
        default="counter_example",
        description="Keep the answer as what a good answer is not, or as what it is",
    )
