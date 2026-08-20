"""Sync source configuration schemas."""

from typing import Any
from uuid import UUID

from app.schemas.base import BaseSchema


class ConnectorConfigField(BaseSchema):
    """Describes a single configuration field for a connector.

    No `secret` flag any more. A connector's configuration says how to *find*
    the documents; the credential is a vault secret the source references by id,
    so there is no field here for a form to mask, encrypt or round-trip as
    `••••••` (#937).
    """

    type: str
    required: bool = False
    label: str = ""
    help: str | None = None
    default: Any = None


class ConnectorInfo(BaseSchema):
    """Metadata about an available connector type.

    `secret_kind` is what a credential for this connector has to be, so the
    wizard can offer the organization's matching vault secrets and nothing else -
    a Drive source takes a service account, an S3 one an AWS key pair.
    """

    type: str
    name: str
    config_schema: dict[str, ConnectorConfigField]
    secret_kind: str
    enabled: bool


class SyncSourceCreate(BaseSchema):
    """Schema for creating a new sync source.

    `collection_name` is optional - a source without it is an org-level
    integration not yet assigned to a knowledge base.

    `secret_id` names the vault secret the connector authenticates with. It is
    optional here and not in the column for one reason: a source can be created
    before its credential exists, and a sync then refuses rather than running on
    nothing. What it may *not* carry is the credential itself - see
    `SyncSourceService.create_source`, which refuses a config holding one (#937).
    """

    name: str
    connector_type: str
    collection_name: str | None = None
    config: dict[str, object]
    secret_id: UUID | None = None
    sync_mode: str = "new_only"
    schedule_minutes: int | None = None


class SyncSourceClone(BaseSchema):
    """Schema for cloning a sync source into a different knowledge base."""

    collection_name: str
    name: str | None = None


class SyncSourceUpdate(BaseSchema):
    """Schema for updating an existing sync source."""

    name: str | None = None
    config: dict[str, object] | None = None
    secret_id: UUID | None = None
    sync_mode: str | None = None
    schedule_minutes: int | None = None
    is_active: bool | None = None
    collection_name: str | None = None


class SyncSourceRead(BaseSchema):
    """Schema for reading a sync source.

    `config` is returned as stored, unmasked, because there is nothing in it to
    mask: the credential is `secret_id`, and what that points at never leaves the
    vault. `secret_hint` is the four characters the vault records so a reader can
    tell *which* credential without being shown it.
    """

    id: str
    organization_id: str
    name: str
    connector_type: str
    collection_name: str | None
    config: dict[str, object]
    secret_id: str | None
    secret_hint: str | None = None
    sync_mode: str
    schedule_minutes: int | None
    is_active: bool
    last_sync_at: str | None
    last_sync_status: str | None
    last_error: str | None
    created_at: str | None


class SyncSourceList(BaseSchema):
    """Paginated list of sync sources."""

    items: list[SyncSourceRead]
    total: int


class ConnectorList(BaseSchema):
    """List of available connectors."""

    items: list[ConnectorInfo]
