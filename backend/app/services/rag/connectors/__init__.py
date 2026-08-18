"""RAG sync connectors - extensible source adapters for document ingestion."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.core.field_errors import field_details
from app.services.rag.remote_names import destination_within

logger = logging.getLogger(__name__)

CONFIG_ROOT = "config"


class RemoteFile(BaseModel):
    """Metadata for a file from a remote source."""

    id: str
    name: str
    mime_type: str | None = None
    size: int | None = None
    modified_at: datetime | None = None
    source_path: str  # Dedup key: "gdrive://file_id", "s3://bucket/key"


class ConfigRefusal(BaseModel):
    """Why a connector will not accept a config, in a shape the wizard can act on.

    `validate_config` used to answer `tuple[bool, str | None]`, so a refusal
    that knew exactly which field was wrong could not say so: the sentence
    reached the wire and the sync-source wizard, which draws one input per
    `CONFIG_SCHEMA` entry, marked none of them (#897).

    `fields` is optional because a connector is entitled to refuse a config
    without blaming one field of it - connectivity that fails, two credentials
    that do not go together - and forcing the folder-id case's shape onto that
    would only produce an invented field name.
    """

    message: str
    fields: list[dict[str, str]] = Field(default_factory=list)

    @classmethod
    def about(cls, field: str, message: str) -> "ConfigRefusal":
        """A refusal of one named field of the config, said once."""
        return cls(message=message, fields=field_details(field, message, root=CONFIG_ROOT))


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

    async def validate_config(self, config: dict) -> ConfigRefusal | None:
        """Why this config would not be accepted, or `None` if it would.

        The required-field check knows the name of the field it is refusing, so
        it says so: an override that has more to check calls this first and
        returns what it answers, unchanged.
        """
        for field_name, field_spec in self.CONFIG_SCHEMA.items():
            if field_spec.get("required") and not config.get(field_name):
                label = field_spec.get("label", field_name)
                return ConfigRefusal.about(field_name, f"Missing required field: {label}")
        return None


CONNECTOR_REGISTRY: dict[str, type[BaseSyncConnector]] = {}
from app.services.rag.connectors.google_drive import GoogleDriveConnector

CONNECTOR_REGISTRY["gdrive"] = GoogleDriveConnector
from app.services.rag.connectors.s3 import S3Connector

CONNECTOR_REGISTRY["s3"] = S3Connector
