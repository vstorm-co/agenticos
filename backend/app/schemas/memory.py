"""Schemas for what a person may see and do about memory kept of them.

Two surfaces, and the difference between them is the whole design. Erasure says
what a deletion removed (#1470). The self-service view says what is written down
- read by its subject, and by a deployment administrator naming a tenant and a
person, never by an organization role: somebody who may edit an agent must not
thereby be able to read what every agent learned about a colleague (#1594).

There is still no authoring here. Notes are written by the agent and by nothing
else; what a person may do is suppress one, restore it, or delete it.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema


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
    deactivated_at: datetime | None = None
    """Set while the note is suppressed - not listed, not read, not editable by any tool."""


class MemoryNoteList(BaseSchema):
    """A page of somebody's notes."""

    items: list[MemoryNoteRead]
    total: int


class MemoryNoteUpdate(BaseSchema):
    """Suppress a note, or restore one - the only field a person may set.

    Not the content: this surface is for reading what an agent wrote and deciding
    whether it may keep using it. A person editing an agent's note into something
    the agent then believes it learned is the authoring surface memory
    deliberately does not have.
    """

    active: bool


class MemoryClaimRead(BaseSchema):
    """One recorded claim as its subject sees it: what it says, whose it is, where it came from."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID | None = None
    agent_name: str | None = None
    scope: Literal["profile", "agent"] = "agent"
    """`profile` serves every agent acting for the person; `agent` is one agent's relationship."""

    subject: str | None = None
    statement: str
    kind: str
    origin: Literal["agent", "person", "consolidation"]
    status: Literal["current", "disputed", "superseded", "merged", "retracted"]
    observed_at: datetime
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_id: UUID | None = None
    derived_from_count: int = 0


class MemoryClaimList(BaseSchema):
    items: list[MemoryClaimRead]
    total: int


class MemoryClaimDetail(MemoryClaimRead):
    """A claim with the claims it was drawn from and the one it replaced."""

    sources: list[MemoryClaimRead] = Field(default_factory=list)
    withheld: int = 0
    """Sources the reader may not see; counted so the ancestry is never silently shorter."""

    superseded: MemoryClaimRead | None = None


class MemoryClaimCorrect(BaseSchema):
    """A person's correction: the new statement, and when it began to hold."""

    statement: str = Field(min_length=1, max_length=600)
    effective_from: datetime | None = None
