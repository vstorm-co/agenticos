"""Knowledge gap schemas: recorded searches, topics and what is done with them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    """An agent that searched, with what the console draws it with."""

    id: UUID
    name: str
    slug: str
    has_avatar: bool = Field(description="Whether `/agents/{id}/avatar` answers with an image")
    avatar_color: int | None = Field(
        default=None, description="The default avatar's colour slot; null picks one from the id"
    )


MAX_DRAFT_SOURCES = 12
"""The most sources a draft keeps, once verified."""


_LEGACY_LABELS = {"answer": "did_not_know", "rating": "missing_information", "none": "no_gap"}
"""The labels a classifier published before these were asked for, read as their successors."""


class ClassifiedAnswer(BaseSchema):
    """What a classifying model decided about one answer, cited by its number.

    Its labels say what they mean to the model, rather than naming the signal a
    gap is stored under: a weaker model read `answer` as "the agent answered".
    A classifier whose published instructions still name the old labels may
    answer in them, so they are read as the labels that replaced them.
    """

    number: int
    signal: Literal["did_not_know", "missing_information", "no_gap"]

    @field_validator("signal", mode="before")
    @classmethod
    def _successor(cls, value: object) -> object:
        return _LEGACY_LABELS.get(value, value) if isinstance(value, str) else value


class KnowledgeGapClassification(BaseSchema):
    """A classifying model's verdicts on the answers it was given, as it answers.

    Answers are cited by the number they were given in the prompt, for the
    reason :class:`KnowledgeGapDraft` cites by number.
    """

    answers: list[ClassifiedAnswer] = Field(max_length=200)


class KnowledgeGapDraft(BaseSchema):
    """The passage a drafting model proposes for a topic, as it answers.

    Documents and questions are cited by the number they were given in the
    prompt, which a model copies reliably, where an id it would have to repeat
    it may garble.
    """

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000, description="Markdown")
    documents: list[int] = Field(
        default_factory=list,
        max_length=50,
        description="The numbers of the documents the draft builds on",
    )
    questions: list[int] = Field(
        default_factory=list,
        max_length=50,
        description="The numbers of the questions the draft answers",
    )


SourceKind = Literal["document", "question"]


class KnowledgeGapSource(BaseSchema):
    """What a draft rests on: a document of the knowledge base, or one of the topic's questions."""

    kind: SourceKind
    id: UUID = Field(description="A document's id, or a search's id for a question")


class KnowledgeGapReport(BaseSchema):
    """A proposed passage for a topic: what `report_knowledge_gap` records.

    The contract a drafting run and the authoring assistant both report through.
    It proposes content and nothing more: a person reads it and adds a document.
    Every source is verified before the draft is kept - a document must be in the
    topic's knowledge base, a question must be one of the topic's - and one that
    is not is left out and counted, never shown.
    """

    topic_id: UUID
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    sources: list[KnowledgeGapSource] = Field(default_factory=list, max_length=50)


class KnowledgeGapSourceRead(KnowledgeGapSource):
    label: str = Field(description="The document's file name, or the question as searched")


class KnowledgeGapDraftRead(BaseSchema):
    title: str
    content: str
    sources: list[KnowledgeGapSourceRead] = Field(
        description="Verified sources that still exist; at most twelve"
    )
    unverified: int = Field(description="Sources the draft named that could not be verified")
    drafted_at: datetime
    run_id: UUID | None = Field(description="The run that wrote it, in Activity")


class KnowledgeGapTopicRead(BaseSchema):
    """A group of questions one knowledge base could not answer.

    Every field but the status is read from the searches the topic still holds,
    so a question removed with its conversation leaves the topic with it.
    """

    id: UUID
    knowledge_base_id: UUID
    knowledge_base_name: str
    status: TopicStatusLiteral
    label: str = Field(description="The first question of the topic, as the agent searched it")
    question_count: int = Field(description="Searches in the topic that found nothing relevant")
    last_asked_at: datetime
    examples: list[str] = Field(description="Up to three of the questions, as searched")
    agents: list[KnowledgeGapAgent] = Field(description="The agents that searched for it")
    dismissed_at: datetime | None = None
    has_draft: bool = False
    can_edit: bool = Field(
        default=False,
        description=(
            "Whether THIS caller may dismiss or reopen the topic: they may change its "
            "knowledge base, by their role or a grant on it. Hides controls; the "
            "server re-checks."
        ),
    )


class KnowledgeGapCollectionCount(BaseSchema):
    knowledge_base_id: UUID
    knowledge_base_name: str
    topics: int
    questions: int


class KnowledgeGapTopicList(BaseSchema):
    items: list[KnowledgeGapTopicRead]
    total: int
    by_knowledge_base: list[KnowledgeGapCollectionCount] = Field(
        description="Every topic matching the filters, counted per knowledge base"
    )
    ungrouped: int = Field(
        description="Misses waiting for the next grouping pass, so not in any topic yet"
    )
    can_regroup: bool = Field(
        default=False,
        description=(
            "Whether the caller may group this knowledge base's waiting misses now; "
            "false for a list of the organization's or an agent's gaps"
        ),
    )
    unchecked: int = Field(
        default=0,
        description=(
            "Recent answers in this knowledge base's runs that no model has read for "
            "knowledge gaps yet; 0 for a list of the organization's or an agent's gaps"
        ),
    )


class KnowledgeGapQuestion(BaseSchema):
    """One time the question was asked, and what the search found."""

    search_id: UUID
    query: str = Field(description="What the agent searched for")
    signal: Literal["retrieval", "answer", "rating"] = Field(
        default="retrieval",
        description=(
            "What makes it a miss: `retrieval` when the search found nothing close "
            "enough, `answer` when the agent said it did not know, `rating` when a "
            "reader's thumbs-down comment said what was missing"
        ),
    )
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
    draft: KnowledgeGapDraftRead | None = Field(
        default=None, description="Proposed content, never added to the collection by itself"
    )


class KnowledgeGapToDataset(BaseSchema):
    dataset_id: UUID


class KnowledgeGapCasesAdded(BaseSchema):
    dataset_id: UUID
    version: int | None = Field(
        description="The version the cases were added in; none if none were"
    )
    added: int
    skipped: int = Field(description="Questions with no stored answer the caller may read")
