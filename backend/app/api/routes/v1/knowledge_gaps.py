"""Knowledge gap routes - what agents searched their knowledge bases for and did not find.

Every route carries `require(runs:view)`: a topic is made of people's questions,
which only a member who reads every run may see. Which knowledge base, agent,
topic and dataset the caller reaches is then the service's to resolve per row,
so a grant on one collection or dataset is honoured.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, KnowledgeGapSvc, VectorStoreSvc, require
from app.core.permissions import Perm
from app.schemas.knowledge_gap import (
    KnowledgeGapCasesAdded,
    KnowledgeGapContent,
    KnowledgeGapContentAdd,
    KnowledgeGapToDataset,
    KnowledgeGapTopicDetail,
    KnowledgeGapTopicList,
    TopicStatusLiteral,
)

router = APIRouter(dependencies=[Depends(require(Perm.RUNS_VIEW))])


@router.get("", response_model=KnowledgeGapTopicList)
async def list_gaps(
    service: KnowledgeGapSvc,
    ctx: Auth,
    topic_status: TopicStatusLiteral | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The gaps of every knowledge base the caller may read, the most asked first."""
    return await service.list_for_organization(ctx, status=topic_status, skip=skip, limit=limit)


@router.get("/collections/{knowledge_base_id}", response_model=KnowledgeGapTopicList)
async def list_collection_gaps(
    knowledge_base_id: UUID,
    service: KnowledgeGapSvc,
    ctx: Auth,
    topic_status: TopicStatusLiteral | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The questions one knowledge base could not answer, grouped, the most asked first."""
    return await service.list_for_knowledge_base(
        ctx, knowledge_base_id, status=topic_status, skip=skip, limit=limit
    )


@router.post(
    "/collections/{knowledge_base_id}/regroup",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def regroup_collection_gaps(
    knowledge_base_id: UUID, service: KnowledgeGapSvc, ctx: Auth
) -> None:
    """Group the knowledge base's waiting questions now, not at the next scheduled pass."""
    await service.regroup(ctx, knowledge_base_id)


@router.post(
    "/collections/{knowledge_base_id}/classify",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def classify_collection_answers(
    knowledge_base_id: UUID, service: KnowledgeGapSvc, ctx: Auth
) -> None:
    """Have a model read the knowledge base's recent answers for questions it could not answer.

    Refused while the organization has AI assistance switched off. The reading
    runs after the response, as the caller, in metered runs of the knowledge
    gap classifier that Activity lists; what it finds joins the topics.
    """
    await service.classify(ctx, knowledge_base_id)


@router.get("/agents/{agent_id}", response_model=KnowledgeGapTopicList)
async def list_agent_gaps(
    agent_id: UUID,
    service: KnowledgeGapSvc,
    ctx: Auth,
    topic_status: TopicStatusLiteral | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """What one agent searched for and did not find, in the knowledge bases the caller reads."""
    return await service.list_for_agent(ctx, agent_id, status=topic_status, skip=skip, limit=limit)


@router.get("/{topic_id}", response_model=KnowledgeGapTopicDetail)
async def get_gap(topic_id: UUID, service: KnowledgeGapSvc, ctx: Auth) -> Any:
    """A topic with its most recent questions and the answers they got."""
    return await service.read(ctx, topic_id)


@router.post("/{topic_id}/dismiss", response_model=KnowledgeGapTopicDetail)
async def dismiss_gap(topic_id: UUID, service: KnowledgeGapSvc, ctx: Auth) -> Any:
    """Mark a topic as needing no content. Its questions stay with it."""
    return await service.set_status(ctx, topic_id, "dismissed")


@router.post("/{topic_id}/reopen", response_model=KnowledgeGapTopicDetail)
async def reopen_gap(topic_id: UUID, service: KnowledgeGapSvc, ctx: Auth) -> Any:
    return await service.set_status(ctx, topic_id, "open")


@router.post(
    "/{topic_id}/dataset",
    response_model=KnowledgeGapCasesAdded,
    status_code=status.HTTP_201_CREATED,
)
async def add_gap_to_dataset(
    topic_id: UUID, data: KnowledgeGapToDataset, service: KnowledgeGapSvc, ctx: Auth
) -> Any:
    """Turn the topic's questions into cases of a dataset, in one new version."""
    return await service.add_to_dataset(ctx, topic_id, data.dataset_id)


@router.post("/{topic_id}/draft", response_model=KnowledgeGapTopicDetail)
async def draft_gap(topic_id: UUID, service: KnowledgeGapSvc, ctx: Auth) -> Any:
    """Ask the organization's drafting agent for the passage this topic is missing.

    A run of a system agent, metered and in Activity, refused while the
    organization has AI assistance off. The draft is kept on the topic for a
    person to check; nothing is added to the collection.
    """
    return await service.draft(ctx, topic_id)


@router.put("/{topic_id}/draft", response_model=KnowledgeGapTopicDetail)
async def save_gap_content(
    topic_id: UUID, data: KnowledgeGapContent, service: KnowledgeGapSvc, ctx: Auth
) -> Any:
    """Keep what a person wrote, or kept of the draft, as the topic's content."""
    return await service.save_content(ctx, topic_id, data)


@router.post(
    "/{topic_id}/document",
    response_model=KnowledgeGapTopicDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_gap_content(
    topic_id: UUID,
    data: KnowledgeGapContentAdd,
    service: KnowledgeGapSvc,
    vector_store: VectorStoreSvc,
    ctx: Auth,
) -> Any:
    """Add the topic's content to its knowledge base as a document; the topic is then covered.

    Takes edit access to the knowledge base. Refused while the content still
    asks for a detail to fill in, and - with `IDENTIFYING_CONTENT` - while it
    is flagged as possibly identifying somebody and `confirm_identifying` is
    not set.
    """
    return await service.add_content(ctx, topic_id, data, vector_store=vector_store)
