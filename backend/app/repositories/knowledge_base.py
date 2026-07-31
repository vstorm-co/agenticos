"""Knowledge Base repository (PostgreSQL async)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import Visibility


async def get_by_id(db: AsyncSession, kb_id: UUID) -> KnowledgeBase | None:
    return await db.get(KnowledgeBase, kb_id)


async def get_accessible(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID | None = None,
    see_all_org: bool,
    shared_org_ids: Sequence[UUID],
) -> list[KnowledgeBase]:
    """All KBs visible to this user: personal + reachable org rows + app.

    Args:
        see_all_org: True when the caller's `collections:view` reaches the
            whole organization; the ownership/visibility predicate on org rows
            is then skipped entirely.
        shared_org_ids: Org knowledge bases explicitly granted to this caller.

    The predicate form of :func:`app.services.collection_access.readable_kb`;
    the two must keep agreeing, or a listing hides a base its detail route
    serves - or the reverse, which is worse.
    """
    conditions = [
        (KnowledgeBase.scope == KBScope.PERSONAL.value) & (KnowledgeBase.owner_user_id == user_id),
        KnowledgeBase.scope == KBScope.APP.value,
    ]
    if organization_id is not None:
        org_cond = (KnowledgeBase.scope == KBScope.ORG.value) & (
            KnowledgeBase.organization_id == organization_id
        )
        if not see_all_org:
            org_cond = org_cond & or_(
                KnowledgeBase.owner_user_id == user_id,
                KnowledgeBase.visibility == Visibility.ORG.value,
                KnowledgeBase.id.in_(shared_org_ids) if shared_org_ids else False,
            )
        conditions.append(org_cond)
    result = await db.execute(
        select(KnowledgeBase).where(or_(*conditions)).order_by(KnowledgeBase.created_at)
    )
    return list(result.scalars().all())


async def get_default_for_org(db: AsyncSession, organization_id: UUID) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.scope == KBScope.ORG.value,
            KnowledgeBase.is_default.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_documents_count(db: AsyncSession, kb_id: UUID) -> int:
    result = await db.execute(
        select(func.count(RAGDocument.id)).where(RAGDocument.knowledge_base_id == kb_id)
    )
    return result.scalar() or 0


async def create(
    db: AsyncSession,
    *,
    name: str,
    collection_name: str,
    scope: str,
    ingestion_config: dict[str, object],
    embedding_model: str,
    embedding_dim: int,
    description: str | None = None,
    owner_user_id: UUID | None = None,
    organization_id: UUID | None = None,
    is_default: bool = False,
    embedding_secret_id: UUID | None = None,
    visibility: str | None = None,
) -> KnowledgeBase:
    """Create a knowledge base.

    `embedding_model` and `embedding_dim` take no default on purpose. They
    are what the collection's vector column was created at, there is no
    interpretable value for "unknown", and a caller that forgets to record them
    would produce a row nobody can later decide whether it is safe to index
    into.
    """
    kb = KnowledgeBase(
        name=name,
        collection_name=collection_name,
        scope=scope,
        description=description,
        owner_user_id=owner_user_id,
        organization_id=organization_id,
        is_default=is_default,
        ingestion_config=ingestion_config,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embedding_secret_id=embedding_secret_id,
        **({"visibility": visibility} if visibility is not None else {}),
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


async def update(
    db: AsyncSession,
    *,
    db_kb: KnowledgeBase,
    name: str | None = None,
    description: str | None = None,
    ingestion_config: dict[str, object] | None = None,
) -> KnowledgeBase:
    if name is not None:
        db_kb.name = name
    if description is not None:
        db_kb.description = description
    if ingestion_config is not None:
        db_kb.ingestion_config = ingestion_config
    await db.flush()
    await db.refresh(db_kb)
    return db_kb


async def delete(db: AsyncSession, kb_id: UUID) -> bool:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        return False
    await db.delete(kb)
    await db.flush()
    return True


async def get_by_collection_name(db: AsyncSession, collection_name: str) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.collection_name == collection_name)
    )
    return result.scalars().first()


async def list_by_collection_name(db: AsyncSession, collection_name: str) -> list[KnowledgeBase]:
    """Every knowledge base claiming this collection name, oldest first.

    Plural because the column is not unique: two organizations can name a
    collection the same thing, and `get_by_collection_name` then answers with
    whichever row the database returns first. An authorization check built on
    that is right in every single-tenant test and wrong in production, so
    anything deciding access asks for all the candidates and picks its own.
    """
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.collection_name == collection_name)
        .order_by(KnowledgeBase.created_at)
    )
    return list(result.scalars().all())
