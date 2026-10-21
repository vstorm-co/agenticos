"""Google Drive document source for RAG ingestion.

Fetches files from Google Drive using a service account credentials JSON file.
Supports listing folders, downloading files, and syncing to RAG collections.

Setup:
1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Share the target Drive folder with the service account email
4. Set GOOGLE_DRIVE_CREDENTIALS_FILE to the path of the JSON key file
"""

import logging
from pathlib import Path

from app.core.config import settings
from app.services.rag.drive_api import DriveClient
from app.services.rag.filters import Source
from app.services.rag.remote_names import checked_drive_folder_id, destination_within
from app.services.rag.sources.base import BaseDocumentSource, SourceFile

logger = logging.getLogger(__name__)

GOOGLE_DOCS_EXPORT = {
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


class GoogleDriveSource(BaseDocumentSource):
    """Google Drive document source using service account credentials.

    Authenticates via a service account JSON key file.
    The target folder must be shared with the service account email.
    """

    SOURCE = Source.GDRIVE

    def __init__(self):
        creds_file = settings.GOOGLE_DRIVE_CREDENTIALS_FILE
        if not creds_file or not Path(creds_file).exists():
            raise ValueError(
                f"Google Drive credentials file not found: {creds_file}. "
                "Set GOOGLE_DRIVE_CREDENTIALS_FILE to the path of your service account JSON key."
            )
        self.service = DriveClient.from_service_account_file(creds_file)

    async def list_files(
        self, path: str = "", extensions: list[str] | None = None
    ) -> list[SourceFile]:
        """List files in a Google Drive folder.

        The folder id is checked before it reaches the query. `rag-sync-gdrive
        --folder-id` takes it from the shell, and a value carrying a single
        quote closes the parent literal and appends its own clauses to the
        query.

        Args:
            path: Google Drive folder ID. Empty string = root.
            extensions: Optional list of extensions to filter by.

        Returns:
            List of SourceFile objects.

        Raises:
            BadRequestError: `path` is not a Drive identifier.
        """
        query_parts = ["trashed = false"]
        if path:
            query_parts.append(f"'{checked_drive_folder_id(path)}' in parents")

        query_parts.append("mimeType != 'application/vnd.google-apps.folder'")
        query = " and ".join(query_parts)

        page = self.service.list_page(
            q=query, fields="files(id, name, mimeType, size)", page_size=1000, page_token=None
        )

        files = []
        for f in page.files:
            mime = f.mime_type
            name = f.name

            if mime in GOOGLE_DOCS_EXPORT:
                _, ext = GOOGLE_DOCS_EXPORT[mime]
                name = f"{name}{ext}" if not name.endswith(ext) else name
            else:
                ext = Path(name).suffix.lower()

            if extensions and ext not in extensions:
                continue

            files.append(
                SourceFile(
                    id=f.id,
                    name=name,
                    mime_type=mime,
                    size=f.size,
                    path=f"gdrive://{f.id}",
                )
            )

        return files

    async def download_file(self, file_id: str, dest_dir: Path) -> Path:
        """Download a file from Google Drive.

        For Google Docs formats, exports as PDF/XLSX/PPTX.
        For regular files, downloads directly.

        Args:
            file_id: Google Drive file ID.
            dest_dir: Local directory to save to.

        Returns:
            Path to the downloaded file.

        Raises:
            BadRequestError: the Drive name does not name a file inside `dest_dir`.
        """
        meta = self.service.metadata(file_id, fields="name, mimeType")
        mime = meta.mime_type
        name = meta.name or "download"

        export_mime = None
        if mime in GOOGLE_DOCS_EXPORT:
            export_mime, ext = GOOGLE_DOCS_EXPORT[mime]
            if not name.endswith(ext):
                name = f"{name}{ext}"

        dest_path = destination_within(dest_dir, name)
        if export_mime is None:
            self.service.download(file_id, dest_path)
        else:
            self.service.export(file_id, export_mime, dest_path)

        logger.info("Downloaded %s from Google Drive (%d bytes)", name, dest_path.stat().st_size)
        return dest_path
