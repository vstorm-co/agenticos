"""Catalog sync schemas (Shop A P4-T3 — Studio parity)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopCatalogSyncStatusRead(BaseSchema):
    enabled: bool = False
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_item_count: int = 0
    last_error: str | None = None
    catalog_kb_id: UUID | None = None


class ShopCatalogSyncSettingsPatch(BaseSchema):
    enabled: bool


class ShopCatalogSyncRunOut(BaseSchema):
    status: str
    indexed: int = 0
    skipped: int = 0
    tombstoned: int = 0
    message: str = ""
    errors: list[str] = Field(default_factory=list)


class ShopCatalogSyncItemOut(BaseSchema):
    status: str
    item_id: UUID
    action: str
    message: str = ""


class ShopCatalogSyncItemQueued(BaseSchema):
    status: str = "queued"
    item_id: UUID
    action: str = "auto"
