"""Minerp IAM tenant ↔ Agentra organization (platform integration)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class MinerpTenantContextRead(BaseSchema):
    organization_id: UUID
    minerp_tenant_id: UUID
    organization_name: str
    organization_slug: str
    is_personal: bool = False
