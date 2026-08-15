"""Business logic for a person's named dashboard presets (PostgreSQL async).

Like the active layout, a preset is a personal preference scoped to
`(user_id, organization_id)` — no permission gates any of this, and every
method takes both ids from the authenticated request, so there is no path
that touches anybody else's shelf. What this layer adds over the repository
is the two refusals: a duplicate name (409, so "save as" can say *that name
is taken* rather than silently overwriting a snapshot the person meant to
keep) and the per-person cap (422, so the table stays bounded).

Applying a preset is not a service method on purpose: the client writes the
preset's entries as the active arrangement through
:class:`~app.services.dashboard_layout.DashboardLayoutService`, which keeps a
single write path — and a single validation — for what the dashboard renders.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from app.db.models.dashboard_preset import DashboardPreset
from app.repositories import dashboard_preset_repo
from app.schemas.dashboard_layout import MAX_PRESETS, DashboardPresetCreate


class DashboardPresetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_user(
        self, *, user_id: UUID, organization_id: UUID
    ) -> tuple[list[DashboardPreset], int]:
        presets = await dashboard_preset_repo.list_for_user(
            self.db, user_id=user_id, organization_id=organization_id
        )
        return presets, len(presets)

    async def create(
        self, *, user_id: UUID, organization_id: UUID, data: DashboardPresetCreate
    ) -> DashboardPreset:
        existing = await dashboard_preset_repo.get_by_name(
            self.db, user_id=user_id, organization_id=organization_id, name=data.name
        )
        if existing is not None:
            raise AlreadyExistsError(
                message="A dashboard preset with this name already exists",
                details={"name": data.name},
            )
        count = await dashboard_preset_repo.count_for_user(
            self.db, user_id=user_id, organization_id=organization_id
        )
        if count >= MAX_PRESETS:
            raise ValidationError(
                message="Dashboard preset limit reached — delete one to save another",
                details={"limit": MAX_PRESETS},
            )
        entries = [placement.model_dump() for placement in data.entries]
        try:
            return await dashboard_preset_repo.create(
                self.db,
                user_id=user_id,
                organization_id=organization_id,
                name=data.name,
                entries=entries,
            )
        except IntegrityError as exc:
            # The get-by-name check above is not atomic: two concurrent saves of
            # the same name both pass it, and the `uq_dashboard_preset_user_org_name`
            # constraint refuses the second insert. Translate that into the same
            # 409 the check raises, rather than letting it surface as a 500.
            raise AlreadyExistsError(
                message="A dashboard preset with this name already exists",
                details={"name": data.name},
            ) from exc

    async def delete(self, *, user_id: UUID, organization_id: UUID, preset_id: UUID) -> None:
        """Delete one preset. A preset in another organization answers 404.

        The repository filters on the caller's ids, so a preset that exists but
        belongs to somebody else — or to this person in a different
        organization — is indistinguishable from one that never did.
        """
        preset = await dashboard_preset_repo.get(
            self.db, preset_id=preset_id, user_id=user_id, organization_id=organization_id
        )
        if preset is None:
            raise NotFoundError(
                message="Dashboard preset not found", details={"preset_id": preset_id}
            )
        await dashboard_preset_repo.delete(self.db, db_preset=preset)
