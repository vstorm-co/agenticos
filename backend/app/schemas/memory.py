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
    object_id: UUID | None = None
    auto_update: bool = False
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


MAX_AUTOMATIC_NOTE_CHARS = 4000


class MemoryNoteAutoUpdate(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    expected_updated_at: AwareDatetime | None


class MemoryNoteRestore(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime | None


class MemoryNoteRevisionRead(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    changed_by: Literal["agent", "person", "maintenance", "restore"]
    replaced_at: datetime
    source_conversation_id: UUID | None = None


class MemoryNoteRevisionList(BaseSchema):
    items: list[MemoryNoteRevisionRead]
    total: int


MemoryValue = StrictStr | StrictInt | StrictBool


class MemoryClaimEvidenceRead(BaseSchema):
    kind: Literal["message", "gmail", "webhook"]
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
    related_object_id: UUID | None = None
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
    value: MemoryValue | None = Field(
        default=None,
        description="New typed value. Omit or use null to preserve the previous value.",
    )
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

    @property
    def identity_key(self) -> str:
        if self.external_key is not None:
            return f"external:{self.external_key}"
        return f"name:{' '.join(self.name.casefold().split())}"


class MemoryRelationRef(BaseSchema):
    """A typed, single-valued relation from an object to another object."""

    model_config = ConfigDict(extra="forbid")
    predicate: Literal["client", "responsible", "part_of"]
    target: MemoryObjectRef

    @property
    def subject(self) -> str:
        return f"relation_{self.predicate}"

    def supports(self, source: MemoryObjectKind) -> bool:
        return (source, self.target.kind) == {
            "client": ("project", "company"),
            "responsible": ("project", "person"),
            "part_of": ("commitment", "project"),
        }[self.predicate]


class MemoryObjectRead(BaseSchema):
    id: UUID
    kind: MemoryObjectKind
    name: str
    external_key: str | None = None


class MemoryObjectPage(BaseSchema):
    items: list[MemoryObjectRead]
    next_cursor: UUID | None = None


class MemoryObjectTimeline(BaseSchema):
    object: MemoryObjectRead
    items: list[MemoryClaimRead]
    next_cursor: UUID | None = None


class MemoryObjectMergeCreate(BaseSchema):
    source_id: UUID
    confirmed: Literal[True]


class MemoryObjectMergeRead(BaseSchema):
    id: UUID
    source: MemoryObjectRead
    target_id: UUID
    merged_at: datetime


class MemoryObjectMergePage(BaseSchema):
    items: list[MemoryObjectMergeRead]
    next_cursor: UUID | None = None


class MemoryObjectBackfillRead(BaseSchema):
    cutoff: datetime
    scanned: int
    linked: int
    completed_at: datetime | None


class MemoryObjectBackfillRun(BaseSchema):
    restart: bool = False


class MemoryObjectBackfillAdvance(MemoryObjectBackfillRun):
    limit: int = Field(default=100, ge=1, le=200)


MemoryInboxMode = Literal["off", "shadow", "live"]
MemoryInboxSource = Literal["gmail", "webhook", "reviewed"]
MemoryInboxChange = Literal["changed", "cancelled", "review"]


class MemorySourceAuthorityUpdate(BaseSchema):
    """Select the only workflow allowed to automatically advance one property."""

    object_kind: MemoryObjectKind
    subject: str = Field(min_length=1, max_length=120)
    workflow_id: UUID | None


class MemorySourceAuthorityRead(MemorySourceAuthorityUpdate):
    """An organization owner's explicit source-of-record choice."""


class MemoryInboxRuleUpdate(BaseSchema):
    expected_version: int = Field(ge=0)
    mode: MemoryInboxMode
    recipient_ids: list[UUID] = Field(max_length=50)
    sources: list[MemoryInboxSource] = Field(max_length=3)
    include_review: bool = False
    shadow_model: bool = False


class MemoryInboxRuleRead(BaseSchema):
    version: int
    mode: MemoryInboxMode
    recipient_ids: list[UUID]
    sources: list[MemoryInboxSource]
    include_review: bool
    shadow_model: bool = False


MemoryInboxRecommendation = Literal["notify", "digest", "review", "ignore"]


class MemoryInboxShadowResult(BaseSchema):
    recommendation: MemoryInboxRecommendation


class MemoryInboxShadowCount(BaseSchema):
    baseline_notify: bool
    recommendation: MemoryInboxRecommendation
    count: int


class MemoryInboxDecisionCount(BaseSchema):
    change: MemoryInboxChange
    outcome: Literal["shadow", "delivered", "muted"]
    count: int


class MemoryInboxContext(BaseSchema):
    claim_id: UUID
    previous_id: UUID
    change: MemoryInboxChange
    source: MemoryInboxSource
    source_event_id: UUID | None = None


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
