"""Knowledge gap schemas: recorded searches, topics and what is done with them."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KnowledgeSearchRecord(BaseModel):
    """One search an agent made: what was asked, where, and how close the best match came."""

    model_config = ConfigDict(frozen=True)

    agent_id: UUID
    knowledge_base_ids: tuple[UUID, ...]
    query: str
    result_count: int
    top_similarity: float | None
