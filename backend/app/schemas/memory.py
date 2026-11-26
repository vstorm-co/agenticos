"""Schemas for what a person may see and do about memory kept of them.

Two surfaces, and the difference between them is the whole design. Erasure says
what a deletion removed (#1470). The self-service view says what is written down
- read by its subject, and by a deployment administrator naming a tenant and a
person, never by an organization role: somebody who may edit an agent must not
thereby be able to read what every agent learned about a colleague (#1594).

A person may correct their own note content, suppress it, restore it or delete it.
Corrections preserve the original agent-write timestamp and are audited separately.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from app.schemas.base import BaseSchema
from app.schemas.decision_episode import DecisionEpisode


class MemoryErasureResult(BaseSchema):
    """What a "forget everything about me" actually removed."""

    notes_deleted: int
    claims_deleted: int = 0


class MemoryNoteRead(BaseSchema):
    """One note as its subject sees it: what it says, and where it came from.

    The content is here because this surface exists to let somebody read what an
    agent wrote about them. Which agent wrote it and when are the provenance that
    makes a note actionable - "this is wrong" is a different sentence from "this
    was true last March" (#1594).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    name: str
    description: str | None = None
    content: str
    format: str
    kind: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    written_at: datetime | None = None
    deactivated_at: datetime | None = None
    """Set while the note is suppressed - not listed, not read, not editable by any tool."""


class MemoryNoteList(BaseSchema):
    """A page of somebody's notes."""

    items: list[MemoryNoteRead]
    total: int


class MemoryNoteUpdate(BaseSchema):
    """Suppress a personal note or restore it without changing its content."""

    active: bool


class MemoryNoteEdit(BaseSchema):
    """Correct a personal note using the revision displayed in the editor."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100_000)
    expected_updated_at: AwareDatetime | None


MemoryValue = StrictStr | StrictInt | StrictBool


class MemoryClaimEvidenceRead(BaseSchema):
    kind: Literal["message", "gmail"]
    source_id: str
    quote: str
    occurred_at: datetime


class MemoryClaimRead(BaseSchema):
    """One recorded claim as its subject sees it: what it says, whose it is, where it came from."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID | None = None
    agent_name: str | None = None
    scope: Literal["profile", "agent", "organization", "group"] = "agent"
    """`profile` serves every agent acting for the person; `agent` is one agent's relationship."""

    subject: str | None = None
    object_id: UUID | None = None
    statement: str
    value: MemoryValue | None = None
    kind: str
    origin: Literal["agent", "person", "consolidation"]
    status: Literal["current", "disputed", "superseded", "merged", "retracted"]
    observed_at: datetime
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_id: UUID | None = None
    derived_from_count: int = 0
    episode: DecisionEpisode | None = None


class MemoryClaimList(BaseSchema):
    items: list[MemoryClaimRead]
    total: int


class MemoryClaimDetail(MemoryClaimRead):
    """A claim with the claims it was drawn from and the one it replaced."""

    evidence: list[MemoryClaimEvidenceRead] = Field(default_factory=list)
    sources: list[MemoryClaimRead] = Field(default_factory=list)
    withheld: int = 0
    """Sources the reader may not see; counted so the ancestry is never silently shorter."""

    superseded: MemoryClaimRead | None = None
    conflicts: list[MemoryClaimRead] = Field(default_factory=list)


MAX_CONFLICT_CANDIDATES = 100


class MemoryConflictResolve(BaseSchema):
    """Confirm a claim against the exact set of alternatives the reviewer saw."""

    candidate_ids: list[UUID] = Field(min_length=1, max_length=MAX_CONFLICT_CANDIDATES)


class MemoryClaimCorrect(BaseSchema):
    """Replace a current claim or amend the exact interval of a historical observation."""

    statement: str = Field(min_length=1, max_length=600)
    effective_from: AwareDatetime | None = None
    episode: DecisionEpisode | None = None
    historical: bool = False


MemoryObjectKind = Literal["person", "company", "project", "commitment"]
MemoryLibrary = Literal["personal", "organization"]


class MemoryObjectRef(BaseSchema):
    """A named business object. An external key is qualified by its source."""

    model_config = ConfigDict(extra="forbid")
    kind: MemoryObjectKind
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    external_key: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=260)]
        | None
    ) = None


class MemoryObjectRead(BaseSchema):
    id: UUID
    kind: MemoryObjectKind
    name: str


class MemoryObjectPage(BaseSchema):
    items: list[MemoryObjectRead]
    next_cursor: UUID | None = None


class MemoryObjectTimeline(BaseSchema):
    object: MemoryObjectRead
    items: list[MemoryClaimRead]
    next_cursor: UUID | None = None


class MemoryClaimShare(BaseSchema):
    """Publish one reviewed claim to the organization or one of its groups."""

    group_id: UUID | None = None
    confirmed: Literal[True]


class MemoryNoteShare(MemoryClaimShare):
    expected_updated_at: AwareDatetime | None


class SharedMemoryNoteRead(BaseSchema):
    id: UUID
    name: str
    content: str


class SharedMemoryNotePage(BaseSchema):
    items: list[SharedMemoryNoteRead]
    next_cursor: UUID | None = None


class MemoryMailConfig(BaseSchema):
    """Gmail admission and Inbox controls reviewed by an organization operator."""

    model_config = ConfigDict(extra="forbid")
    sender: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[^\s@]+@[^\s@]+$", max_length=254)
    ]
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    commitment: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]
    object_key: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=260)]
        | None
    ) = None
    mode: Literal["shadow", "active"]
    notify: bool = False
    confirmed: Literal[True]


class MemoryMailSourceRead(BaseSchema):
    sender: str
    subject: str
    commitment: str
    object_key: str | None = None
    mode: str
    notify: bool
    last_outcome: str | None = None
    authorized: bool
