"""B60 — Shop knowledge base list/create/delete guards."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.services.shop_tenant_kb import ShopTenantKnowledgeBaseService

pytestmark = pytest.mark.anyio


async def test_delete_requires_transfer_to() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    kb = MagicMock(id=kb_id, name="Shop FAQ", organization_id=org_id)

    db = AsyncMock()
    with (
        patch.object(
            ShopTenantKnowledgeBaseService,
            "_get_deletable_kb",
            new=AsyncMock(return_value=kb),
        ),
        patch.object(
            ShopTenantKnowledgeBaseService,
            "_list_faq_kbs",
            new=AsyncMock(return_value=[kb, MagicMock()]),
        ),
    ):
        with pytest.raises(BadRequestError, match="transfer_to is required"):
            await ShopTenantKnowledgeBaseService(db).delete(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                kb_id=kb_id,
                transfer_to=None,
            )


async def test_delete_rejects_only_faq_kb() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    kb = MagicMock(id=kb_id, name="Shop FAQ", organization_id=org_id)

    db = AsyncMock()
    with (
        patch.object(
            ShopTenantKnowledgeBaseService,
            "_get_deletable_kb",
            new=AsyncMock(return_value=kb),
        ),
        patch.object(
            ShopTenantKnowledgeBaseService,
            "_list_faq_kbs",
            new=AsyncMock(return_value=[kb]),
        ),
    ):
        with pytest.raises(BadRequestError, match="only FAQ knowledge base"):
            await ShopTenantKnowledgeBaseService(db).delete(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                kb_id=kb_id,
                transfer_to=uuid4(),
            )


async def test_create_requires_org_template_kb() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    db = AsyncMock()

    with patch(
        "app.services.shop_tenant_kb.knowledge_base_repo.list_org_scoped",
        new=AsyncMock(return_value=[]),
    ):
        from app.schemas.shop_knowledge_base import ShopKnowledgeBaseCreate

        with pytest.raises(BadRequestError, match="no knowledge base template"):
            await ShopTenantKnowledgeBaseService(db).create_for_shop(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                data=ShopKnowledgeBaseCreate(name="FAQ mới"),
            )


async def test_get_deletable_kb_not_found() -> None:
    db = AsyncMock()
    with patch(
        "app.services.shop_tenant_kb.knowledge_base_repo.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(NotFoundError):
            await ShopTenantKnowledgeBaseService(db)._get_deletable_kb(
                organization_id=uuid4(),
                kb_id=uuid4(),
            )
