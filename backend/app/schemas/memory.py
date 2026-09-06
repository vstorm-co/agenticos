"""Schemas for the memory-erasure surface.

There is no operator authoring left to describe. Notes are written by the agent
and by nothing else, so the only shapes a person needs are the ones that say what
a deletion removed (#1470).
"""

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
