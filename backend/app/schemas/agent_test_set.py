"""An agent's test set: what building it asks for, and what it made."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.case_generation import MAX_GENERATED
from app.schemas.resource_grant import VisibilityLiteral

JudgeReason = Literal[
    "one_model", "ai_off", "cannot_publish", "unknown_model", "shares_model", "judge_off"
]
"""Why the grader is not on a model of its own: only one model is set up, AI
assistance is off, the caller may not publish a grader, the agent has no model,
the grading a test set already had shares the agent's model, or its judge is off."""

GenerationSkipped = Literal["enough", "ai_off", "unavailable", "nothing_to_draft"]


class AgentTestSetRequest(BaseSchema):
    since: datetime | None = Field(
        default=None, description="Take the answers rated since then; every rating when omitted"
    )
    more: int | None = Field(
        default=None,
        ge=1,
        le=MAX_GENERATED,
        description="Write this many questions more, whatever the test set holds already",
    )


class AgentTestSetCounts(BaseSchema):
    rated_good: int = Field(description="Answers rated up, kept as the good answer")
    rated_bad: int = Field(description="Answers rated down, kept as the answer to avoid")
    skipped: int = Field(
        description=(
            "Rated answers left out: already in the test set, with no question before them, "
            "or in a conversation the caller cannot open"
        )
    )
    from_others: int = Field(description="Questions taken from other people's conversations")
    generated_requested: int = Field(description="Questions the case generator was asked to write")


class AgentTestSetJudge(BaseSchema):
    agent_id: UUID | None = Field(
        default=None, description="The dataset's own judge; none for the default judge"
    )
    independent: bool = Field(description="Whether it grades on another model than the agent's")
    reason: str | None = Field(
        default=None, description="Why it is not independent, in words for the person"
    )
    reason_code: JudgeReason | None = None
    kept: bool = Field(
        default=False,
        description="Whether this is the grading the test set already had, left as it was",
    )


class AgentTestSetBootstrap(BaseSchema):
    dataset_id: UUID
    visibility: VisibilityLiteral = Field(
        description=(
            "Who may read the test set. A new one is private, because it copies other "
            "people's questions; its Share action gives it to more readers"
        )
    )
    version: int = Field(description="The dataset's newest version once the rated answers are in")
    created: bool = Field(description="Whether the test set was created by this call")
    counts: AgentTestSetCounts
    generation_id: UUID | None = Field(
        default=None,
        description="The generation writing more questions; its drafts join the test set when ready",
    )
    generation_skipped: GenerationSkipped | None = Field(
        default=None, description="Why no question was asked for, when none was"
    )
    judge: AgentTestSetJudge
    gradable: int = Field(
        description=(
            "Questions the test set can grade that do not come from the evidence conversations, "
            "not counting those still being written"
        )
    )
    too_few: bool = Field(description="Whether that is too few to measure a change")


class AgentTestSetEstimate(BaseSchema):
    cost_usd: Decimal = Field(description="What writing the questions would cost; 0 when none")
    priced: bool = Field(description="False when the generator's model has no price")
    generate: int = Field(description="How many questions the estimate is for, at most")
