"""Knowledge Base repository (PostgreSQL async)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility


async def get_by_id(db: AsyncSession, kb_id: UUID) -> KnowledgeBase | None:
    return await db.get(KnowledgeBase, kb_id)


async def lock(db: AsyncSession, kb_id: UUID) -> KnowledgeBase | None:
    """The knowledge base row, locked `FOR UPDATE`.

    A teardown enumerates a base's documents and then deletes the base. A
    concurrent upload or sync inserting a `rag_documents` row takes `FOR KEY
    SHARE` on this parent for its foreign-key check, and `FOR UPDATE` conflicts
    with that - so locking the base first makes such an insert wait until the
    deletion commits and then fail its check, rather than surviving detached
    under the base's `ON DELETE SET NULL` (#1266).
    """
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update()
    )
    return result.scalars().first()


async def get_by_ids(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, KnowledgeBase]:
    """The collections for a set of ids, keyed by id, in one query.

    An id with no row is simply absent from the map, the same way `get_by_id`
    answers `None`: the caller decides what a reference to a collection that is
    gone means, and here it degrades an agent's reach rather than failing a run.
    """
    if not ids:
        return {}
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(ids)))
    return {kb.id: kb for kb in result.scalars()}


async def get_accessible(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID | None = None,
    see_all_org: bool,
    shared_org_ids: Sequence[UUID],
    shared_with_me: bool = False,
) -> list[KnowledgeBase]:
    """All KBs visible to this user: personal + reachable org rows + app.

    Args:
        see_all_org: True when the caller's `collections:view` reaches the
            whole organization; the ownership/visibility predicate on org rows
            is then skipped entirely.
        shared_org_ids: Org knowledge bases explicitly granted to this caller.
        shared_with_me: Narrow to org rows deliberately shared with the
            caller - org-visible or explicitly granted, and not their own -
            whatever the role's scope. Personal rows are the caller's by
            construction and app rows are the deployment's, so both are
            excluded: neither was shared *with* anybody.

    The predicate form of :func:`app.services.collection_access.readable_kb`;
    the two must keep agreeing, or a listing hides a base its detail route
    serves - or the reverse, which is worse.
    """
    if shared_with_me:
        if organization_id is None:
            return []
        shared_cond = (
            (KnowledgeBase.scope == KBScope.ORG.value)
            & (KnowledgeBase.organization_id == organization_id)
            & or_(
                KnowledgeBase.visibility == Visibility.ORG.value,
                KnowledgeBase.id.in_(shared_org_ids) if shared_org_ids else false(),
            )
            # IS DISTINCT FROM, not !=: an ownerless row is not the caller's.
            & KnowledgeBase.owner_user_id.is_distinct_from(user_id)
        )
        result = await db.execute(
            select(KnowledgeBase).where(shared_cond).order_by(KnowledgeBase.created_at)
        )
        return list(result.scalars().all())

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


async def create(
    db: AsyncSession,
    *,
    name: str,
    collection_name: str,
    scope: str,
    ingestion_config: dict[str, object],
    embedding_model: str,
    embedding_dim: int,
    embedding_provider: str,
    description: str | None = None,
    owner_user_id: UUID | None = None,
    organization_id: UUID | None = None,
    is_default: bool = False,
    embedding_secret_id: UUID | None = None,
    visibility: str | None = None,
) -> KnowledgeBase:
    """Create a knowledge base.

    `embedding_model`, `embedding_dim` and `embedding_provider` take no default
    on purpose. The first two are what the collection's vector column was
    created at, there is no interpretable value for "unknown", and a caller that
    forgets to record them would produce a row nobody can later decide whether
    it is safe to index into. The third is where those vectors were produced,
    and a row defaulting to whichever provider this module happened to name
    would be a claim about somebody else's data.
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
        embedding_provider=embedding_provider,
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
    embedding_provider: str | None = None,
    embedding_secret_id: UUID | None = None,
    clear_embedding_secret: bool = False,
) -> KnowledgeBase:
    """Apply what an update named, leaving what it did not alone.

    `clear_embedding_secret` is separate from a null `embedding_secret_id`
    because both have to be sayable: on a partial update null means "leave the
    key alone", so going back to the deployment's key needs a word of its own.
    """
    if name is not None:
        db_kb.name = name
    if description is not None:
        db_kb.description = description
    if ingestion_config is not None:
        db_kb.ingestion_config = ingestion_config
    if embedding_provider is not None:
        db_kb.embedding_provider = embedding_provider
    if clear_embedding_secret:
        db_kb.embedding_secret_id = None
    elif embedding_secret_id is not None:
        db_kb.embedding_secret_id = embedding_secret_id
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


async def list_org_scoped(db: AsyncSession, organization_id: UUID) -> list[KnowledgeBase]:
    """The org-scoped collections a tenant owns - the ones a deletion must remove.

    `knowledge_bases.organization_id` is `ON DELETE SET NULL`, but
    `ck_knowledge_bases_org_scope_has_org` forbids an org-scoped row with no org,
    so nulling one on organization delete violates the check (#9). These rows are
    deleted explicitly before the org row goes. Personal collections that merely
    carry this org's id are left to the `SET NULL`, which their scope permits.
    """
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.scope == KBScope.ORG.value,
        )
    )
    return list(result.scalars().all())


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
