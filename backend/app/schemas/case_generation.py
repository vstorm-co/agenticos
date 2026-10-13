"""Schemas for generating dataset cases and deciding what was generated."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema
from app.schemas.dataset import DatasetCaseContent

CaseOriginLiteral = Literal["agent", "knowledge", "conversation", "red_team"]
GenerationStatusLiteral = Literal["running", "ready", "failed"]

# Decided in one request: a page of proposals, so "Accept all" on a page is one version.
MAX_DECIDED = 100
# Drafted in one generation: one generator run, and a review a person finishes.
MAX_GENERATED = 50
CASE_ORIGINS: tuple[CaseOriginLiteral, ...] = ("agent", "knowledge", "conversation", "red_team")


class CaseProposalRead(DatasetCaseContent):
    """A drafted case waiting for a decision, with what it was drafted from."""

    id: UUID
    generation_id: UUID
    origin: CaseOriginLiteral
    source_document_id: UUID | None = None
    source_run_id: UUID | None = None
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None
    created_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        # Cleaned when the proposal was stored; see `DatasetCaseRead`.
        return tags


class CaseProposalList(BaseSchema):
    items: list[CaseProposalRead]
    total: int


class CaseProposalDecision(BaseSchema):
    """One proposal to accept - as drafted, or as the reviewer edited it."""

    id: UUID
    content: DatasetCaseContent | None = Field(
        default=None, description="The case as edited; the proposal as drafted when omitted"
    )


class CaseProposalAccept(BaseSchema):
    items: list[CaseProposalDecision] = Field(min_length=1, max_length=MAX_DECIDED)


class CaseProposalDismiss(BaseSchema):
    ids: list[UUID] = Field(min_length=1, max_length=MAX_DECIDED)


class CaseGenerationRead(BaseSchema):
    id: UUID
    agent_id: UUID | None = None
    sources: list[CaseOriginLiteral]
    requested_count: int
    status: GenerationStatusLiteral
    error: str | None = None
    run_id: UUID | None = Field(
        default=None, description="The generator's run, with its cost, in Activity"
    )
    proposed_count: int
    accepted_count: int
    dismissed_count: int
    created_at: datetime
    finished_at: datetime | None = None


class CaseGenerationList(BaseSchema):
    items: list[CaseGenerationRead]


class CaseGenerationRequest(BaseSchema):
    """What a person asks the case generator to draft."""

    agent_id: UUID = Field(description="The agent the cases test")
    sources: list[CaseOriginLiteral] = Field(
        min_length=1, description="What to draft from; the count is shared evenly across them"
    )
    count: int = Field(default=20, ge=1, le=MAX_GENERATED)

    @field_validator("sources")
    @classmethod
    def _sources(cls, sources: list[CaseOriginLiteral]) -> list[CaseOriginLiteral]:
        # One order whatever was sent, so the same request always asks the same quotas.
        return [origin for origin in CASE_ORIGINS if origin in sources]


class SourcePlan(BaseSchema):
    """How many cases one source is asked for, and how much it has to draft from."""

    source: CaseOriginLiteral
    cases: int
    material: int = Field(
        description="Passages for knowledge, questions for conversations, tools for the agent"
    )


class CaseGenerationEstimate(BaseSchema):
    """What a generation would draft and roughly cost. Nothing is spent to answer it."""

    count: int
    sources: list[SourcePlan]
    excluded_collections: int = Field(
        description="Knowledge bases the agent uses that the caller may not read"
    )
    estimated_cost_usd: Decimal | None = Field(
        description="An estimate; null when the generator's model has no known price"
    )
