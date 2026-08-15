"""The caller's own dashboard arrangement for the active organization.

Nested under `/me/dashboard-layout` and scoped to the current user and their
active organization on every verb — there is no route that reads or writes
somebody else's, and no permission gates this. A dashboard layout is a personal
preference, not organization data, so any signed-in member may read and write
**their own**.

`GET` answers 404 when nothing is saved; the frontend reads that as "fall back
to the audience default" rather than as a failure. `PUT` replaces the saved
arrangement (widget ids validated against the registry, so a typo is a 422 here
rather than a card that never renders). `DELETE` is reset-to-default.

`/presets` underneath is the shelf of named arrangements: list, save under a
name (409 on a duplicate, 422 at the per-person cap), delete. There is no
apply endpoint — applying a preset is the client writing its entries through
`PUT` above, so the active arrangement has exactly one write path.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ActiveOrg, CurrentUser, DashboardLayoutSvc, DashboardPresetSvc
from app.core.exceptions import NotFoundError
from app.schemas.dashboard_layout import (
    DashboardLayoutRead,
    DashboardLayoutUpdate,
    DashboardPresetCreate,
    DashboardPresetList,
    DashboardPresetRead,
)

router = APIRouter()


@router.get("", response_model=DashboardLayoutRead)
async def get_dashboard_layout(
    service: DashboardLayoutSvc, user: CurrentUser, org: ActiveOrg
) -> Any:
    """Return the caller's saved layout, or 404 when they have not saved one."""
    layout = await service.get_for_user(user_id=user.id, organization_id=org.id)
    if layout is None:
        raise NotFoundError(message="No saved dashboard layout", details={"org_id": org.id})
    return DashboardLayoutRead.model_validate(layout)


@router.put("", response_model=DashboardLayoutRead)
async def put_dashboard_layout(
    data: DashboardLayoutUpdate,
    service: DashboardLayoutSvc,
    user: CurrentUser,
    org: ActiveOrg,
) -> Any:
    """Replace the caller's saved arrangement for the active organization."""
    layout = await service.save(user_id=user.id, organization_id=org.id, data=data)
    return DashboardLayoutRead.model_validate(layout)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_dashboard_layout(
    service: DashboardLayoutSvc, user: CurrentUser, org: ActiveOrg
) -> Any:
    """Reset to the audience default by discarding the saved layout."""
    await service.reset(user_id=user.id, organization_id=org.id)
    return None


@router.get("/presets", response_model=DashboardPresetList)
async def list_dashboard_presets(
    service: DashboardPresetSvc, user: CurrentUser, org: ActiveOrg
) -> Any:
    """List the caller's named presets in the active organization, by name."""
    presets, total = await service.list_for_user(user_id=user.id, organization_id=org.id)
    return DashboardPresetList(
        items=[DashboardPresetRead.model_validate(preset) for preset in presets], total=total
    )


@router.post("/presets", response_model=DashboardPresetRead, status_code=status.HTTP_201_CREATED)
async def create_dashboard_preset(
    data: DashboardPresetCreate,
    service: DashboardPresetSvc,
    user: CurrentUser,
    org: ActiveOrg,
) -> Any:
    """Save an arrangement under a name — 409 when the caller already used it."""
    preset = await service.create(user_id=user.id, organization_id=org.id, data=data)
    return DashboardPresetRead.model_validate(preset)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_dashboard_preset(
    preset_id: UUID, service: DashboardPresetSvc, user: CurrentUser, org: ActiveOrg
) -> Any:
    """Delete one preset; one outside the caller's `(user, org)` scope is a 404."""
    await service.delete(user_id=user.id, organization_id=org.id, preset_id=preset_id)
    return None
