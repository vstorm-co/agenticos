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


TopicStatusLiteral = Literal["open", "dismissed", "covered"]

DecidedStatusLiteral = Literal["open", "dismissed"]
"""What a person sets a topic to by hand; it is covered by adding its content."""


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
    signal: Literal["did_not_know", "missing_information", "no_gap", "refused"]

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
    context_files: list[int] = Field(
        default_factory=list,
        max_length=50,
        description="The numbers of the context files the draft builds on or that answer it",
    )
    already_covered: bool = Field(
        default=False,
        description=(
            "True when a context file or a document listed already answers the questions; "
            "cite it, and say so in the content instead of repeating it"
        ),
    )


SourceKind = Literal["document", "question", "context"]


class KnowledgeGapSource(BaseSchema):
    """What a draft rests on: a document, one of the topic's questions, or a context file."""

    kind: SourceKind
    id: UUID = Field(
        description="A document's id, a search's id for a question, or a context file's id"
    )


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
    already_covered: bool = False


class KnowledgeGapSourceRead(KnowledgeGapSource):
    label: str = Field(
        description="The document's file name, the question as searched, or the context file's name"
    )


class KnowledgeGapFlag(BaseSchema):
    """Something in a topic's content that may identify a person, for a person to check."""

    kind: Literal["personal_data", "shared"] = Field(
        description=(
            "`personal_data` for a match of the personal data detectors, `shared` for a "
            "number or code the content repeats from the topic's questions, answers or comments"
        )
    )
    value: str = Field(
        max_length=200,
        description="The detector's category for `personal_data`, the repeated token for `shared`",
    )
    count: int = Field(default=1, ge=1)


class KnowledgeGapContent(BaseSchema):
    """What a person writes, or keeps of a draft, as a topic's content."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000, description="Markdown")


class KnowledgeGapContentAdd(KnowledgeGapContent):
    confirmed: list[KnowledgeGapFlag] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "The flags the caller checked and confirms, as they were shown. Adding is "
            "refused while the content holds a flag not among them"
        ),
    )


class KnowledgeGapDraftRead(BaseSchema):
    title: str
    content: str
    sources: list[KnowledgeGapSourceRead] = Field(
        description="Verified sources that still exist; at most twelve"
    )
    unverified: int = Field(description="Sources the draft named that could not be verified")
    drafted_at: datetime
    run_id: UUID | None = Field(
        description="The run that wrote it, in Activity; none for content a person wrote"
    )
    already_covered: bool = Field(
        default=False,
        description="The drafter found the questions answered by a source it cites",
    )
    blanks: list[str] = Field(
        default_factory=list,
        description="The details still to fill in, each written `{{...}}` in the content",
    )
    flags: list[KnowledgeGapFlag] = Field(
        default_factory=list,
        description="What may identify somebody, which adding the content asks to confirm",
    )


class KnowledgeGapDocument(BaseSchema):
    """The document a person added to cover a topic."""

    id: UUID
    filename: str
    status: str = Field(description="The document's ingestion status")


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
    asker_count: int = Field(
        default=0,
        description="Distinct people who asked; everybody who asked anonymously counts as one",
    )
    last_asked_at: datetime
    examples: list[str] = Field(description="Up to three of the questions, as searched")
    agents: list[KnowledgeGapAgent] = Field(description="The agents that searched for it")
    dismissed_at: datetime | None = None
    covered_at: datetime | None = None
    covered_by: KnowledgeGapDocument | None = Field(
        default=None, description="The document added for it, while it is covered"
    )
    has_draft: bool = False
    can_edit: bool = Field(
        default=False,
        description=(
            "Whether THIS caller may dismiss, reopen, draft or add the topic's content: "
            "they may change its knowledge base, by their role or a grant on it. Hides "
            "controls; the server re-checks."
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
        default=None,
        description="Proposed or written content, added to the collection only by a person",
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
