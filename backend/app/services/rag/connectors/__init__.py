"""RAG sync connectors - extensible source adapters for document ingestion."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from app.services.rag.remote_names import destination_within

logger = logging.getLogger(__name__)


class RemoteFile(BaseModel):
    """Metadata for a file from a remote source."""

    id: str
    name: str
    mime_type: str | None = None
    size: int | None = None
    modified_at: datetime | None = None
    source_path: str  # Dedup key: "gdrive://file_id", "s3://bucket/key"


class BaseSyncConnector(ABC):
    """Base class for all sync source connectors.

    To add a new connector:
    1. Create a new class inheriting BaseSyncConnector
    2. Implement list_files() and _fetch()
    3. Define CONFIG_SCHEMA with required/optional fields
    4. Register in CONNECTOR_REGISTRY
    """

    CONNECTOR_TYPE: ClassVar[str] = ""
    DISPLAY_NAME: ClassVar[str] = ""
    CONFIG_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {}

    @abstractmethod
    async def list_files(self, config: dict) -> list[RemoteFile]:
        """List files available for sync from this source."""

    async def download_file(
        self, file: RemoteFile, dest_dir: Path, config: dict | None = None
    ) -> Path:
        """Download one file into `dest_dir` and answer the local path it landed at.

        **Where the file lands is this class's answer, not a connector's.** The
        two shipped connectors used to decide it separately and disagreed: S3
        reduced its key to a single component, Drive wrote `dest_dir /
        file.name` verbatim, and a Drive file named `../../../evil` therefore
        left the temporary directory the worker had made for it. Handing an
        implementation a path rather than a directory is what makes the answer
        inherited instead of remembered - see `destination_within` for the
        refusal itself.
        """
        dest_path = destination_within(dest_dir, file.name)
        await self._fetch(file, dest_path, config or {})
        return dest_path

    @abstractmethod
    async def _fetch(self, file: RemoteFile, dest_path: Path, config: dict) -> None:
        """Write `file`'s bytes to `dest_path`, which is already inside the sync directory."""

    async def validate_config(self, config: dict) -> tuple[bool, str | None]:
        """Validate connector config. Returns (is_valid, error_message)."""
        for field_name, field_spec in self.CONFIG_SCHEMA.items():
            if field_spec.get("required") and not config.get(field_name):
                return False, f"Missing required field: {field_spec.get('label', field_name)}"
        return True, None


# Registry of available connectors - import conditionally to avoid missing deps
CONNECTOR_REGISTRY: dict[str, type[BaseSyncConnector]] = {}
from app.services.rag.connectors.google_drive import GoogleDriveConnector

CONNECTOR_REGISTRY["gdrive"] = GoogleDriveConnector
from app.services.rag.connectors.s3 import S3Connector

CONNECTOR_REGISTRY["s3"] = S3Connector
