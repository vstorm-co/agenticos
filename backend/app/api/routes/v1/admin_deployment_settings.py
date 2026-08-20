"""The deployment's own settings, as its administrator edits them.

`CurrentAppAdmin` on every verb, which is the authority that already administers
users and tenants across the installation - not a permission from the catalog,
because a permission is scoped to an organization and this row is not in one.

The read is the whole form in one request; the write is a PATCH, so an
administrator editing the name does not have to resend the announcement. Images
are their own endpoints because they carry bytes rather than JSON, and their paths
are never in the update schema at all: the upload writes the storage key itself,
and a caller who could name it could point this deployment's public logo at
anything the storage backend holds.
"""

from typing import Any

from fastapi import APIRouter, File, UploadFile

from app.api.deps import CurrentAppAdmin, DeploymentSettingsSvc
from app.schemas.deployment_settings import DeploymentSettingsRead, DeploymentSettingsUpdate

router = APIRouter()


@router.get("", response_model=DeploymentSettingsRead)
async def get_deployment_settings(service: DeploymentSettingsSvc, _user: CurrentAppAdmin) -> Any:
    """Everything the settings page edits, including the notice fields."""
    return await service.read()


@router.patch("", response_model=DeploymentSettingsRead)
async def patch_deployment_settings(
    data: DeploymentSettingsUpdate,
    service: DeploymentSettingsSvc,
    user: CurrentAppAdmin,
) -> Any:
    """Write the fields this request named. `null` clears an override."""
    return await service.update(actor_user_id=user.id, data=data)


@router.post("/logo", response_model=DeploymentSettingsRead)
async def upload_logo(
    service: DeploymentSettingsSvc,
    user: CurrentAppAdmin,
    file: UploadFile = File(...),
) -> Any:
    """Replace the wordmark shown wherever this deployment names itself."""
    data = await file.read()
    return await service.set_image(
        actor_user_id=user.id, kind="logo", file_data=data, content_type=file.content_type
    )


@router.delete("/logo", response_model=DeploymentSettingsRead)
async def delete_logo(service: DeploymentSettingsSvc, user: CurrentAppAdmin) -> Any:
    """Go back to the built-in mark. 200 with the settings, not 204: the form
    re-renders from this response, and a 204 would leave it guessing."""
    return await service.clear_image(actor_user_id=user.id, kind="logo")


@router.post("/favicon", response_model=DeploymentSettingsRead)
async def upload_favicon(
    service: DeploymentSettingsSvc,
    user: CurrentAppAdmin,
    file: UploadFile = File(...),
) -> Any:
    """Replace the browser-tab icon."""
    data = await file.read()
    return await service.set_image(
        actor_user_id=user.id, kind="favicon", file_data=data, content_type=file.content_type
    )


@router.delete("/favicon", response_model=DeploymentSettingsRead)
async def delete_favicon(service: DeploymentSettingsSvc, user: CurrentAppAdmin) -> Any:
    """Go back to the built-in icon."""
    return await service.clear_image(actor_user_id=user.id, kind="favicon")
