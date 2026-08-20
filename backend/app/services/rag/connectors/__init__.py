"""RAG sync connectors - extensible source adapters for document ingestion."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from app.core.secret_kinds import SecretKind, StorableSecret
from app.schemas.sync_source import ConnectorConfigField
from app.services.rag.remote_names import destination_within

logger = logging.getLogger(__name__)


ConnectorConfig = dict[str, Any]
"""How to *find* a source's documents, as the wizard posted it.

`Any` and meant: this is the source's own JSONB column, and what a connector
accepts is described by its `CONFIG_SCHEMA` rather than by a model per
connector - which is what lets the wizard draw a form for a connector it has
never heard of. What is typed is the *shape of a declared field*, in
`ConnectorConfigField`, because that is where a key typo silently disabled a
check (#562). A credential never arrives here (#937).
"""


class RemoteFile(BaseModel):
    """Metadata for a file from a remote source."""

    id: str
    name: str
    mime_type: str | None = None
    size: int | None = None
    modified_at: datetime | None = None
    source_path: str  # Dedup key: "gdrive://file_id", "s3://bucket/key"


class ConfigRefusal(BaseModel):
    """Why a connector will not accept a config, and which of its fields.

    `validate_config` used to answer `tuple[bool, str | None]`, so a refusal
    that knew exactly which field was wrong could not say so: the sentence
    reached the wire and the sync-source wizard, which draws one input per
    `CONFIG_SCHEMA` entry, marked none of them (#897).

    `field` is a key of `CONFIG_SCHEMA`, as the connector names it. Where that
    sits in the document the wizard posted is not a connector's to know:
    `SyncSourceService` roots it and builds the refusal with `refused_field`,
    which is the only thing that decides what reaches the wire. Singular here
    and plural there on purpose - a connector refuses on the first thing it
    finds wrong, and `details["fields"]` is a list because a *pydantic* refusal
    reports every field at once (#891).

    It is optional because a connector is entitled to refuse a config without
    blaming one field of it - connectivity that fails, two credentials that do
    not belong to the same account - and forcing the folder-id case's shape onto
    that would only produce an invented field name.
    """

    message: str
    field: str | None = None


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
    CONFIG_SCHEMA: ClassVar[dict[str, ConnectorConfigField]] = {}
    # Which vault secret authenticates this connector. `CONFIG_SCHEMA` describes
    # how to *find* the documents and holds nothing that has to be kept: the
    # credential arrives separately, unsealed from the organization's vault by
    # whoever is running the sync (#937). A connector that needs none says
    # `SecretKind.NONE` - a public docs crawler, when there is one.
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.NONE

    @abstractmethod
    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        """List files available for sync from this source.

        `credential` is the unsealed vault secret, or `None` when the source has
        no `secret_id` or its secret has been deleted. A connector needing one
        raises rather than reaching for a deployment-wide fallback: there is no
        such thing here, and inventing one would let a source read under the
        operator's identity rather than its own.
        """

    async def download_file(
        self,
        file: RemoteFile,
        dest_dir: Path,
        config: ConnectorConfig | None = None,
        credential: StorableSecret | None = None,
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
        await self._fetch(file, dest_path, config or {}, credential)
        return dest_path

    @abstractmethod
    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Write `file`'s bytes to `dest_path`, which is already inside the sync directory."""

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """Why this config would not be accepted, or `None` if it would.

        The required-field check knows the name of the field it is refusing, so
        it says so: an override that has more to check calls this first and
        returns what it answers, unchanged.
        """
        for field_name, field_spec in self.CONFIG_SCHEMA.items():
            if field_spec.required and not config.get(field_name):
                return ConfigRefusal(
                    message=f"Missing required field: {field_spec.label or field_name}",
                    field=field_name,
                )
        return None


CONNECTOR_REGISTRY: dict[str, type[BaseSyncConnector]] = {}
from app.services.rag.connectors.google_drive import GoogleDriveConnector

CONNECTOR_REGISTRY["gdrive"] = GoogleDriveConnector
from app.services.rag.connectors.s3 import S3Connector

CONNECTOR_REGISTRY["s3"] = S3Connector
