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
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema


class MemoryErasureResult(BaseSchema):
    """What a "forget everything about me" actually removed.

    Two counts rather than one, because the two halves can fail independently: the
    notes are rows in this database, the mem0 memories are somebody else's service.
    A caller that reported one number could not tell somebody their notes are gone
    but their mem0 memories are not - which is the partial wipe this reports rather
    than hides.
    """

    notes_deleted: int
    mem0_agents_cleared: int


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
    """A page of somebody's notes, and what the platform could not include.

    `external_stores` is the honest half. An agent bound to mem0 keeps memories
    in somebody else's service, and this listing does not reach them: showing a
    page of native notes while calling it a complete inventory would be worse than
    saying which stores are outside it (#1594).
    """

    items: list[MemoryNoteRead]
    total: int
    external_stores: list[str] = Field(default_factory=list)


class MemoryNoteUpdate(BaseSchema):
    """Suppress a note, or restore one - the only field a person may set.

    Not the content: this surface is for reading what an agent wrote and deciding
    whether it may keep using it. A person editing an agent's note into something
    the agent then believes it learned is the authoring surface memory
    deliberately does not have.
    """

    active: bool
