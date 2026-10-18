"""IAM tenant entitlement replica reads (D3 B73)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.integration.iam_tenant_entitlement import TenantServiceEntitlement

_SHOP_AI_SERVICE_CODE = "shop_ai"


async def tenant_has_service(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    service_code: str,
) -> bool:
    result = await db.execute(
        select(TenantServiceEntitlement.id).where(
            TenantServiceEntitlement.tenant_id == tenant_id,
            TenantServiceEntitlement.service_code == service_code,
            TenantServiceEntitlement.disabled_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def list_tenants_with_service(
    db: AsyncSession,
    *,
    service_code: str,
) -> list[UUID]:
    result = await db.execute(
        select(TenantServiceEntitlement.tenant_id).where(
            TenantServiceEntitlement.service_code == service_code,
            TenantServiceEntitlement.disabled_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def count_active_shop_ai_entitlements(db: AsyncSession) -> int:
    q = (
        select(func.count())
        .select_from(TenantServiceEntitlement)
        .where(
            TenantServiceEntitlement.service_code == _SHOP_AI_SERVICE_CODE,
            TenantServiceEntitlement.disabled_at.is_(None),
        )
    )
    return int((await db.execute(q)).scalar_one())
