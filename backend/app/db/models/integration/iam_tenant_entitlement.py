"""CDC replica from auth `tenant_service_entitlements` (D3 B73). READ ONLY."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantServiceEntitlement(Base):
    """IAM tenant service entitlement replica — join by minerp tenant_id UUID."""

    __tablename__ = "tenant_service_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "service_code",
            name="uq_tenant_service_entitlements_tenant_service",
        ),
        {"comment": "CDC replica from auth (shop_ai SKU gate)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    service_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<TenantServiceEntitlement(tenant_id={self.tenant_id}, "
            f"service_code={self.service_code!r})>"
        )
