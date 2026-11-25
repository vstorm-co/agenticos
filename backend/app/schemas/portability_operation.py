"""Public transfer state excludes staging paths, credentials and queue internals."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema
from app.schemas.resource_bundle import (
    BundleImportChoice,
    BundleImportRead,
    BundleKey,
    BundlePreview,
    BundleSelection,
)

type TransferStatus = Literal[
    "awaiting_upload", "queued", "running", "review", "needs_bindings", "ready", "failed", "expired"
]
type TransferDirection = Literal["export", "import"]


class BundleExportStart(BundleSelection):
    request_id: UUID
    root_kind: Literal["agent", "workflow"]
    root_id: UUID


class BundleUploadStart(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=512 * 1024 * 1024, strict=True)


class BundleApplyCreate(BaseSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    expected_revision: int = Field(ge=1, strict=True)
    choices: dict[BundleKey, BundleImportChoice] = Field(max_length=10_000)


class BundleVersionRequirement(BaseSchema):
    resource: BundleKey
    owner: BundleKey
    owner_id: UUID
    name: str


class PortabilityOperationRead(BaseSchema):
    id: UUID
    request_id: UUID
    direction: TransferDirection
    phase: Literal["prepare", "apply"]
    status: TransferStatus
    revision: int
    completed_bytes: int
    total_bytes: int
    expires_at: datetime
    error_code: str | None = None
    preview: BundlePreview | None = None
    receipt: BundleImportRead | None = None
    required_versions: tuple[BundleVersionRequirement, ...] = ()
    can_download: bool = False
