"""The caller's own pinned sidebar items for the active organization.

Nested under `/me/nav-pins`. Both verbs are scoped to the signed-in user and
their active organization; there is no route for anybody else's pins. API keys
are refused by the shared authentication dependency because this is not a
public-API route.
"""

from typing import Any

from fastapi import APIRouter

from app.api.deps import ActiveOrg, CurrentUser, NavPinsSvc
from app.schemas.nav_pins import NavPinsRead, NavPinsUpdate

router = APIRouter()


@router.get("", response_model=NavPinsRead)
async def get_nav_pins(service: NavPinsSvc, user: CurrentUser, org: ActiveOrg) -> Any:
    """Return the caller's pins in pinned order; empty when none are saved."""
    ids = await service.get_for_user(user_id=user.id, organization_id=org.id)
    return NavPinsRead(item_ids=ids)


@router.put("", response_model=NavPinsRead)
async def replace_nav_pins(
    data: NavPinsUpdate, service: NavPinsSvc, user: CurrentUser, org: ActiveOrg
) -> Any:
    """Replace the caller's pins with the given ordered list."""
    ids = await service.replace(user_id=user.id, organization_id=org.id, data=data)
    return NavPinsRead(item_ids=ids)
