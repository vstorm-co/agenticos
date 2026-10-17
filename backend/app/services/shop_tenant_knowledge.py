"""Resolve Minerp shop tenant → Agentra org knowledge bases (widget FAQ RAG)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.knowledge_base import KnowledgeBase
from app.repositories import knowledge_base_repo, organization_repo

if TYPE_CHECKING:
    from app.services.rag.filters import RetrievalScope


@dataclass(frozen=True, slots=True)
class ShopTenantKbContext:
    """KB rows and collection names for a storefront tenant."""

    organization_id: UUID
    effective_kb: KnowledgeBase
    collection_names: list[str]
    scopes: dict[str, "RetrievalScope"]


async def resolve_shop_tenant_kb(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID | None,
) -> ShopTenantKbContext | None:
    """Map `X-Tenant-Id` (minerp tenant) to org-scoped KB collections."""
    from app.services.rag.filters import scope_for_tenant

    org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
    if org is None:
        return None

    rows = await knowledge_base_repo.list_org_scoped(db, org.id)
    if not rows:
        return None

    effective: KnowledgeBase | None = None
    if kb_id is not None:
        candidate = await knowledge_base_repo.get_by_id(db, kb_id)
        if candidate is None or candidate.organization_id != org.id:
            return None
        effective = candidate
    else:
        effective = next((r for r in rows if r.is_default), None) or rows[0]

    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = (row.collection_name or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        names = [effective.collection_name]

    scopes = {kb.collection_name: scope_for_tenant(kb.vector_tenant) for kb in rows if kb.collection_name}
    for name in names:
        scopes.setdefault(name, scope_for_tenant(effective.vector_tenant))

    return ShopTenantKbContext(
        organization_id=org.id,
        effective_kb=effective,
        collection_names=names,
        scopes=scopes,
    )


async def require_kb_for_shop_organization(
    db: AsyncSession,
    *,
    organization_id: UUID,
    kb_id: UUID,
) -> KnowledgeBase:
    kb = await knowledge_base_repo.get_by_id(db, kb_id)
    if kb is None or kb.organization_id != organization_id:
        raise NotFoundError(
            message="Knowledge base not found",
            details={"knowledge_base_id": str(kb_id)},
        )
    return kb
