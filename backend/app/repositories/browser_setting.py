"""Data access for an organization's browser setting."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.browser_setting import BrowserSetting


async def get(db: AsyncSession, *, organization_id: UUID) -> BrowserSetting | None:
    """The organization's setting, or `None` while it has the default."""
    return await db.get(BrowserSetting, organization_id)


async def save(
    db: AsyncSession, *, organization_id: UUID, values: dict[str, Any]
) -> BrowserSetting:
    """Write the organization's setting, creating its row the first time."""
    row = await db.get(BrowserSetting, organization_id)
    if row is None:
        row = BrowserSetting(organization_id=organization_id, **values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    await db.flush()
    await db.refresh(row)
    return row
