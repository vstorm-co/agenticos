"""Knowledge gap schemas: recorded searches, topics and what is done with them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema


class KnowledgeSearchRecord(BaseModel):
    """One search an agent made: what was asked, where, and how close the best match came."""

    model_config = ConfigDict(frozen=True)

    agent_id: UUID
    knowledge_base_ids: tuple[UUID, ...]
    query: str
    result_count: int
    top_similarity: float | None


TopicStatusLiteral = Literal["open", "dismissed"]


class KnowledgeGapAgent(BaseSchema):
    id: UUID
    name: str


class KnowledgeGapTopicRead(BaseSchema):
    """A group of questions one knowledge base could not answer.

    Every field but the status is read from the searches the topic still holds,
    so a question removed with its conversation leaves the topic with it.
    """

    id: UUID
    knowledge_base_id: UUID
    status: TopicStatusLiteral
    label: str = Field(description="The first question of the topic, as the agent searched it")
    question_count: int = Field(description="Searches in the topic that found nothing relevant")
    last_asked_at: datetime
    examples: list[str] = Field(description="Up to three of the questions, as searched")
    agents: list[KnowledgeGapAgent] = Field(description="The agents that searched for it")
    dismissed_at: datetime | None = None


class KnowledgeGapTopicList(BaseSchema):
    items: list[KnowledgeGapTopicRead]
    total: int
    ungrouped: int = Field(
        description="Misses waiting for the next grouping pass, so not in any topic yet"
    )


class KnowledgeGapQuestion(BaseSchema):
    """One time the question was asked, and what the search found."""

    search_id: UUID
    query: str = Field(description="What the agent searched for")
    question: str | None = Field(
        default=None, description="What the person asked, when the conversation is kept"
    )
    top_similarity: float | None
    result_count: int
    agent: KnowledgeGapAgent | None
    run_id: UUID
    conversation_id: UUID | None
    answer_message_id: UUID | None = Field(
        default=None, description="The agent's answer, which a dataset case is made from"
    )
    down_rating_comment: str | None = None
    asked_at: datetime


class KnowledgeGapTopicDetail(KnowledgeGapTopicRead):
    questions: list[KnowledgeGapQuestion]


class KnowledgeGapToDataset(BaseSchema):
    dataset_id: UUID


class KnowledgeGapCasesAdded(BaseSchema):
    dataset_id: UUID
    version: int | None = Field(
        description="The version the cases were added in; none if none were"
    )
    added: int
    skipped: int = Field(description="Questions with no stored answer the caller may read")
