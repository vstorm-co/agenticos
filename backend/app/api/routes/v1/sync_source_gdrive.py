"""Google Drive browsing for the sync-source setup."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, GoogleDrivePickerSvc, require
from app.core.permissions import Perm
from app.schemas.gdrive_folder import GoogleDriveFolderPickerResponse

router = APIRouter(dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))])


@router.get("/gdrive/folders", response_model=GoogleDriveFolderPickerResponse)
async def list_google_drive_folders(
    service: GoogleDrivePickerSvc,
    ctx: Auth,
    account: UUID = Query(...),
    parent: str = Query("root"),
) -> Any:
    """List Shared Drives and My Drive folders for an org account."""
    return await service.list_folders(ctx, account_id=account, parent=parent)
