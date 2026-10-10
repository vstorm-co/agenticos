"""Where a skill, a context file or a knowledge base is used (#2075)."""

from uuid import UUID

from app.schemas.base import BaseSchema


class AgentUsage(BaseSchema):
    """One agent whose draft binds the resource, named so a card can say which."""

    id: UUID
    name: str
