"""Google Drive sync connector for RAG ingestion.

Fetches files from Google Drive using a Google service account. Credentials are
supplied per-source via the `service_account_json` config field (a copy of the
JSON key file contents), and only that way - a source runs on the credential
its own configuration carries or it does not run.

Setup:
1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Share the target Drive folder with the service account email
4. Paste the JSON contents into the "Service Account JSON" field when
   creating a sync source
"""

import asyncio
import json as _json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload

from app.core.exceptions import BadRequestError
from app.services.rag.connectors import BaseSyncConnector, RemoteFile
from app.services.rag.remote_names import checked_drive_folder_id

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

GOOGLE_DOCS_EXPORT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


class GoogleDriveConnector(BaseSyncConnector):
    """Google Drive connector using a service account.

    Credentials are read from `config["service_account_json"]` (a JSON string)
    and from nowhere else.
    """

    CONNECTOR_TYPE: ClassVar[str] = "gdrive"
    DISPLAY_NAME: ClassVar[str] = "Google Drive"
    CONFIG_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "service_account_json": {
            "type": "textarea",
            "required": True,
            "label": "Service Account JSON",
            "help": "Paste the full contents of your Google service account JSON key file.",
            "secret": True,
        },
        "folder_id": {
            "type": "string",
            "required": True,
            "label": "Google Drive Folder ID",
            "help": "The ID from the folder URL: drive.google.com/drive/folders/{THIS_ID}",
        },
        "include_subfolders": {
            "type": "boolean",
            "required": False,
            "default": True,
            "label": "Include subfolders",
        },
    }

    def _get_drive_service(self, config: dict) -> Resource:
        """Build an authenticated Drive client from the source's own credential.

        **There is no deployment-wide fallback.** A `GOOGLE_DRIVE_CREDENTIALS_FILE`
        one used to stand in whenever the config field was absent, which meant a
        tenant's `folder_id` chose what was listed under the *operator's* service
        account and whatever that account had been shared - turning a source's own
        configuration into a reach across organizations. The field is required by
        `CONFIG_SCHEMA`, so the fallback only ever covered rows written before it
        existed.

        Raises:
            BadRequestError: the source carries no service account credential.
        """
        sa_json = config.get("service_account_json")
        if not sa_json:
            raise BadRequestError(
                message=(
                    "This Google Drive source has no service account credential. "
                    "Add the service account JSON to the source configuration."
                ),
                details={"field": "service_account_json"},
            )
        info = _json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("drive", "v3", credentials=creds)

    async def validate_config(self, config: dict) -> tuple[bool, str | None]:
        """Validate required fields and the shape of the folder id.

        Connectivity is still checked at sync time. The folder id is checked
        here as well as where the query is built, so a hostile value is answered
        by the route that accepted it rather than by a sync log an hour later.
        The two cannot disagree - both ask `checked_drive_folder_id`.
        """
        is_valid, error = await super().validate_config(config)
        if not is_valid:
            return False, error
        try:
            checked_drive_folder_id(config["folder_id"])
        except BadRequestError as exc:
            return False, exc.message
        return True, None

    def _list_folder(
        self, service: Resource, folder_id: str, include_subfolders: bool
    ) -> list[RemoteFile]:
        """Recursively list files in a Google Drive folder (sync, runs in thread).

        The parent id is checked rather than escaped, here where the query is
        built: this is the one funnel both the configured folder and every
        sub-folder id pass through, so nothing reaches the query language
        unchecked whichever way in it came - a route, a clone, or a row older
        than the check.
        """
        files: list[RemoteFile] = []
        query = f"'{checked_drive_folder_id(folder_id)}' in parents and trashed = false"
        page_token = None

        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    pageSize=100,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageToken=page_token,
                )
                .execute()
            )

            for f in response.get("files", []):
                mime = f.get("mimeType", "")

                if mime == "application/vnd.google-apps.folder":
                    if include_subfolders:
                        files.extend(self._list_folder(service, f["id"], include_subfolders))
                    continue

                name = f.get("name", "")

                if mime in GOOGLE_DOCS_EXPORT:
                    export_mime, ext = GOOGLE_DOCS_EXPORT[mime]
                    if not name.endswith(ext):
                        name = f"{name}{ext}"
                    mime = export_mime

                modified_at = None
                if f.get("modifiedTime"):
                    modified_at = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00"))

                files.append(
                    RemoteFile(
                        id=f["id"],
                        name=name,
                        mime_type=mime,
                        size=int(f.get("size", 0)),
                        modified_at=modified_at,
                        source_path=f"gdrive://{f['id']}",
                    )
                )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    async def list_files(self, config: dict) -> list[RemoteFile]:
        """List all files in the configured Google Drive folder."""
        folder_id = config["folder_id"]
        include_subfolders = config.get("include_subfolders", True)

        def _list():
            service = self._get_drive_service(config)
            return self._list_folder(service, folder_id, include_subfolders)

        return await asyncio.to_thread(_list)

    async def _fetch(self, file: RemoteFile, dest_path: Path, config: dict) -> None:
        """Download a file from Google Drive to the path the base class chose.

        For Google Docs formats, exports as PDF/XLSX/PPTX.
        For regular files, downloads directly.
        """

        def _download() -> None:
            service = self._get_drive_service(config)

            meta = service.files().get(fileId=file.id, fields="mimeType").execute()
            original_mime = meta.get("mimeType", "")

            if original_mime in GOOGLE_DOCS_EXPORT:
                export_mime, ext = GOOGLE_DOCS_EXPORT[original_mime]
                request = service.files().export_media(fileId=file.id, mimeType=export_mime)
            else:
                request = service.files().get_media(fileId=file.id)

            with open(dest_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            logger.info(
                "Downloaded %s from Google Drive (%d bytes)", file.id, dest_path.stat().st_size
            )

        await asyncio.to_thread(_download)
