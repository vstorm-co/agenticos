"""Shop AI SKU gate for internal shop-ai (D3 B70/B73).

When `SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED` is on, requires an active row in
IAM CDC replica `tenant_service_entitlements` for service `shop_ai`. Storefront
Studio BFF still calls `assert_shop_ai_sku` when entitlement check is off here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.repositories.tenant_service_entitlement import tenant_has_service

SHOP_AI_SERVICE_CODE = "shop_ai"


async def require_shop_ai_entitlement(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
) -> None:
    if not settings.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED:
        return
    has = await tenant_has_service(
        db,
        tenant_id=minerp_tenant_id,
        service_code=SHOP_AI_SERVICE_CODE,
    )
    if not has:
        raise AuthorizationError(
            message="Shop AI is not enabled for this tenant",
            details={
                "minerp_tenant_id": str(minerp_tenant_id),
                "service_code": SHOP_AI_SERVICE_CODE,
            },
        )


async def tenant_has_shop_ai(db: AsyncSession, *, minerp_tenant_id: UUID) -> bool:
    if not settings.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED:
        return True
    return await tenant_has_service(
        db,
        tenant_id=minerp_tenant_id,
        service_code=SHOP_AI_SERVICE_CODE,
    )
