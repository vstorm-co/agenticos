"""Business logic for a person's pinned sidebar items.

Pins are a personal preference, not organization data: there is no permission
check beyond the caller owning the row. Both ids come from the request's
signed-in user and active organization. Pins never grant access; the client
filters them through its own permission-aware navigation.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import nav_pins_repo
from app.schemas.nav_pins import NavPinsUpdate


class NavPinsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(self, *, user_id: UUID, organization_id: UUID) -> list[str]:
        row = await nav_pins_repo.get(self.db, user_id=user_id, organization_id=organization_id)
        return list(row.item_ids) if row is not None else []

    async def replace(
        self, *, user_id: UUID, organization_id: UUID, data: NavPinsUpdate
    ) -> list[str]:
        row = await nav_pins_repo.upsert(
            self.db, user_id=user_id, organization_id=organization_id, item_ids=data.item_ids
        )
        return list(row.item_ids)
