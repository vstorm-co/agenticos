"""A knowledge base's detail reports what its row on the listing reports."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentStatus
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.knowledge_base import KnowledgeBaseService

pytestmark = pytest.mark.anyio


async def _owner(db: AsyncSession) -> AuthContext:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")


async def _base_in_use(db: AsyncSession, ctx: AuthContext) -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name="Handbook",
        scope=KBScope.ORG.value,
        collection_name=f"handbook_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility=Visibility.ORG.value,
    )
    db.add(kb)
    await db.flush()
    for filename, chunks in (("leave.pdf", 3), ("travel.pdf", 2)):
        db.add(
            RAGDocument(
                organization_id=ctx.organization_id,
                knowledge_base_id=kb.id,
                writer_kind="document",
                collection_name=kb.collection_name,
                filename=filename,
                filesize=1,
                filetype="pdf",
                status="done",
                chunk_count=chunks,
            )
        )
    db.add(
        Agent(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            name="Support",
            slug=f"support-{uuid.uuid4().hex[:8]}",
            visibility=Visibility.ORG.value,
            status=AgentStatus.DRAFT.value,
            draft_spec=AgentSpec(name="Support", collection_ids=[kb.id]).model_dump(mode="json"),
        )
    )
    await db.flush()
    return kb


async def test_the_detail_counts_and_users_match_the_listing(db: AsyncSession) -> None:
    ctx = await _owner(db)
    kb = await _base_in_use(db, ctx)
    service = KnowledgeBaseService(db)

    (listed,) = (await service.list_readable(ctx)).items
    detail = await service.describe(await service.get(kb.id, ctx=ctx), ctx=ctx)

    assert (detail.document_count, detail.chunk_count) == (2, 5)
    assert [agent.name for agent in detail.used_by] == ["Support"]
    fields = ("document_count", "indexed_count", "chunk_count", "used_by", "shared_groups")
    assert {f: getattr(detail, f) for f in fields} == {f: getattr(listed, f) for f in fields}
    assert detail.can_edit is True
