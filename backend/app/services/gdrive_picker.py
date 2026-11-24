"""Resolve organization Google accounts and browse their Drive folders."""

import asyncio
from uuid import UUID

from google.auth.exceptions import RefreshError
from httpx import HTTPStatusError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext
from app.repositories import mcp_connection as mcp_connection_repo
from app.schemas.gdrive_folder import GoogleDriveFolderPickerResponse, GoogleDrivePickerItem
from app.services.mcp_connection import McpConnectionService
from app.services.portals.google_oauth import DRIVE_GRANT_SCOPES
from app.services.rag.drive_api import DriveClient
from app.services.rag.remote_names import checked_drive_folder_id

_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def _folders(
    drive: DriveClient, *, parent: str, corpora: str, drive_id: str | None
) -> list[GoogleDrivePickerItem]:
    parent_id = checked_drive_folder_id(parent)
    query = f"mimeType='{_FOLDER_MIME_TYPE}' and '{parent_id}' in parents and trashed=false"
    folders: list[GoogleDrivePickerItem] = []
    page_token = None
    while True:
        page = drive.list_page(
            q=query,
            fields="nextPageToken, files(id, name)",
            page_size=100,
            page_token=page_token,
            corpora=corpora,
            drive_id=drive_id,
        )
        folders.extend(
            GoogleDrivePickerItem(id=checked_drive_folder_id(item.id), name=item.name)
            for item in page.files
        )
        page_token = page.next_page_token
        if not page_token:
            return folders


def _shared_drives(drive: DriveClient) -> list[GoogleDrivePickerItem]:
    drives: list[GoogleDrivePickerItem] = []
    page_token = None
    while True:
        page = drive.list_drives_page(
            fields="nextPageToken, drives(id, name)",
            page_size=100,
            page_token=page_token,
        )
        drives.extend(
            GoogleDrivePickerItem(id=checked_drive_folder_id(item.id), name=item.name)
            for item in page.drives
        )
        page_token = page.next_page_token
        if not page_token:
            return drives


class GoogleDrivePickerService:
    """Browse only an authorized Google account belonging to the current organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_folders(
        self, ctx: AuthContext, *, account_id: UUID, parent: str = "root"
    ) -> GoogleDriveFolderPickerResponse:
        """List folders with the account's current grant and controlled provider errors."""
        account_row = await mcp_connection_repo.get_account(self.db, account_id)
        if (
            account_row is None
            or account_row.scope != "org"
            or account_row.organization_id != ctx.organization_id
            or account_row.catalog_key != "google"
            or account_row.oauth_payload is None
        ):
            raise NotFoundError(message="Google account not found")

        grant = await McpConnectionService(self.db).account_grant(
            account_row, organization_id=ctx.organization_id
        )
        if grant is None or not DRIVE_GRANT_SCOPES.intersection(grant.scopes):
            raise NotFoundError(message="Google account not found")

        shared_drive_id: str | None = None
        if parent == "root":
            parent_id, corpora = "root", "user"
        elif parent.startswith("drive:"):
            shared_drive_id = checked_drive_folder_id(parent.removeprefix("drive:"))
            parent_id, corpora = shared_drive_id, "drive"
        else:
            parent_id, corpora = checked_drive_folder_id(parent), "allDrives"

        drive = DriveClient.from_oauth_grant(
            client_id=grant.client_id,
            client_secret=grant.client_secret,
            refresh_token=grant.refresh_token,
        )

        def read() -> GoogleDriveFolderPickerResponse:
            with drive:
                folders = _folders(
                    drive,
                    parent=parent_id,
                    corpora=corpora,
                    drive_id=shared_drive_id,
                )
                shared_drives = _shared_drives(drive) if parent == "root" else []
            return GoogleDriveFolderPickerResponse(drives=shared_drives, folders=folders)

        try:
            return await asyncio.to_thread(read)
        except HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 403:
                raise AuthorizationError(
                    message="Google Drive denied access to this listing."
                ) from None
            if status_code == 404:
                raise NotFoundError(
                    message="Google Drive folder not found or no longer accessible."
                ) from None
            if status_code == 401:
                raise ExternalServiceError(
                    message="Google Drive rejected the account authorization. Reconnect the account."
                ) from None
            raise ExternalServiceError(
                message="Google Drive could not list folders. Try again later."
            ) from None
        except RefreshError:
            raise ExternalServiceError(
                message="Google Drive account authorization expired. Reconnect the account."
            ) from None
