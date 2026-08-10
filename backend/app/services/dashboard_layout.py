"""Business logic for a person's saved dashboard arrangement (PostgreSQL async).

There is no authorization here beyond the caller being the row's owner: a
layout is a personal preference, scoped to `(user_id, organization_id)`, not
organization data. Every method takes both ids from the request's authenticated
user and active organization, so there is no path that reads or writes anybody
else's — the tenant boundary is the composite key, enforced in the repository.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dashboard_layout import DashboardLayout
from app.repositories import dashboard_layout_repo
from app.schemas.dashboard_layout import DashboardLayoutUpdate


class DashboardLayoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(self, *, user_id: UUID, organization_id: UUID) -> DashboardLayout | None:
        """The caller's saved layout, or `None` when they have not saved one.

        `None` is not an error: it is the signal to fall back to the audience
        default, which the route turns into a 404 the frontend reads as "use the
        default" rather than as a failure.
        """
        return await dashboard_layout_repo.get(
            self.db, user_id=user_id, organization_id=organization_id
        )

    async def save(
        self, *, user_id: UUID, organization_id: UUID, data: DashboardLayoutUpdate
    ) -> DashboardLayout:
        entries = [placement.model_dump() for placement in data.entries]
        return await dashboard_layout_repo.upsert(
            self.db, user_id=user_id, organization_id=organization_id, entries=entries
        )

    async def reset(self, *, user_id: UUID, organization_id: UUID) -> None:
        """Discard the saved layout, returning the caller to the audience default.

        Idempotent: resetting when nothing is saved is the end state already, so
        it succeeds silently rather than reporting a missing row the caller does
        not care about.
        """
        existing = await dashboard_layout_repo.get(
            self.db, user_id=user_id, organization_id=organization_id
        )
        if existing is not None:
            await dashboard_layout_repo.delete(self.db, db_layout=existing)
