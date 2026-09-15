"""Announcement repository (PostgreSQL async) (#1598)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.announcement import Announcement


async def create(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    body: str,
    audience_spec: dict[str, Any],
    audience_description: str,
) -> Announcement:
    announcement = Announcement(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        body=body,
        audience_spec=audience_spec,
        audience_description=audience_description,
    )
    db.add(announcement)
    await db.flush()
    return announcement
