"""Which of a dataset's keys an agent's sources cover, as the API shows it."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.agent import KnowledgeSourceKind
from app.schemas.base import BaseSchema
from app.schemas.scoring import MAX_KEY_LABEL

CoverageVerdict = Literal["covered", "not_covered", "unsure"]

MAX_WHY = 500


class JudgedKey(BaseSchema):
    """The source coverage agent's verdict on one label."""

    key: str = Field(max_length=MAX_KEY_LABEL)
    verdict: CoverageVerdict
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    why: str = Field(default="", max_length=MAX_WHY)


class JudgedCoverage(BaseSchema):
    """What the source coverage agent answers: a verdict per label."""

    keys: list[JudgedKey] = Field(default_factory=list)


class KeyCoverageRequest(BaseSchema):
    """Judge the dataset's keys against this agent's published version."""

    agent_id: UUID


class StoredSource(BaseSchema):
    """A source a verdict rests on, as a report stores it."""

    kind: KnowledgeSourceKind
    id: UUID
    name: str


class StoredItem(BaseSchema):
    """One label's verdict, as a report stores it: no value, ever."""

    key: str
    verdict: CoverageVerdict
    sources: list[StoredSource]
    why: str | None


class CoverageSource(BaseSchema):
    """A source a verdict rests on. `name` is null for one the reader may not see."""

    kind: KnowledgeSourceKind
    id: UUID | None
    name: str | None


class CoverageItem(BaseSchema):
    """One key label, whether a source covers it, and which.

    `why` is null unless the reader may see every source the judge was shown: it
    may quote what any of them holds.
    """

    key: str
    verdict: CoverageVerdict
    sources: list[CoverageSource]
    why: str | None


class KeyCoverageReportRead(BaseSchema):
    """An agent's coverage of a dataset's keys, still being judged, or why it could not be.

    Labels and source names only: a key's value never reaches a report.
    `unseen_sources` counts the sources the agent binds that the person who asked
    could not see, so none of them was read. `current` is false once the agent was
    published again, the dataset gained a version, or a source it read changed since
    - `sources_changed` says which: the report judged other sources or other keys,
    and Improve no longer reads it.
    """

    id: UUID
    agent_id: UUID
    dataset_id: UUID
    dataset_version: int
    status: Literal["running", "ready", "failed"]
    items: list[CoverageItem]
    unseen_sources: int
    current: bool
    sources_changed: bool
    error: str | None
    created_at: datetime
    finished_at: datetime | None
