"""Reading a retention policy, changing one, and the sweep that applies it.

The policy itself is arithmetic and lives in `app/core/retention.py`; what is
here is everything that touches the database. Three jobs:

- **Read** the three answers a settings page needs - what this organization
  asked for, what it actually gets, and what the deployment allows - because a
  page showing only the last cannot explain why the number it displays is not the
  number somebody typed.
- **Change** what an organization asked for, refusing a period the deployment's
  audit floor forbids and recording the change in the trail.
- **Sweep**, per organization and per class, in batches, hard-deleting. A policy
  that keeps the rows is not a policy.

**What the sweep records, and what it must never record.** One audit entry per
organization per sweep, naming the class and the count. Not a title, not an
address, not a file name: an audit trail that quoted what it deleted would keep
the content past the retention that removed it, which is the failure the whole
feature exists to avoid.

**Failure is per class, not per sweep.** A vector store that is down must not
stop conversations being purged, so each class is attempted, its error logged and
named in the entry, and the sweep goes on. An operator reads which class failed;
the next pass retries it, because a batch that removed nothing simply comes round
again.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError
from app.core.field_errors import refused_field
from app.core.permissions import Perm, role_has
from app.core.retention import (
    AUDIT,
    DEFAULT_AUDIT_FLOOR_DAYS,
    RETENTION_CLASSES,
    RetentionClass,
    effective_policy,
    known_periods,
    policy_conflicts,
)
from app.repositories import deployment_settings_repo, retention_repo
from app.schemas.retention import RetentionRead, RetentionUpdate

if TYPE_CHECKING:
    from app.db.models.organization import Organization

logger = logging.getLogger(__name__)

BATCH = 500
"""Rows per statement. An organization arriving at a ninety-day policy after two
years has two years to remove, and one statement deleting a million rows holds a
lock for the length of it."""

MAX_BATCHES = 40
"""Passes per class per sweep - twenty thousand rows, then the next class gets a
turn. A backlog is worked off over several sweeps rather than in one that runs
for an hour and blocks every other periodic flow behind it."""


@dataclass
class SweepResult:
    """What one organization's sweep removed, and what it could not."""

    organization_id: UUID
    removed: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.removed.values())


#: Removing one document's vectors from the store that holds them.
#:
#: `Awaitable[object]` rather than `Awaitable[None]`: `remove_document` answers
#: whether it found anything, and a sweep does not care - what it needs is that
#: the call was made and did not raise.
#:
#: Injected rather than built here, because a vector store rides an engine of its
#: own and the layer that owns that is the worker (`_ingestion_service`, and the
#: `max_connections` exhaustion in #948 that put it there). A sweep constructed
#: without one cannot purge documents and says so, which is better than a class
#: that silently does nothing on every surface but the flow.
VectorRemover = Callable[[str, str], Awaitable[object]]


class RetentionService:
    """The organization's retention policy, and the sweep that applies it."""

    def __init__(self, db: AsyncSession, *, remove_vectors: VectorRemover | None = None) -> None:
        self.db = db
        self.remove_vectors = remove_vectors

    async def read(self, organization_id: UUID, *, requester_id: UUID) -> RetentionRead:
        """The requested, effective and allowed periods for one organization.

        Gated on `org:settings` like the rest of the organization's settings, and
        gated for *reading* as much as for writing: how long this tenant keeps
        what its people said is a statement about the tenant, not a fact every
        member needs.
        """
        organization = await self._settings_access(organization_id, requester_id)
        return await self._read_for(organization)

    async def update(
        self, organization_id: UUID, data: RetentionUpdate, *, actor_user_id: UUID
    ) -> RetentionRead:
        """Set what this organization asks to keep, within what the deployment allows.

        A class left out of the request is left alone rather than cleared: a page
        that sends one row must not silently reset the other five.

        Raises:
            BadRequestError: An audit period below the deployment's floor. Refused
                rather than raised to the floor, because a trail an administrator
                can shorten is not a trail - and silently keeping entries longer
                than the number on the screen is its own kind of wrong.
        """
        organization = await self._settings_access(organization_id, actor_user_id)
        floor = await self._audit_floor()
        asked = data.retention_days.get(AUDIT)
        if asked is not None and asked < floor:
            raise refused_field(
                "audit",
                f"Audit entries are kept at least {floor} days on this deployment",
            )

        merged: dict[str, int | None] = {
            **known_periods(organization.retention_days),
            **data.retention_days,
        }
        await retention_repo.set_retention(
            self.db, organization=organization, retention_days=merged
        )
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            action="retention.updated",
            target_type="organization",
            target_id=str(organization_id),
            # The periods, which are the policy. Nothing about what they apply to.
            details={"retention_days": merged},
        )
        return await self._read_for(organization)

    async def sweep(self, *, now: datetime | None = None) -> list[SweepResult]:
        """Apply every organization's policy once, class by class.

        Args:
            now: The moment the cutoffs are measured back from. A parameter so a
                test can freeze it; the flow passes none.

        Returns:
            One result per organization that removed something or failed
            something. An organization with nothing to do is left out, because a
            log line per tenant per day saying "nothing" is a log nobody reads.
        """
        moment = now or datetime.now(UTC)
        settings_row = await deployment_settings_repo.get(self.db)
        defaults = getattr(settings_row, "retention_defaults", None)
        ceilings = getattr(settings_row, "retention_max_days", None)
        floor = getattr(settings_row, "audit_retention_floor_days", None)

        results: list[SweepResult] = []
        for organization_id, requested in await retention_repo.organizations_with_retention(
            self.db
        ):
            policy = effective_policy(
                organization=requested,
                defaults=defaults,
                ceilings=ceilings,
                audit_floor_days=floor,
            )
            result = await self._sweep_one(organization_id, policy, moment)
            if result.total or result.failed:
                await self._record_sweep(result)
                results.append(result)
        return results

    async def _sweep_one(
        self, organization_id: UUID, policy: dict[RetentionClass, int | None], moment: datetime
    ) -> SweepResult:
        result = SweepResult(organization_id=organization_id)
        for name in RETENTION_CLASSES:
            days = policy[name]
            if days is None:
                continue
            cutoff = moment - timedelta(days=days)
            try:
                removed = await self._purge(name, organization_id=organization_id, cutoff=cutoff)
            except Exception:
                # Named, not raised: a vector store that is down must not stop
                # conversations being purged, and the next pass retries this
                # class because a batch that removed nothing comes round again.
                logger.exception(
                    "retention_class_failed",
                    extra={"organization_id": str(organization_id), "retention_class": name},
                )
                result.failed.append(name)
                continue
            if removed:
                result.removed[name] = removed
        return result

    async def _purge(self, name: RetentionClass, *, organization_id: UUID, cutoff: datetime) -> int:
        """One class, in batches, until a pass removes nothing or the cap is reached."""
        removed = 0
        for _ in range(MAX_BATCHES):
            took = await self._purge_batch(name, organization_id=organization_id, cutoff=cutoff)
            removed += took
            if took < BATCH:
                break
        return removed

    async def _purge_batch(
        self, name: RetentionClass, *, organization_id: UUID, cutoff: datetime
    ) -> int:
        scope = {"organization_id": organization_id, "cutoff": cutoff, "limit": BATCH}
        if name == "conversations":
            paths = await retention_repo.stored_paths_for_expiring_conversations(self.db, **scope)
            took = await retention_repo.delete_conversations(self.db, **scope)
            if paths:
                from app.services.file_storage import delete_files_best_effort

                await delete_files_best_effort(paths)
            return took
        if name == "runs":
            # The spend is read and kept *before* the rows go, or the month's
            # figure it belongs to would fall to zero with them.
            for period, cost, count in await retention_repo.expiring_run_spend(self.db, **scope):
                await retention_repo.record_purged_spend(
                    self.db,
                    organization_id=organization_id,
                    period_start=period,
                    cost=cost,
                    runs=count,
                )
            return await retention_repo.delete_runs(self.db, **scope)
        if name == "workspaces":
            return await retention_repo.delete_workspaces(self.db, **scope)
        if name == "memory":
            return await retention_repo.delete_memory(self.db, **scope)
        if name == "knowledge_documents":
            return await self._purge_documents(organization_id=organization_id, cutoff=cutoff)
        return await retention_repo.delete_audit_entries(self.db, **scope)

    async def _purge_documents(self, *, organization_id: UUID, cutoff: datetime) -> int:
        """Uploaded documents, their vectors and their files - in that order.

        The vectors first and the row last, so a failure removing them leaves a
        row that still points at what is there. The other order leaves content
        searchable with nothing left to find it by, which is #992's shape.

        Raises:
            RuntimeError: No vector remover was injected. The class is then
                reported as failed for this organization rather than counted as
                swept, because a document whose row is gone and whose vectors are
                not is exactly the state #992 describes.
        """
        expiring = await retention_repo.expiring_documents(
            self.db, organization_id=organization_id, cutoff=cutoff, limit=BATCH
        )
        if not expiring:
            return 0
        if self.remove_vectors is None:
            raise RuntimeError("retention sweep has no vector remover; cannot purge documents")

        from app.services.file_storage import delete_files_best_effort

        for _, collection, vector_document_id, _ in expiring:
            if vector_document_id:
                await self.remove_vectors(collection, vector_document_id)
        paths = [path for *_, path in expiring if path]
        if paths:
            await delete_files_best_effort(paths)
        return await retention_repo.delete_documents(
            self.db, document_ids=[row[0] for row in expiring]
        )

    async def _record_sweep(self, result: SweepResult) -> None:
        """One entry per organization per sweep: classes and counts, no content."""
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=result.organization_id,
            action="retention.swept",
            target_type="organization",
            target_id=str(result.organization_id),
            details={"removed": result.removed, "failed": sorted(result.failed)},
        )

    async def _read_for(self, organization: Organization) -> RetentionRead:
        settings_row = await deployment_settings_repo.get(self.db)
        defaults = getattr(settings_row, "retention_defaults", None)
        ceilings = getattr(settings_row, "retention_max_days", None)
        floor = getattr(settings_row, "audit_retention_floor_days", None)
        return RetentionRead(
            requested=known_periods(organization.retention_days),
            effective=effective_policy(
                organization=organization.retention_days,
                defaults=defaults,
                ceilings=ceilings,
                audit_floor_days=floor,
            ),
            ceilings=known_periods(ceilings),
            audit_floor_days=floor if floor is not None else DEFAULT_AUDIT_FLOOR_DAYS,
            conflicts=policy_conflicts(ceilings=ceilings, audit_floor_days=floor),
        )

    async def _audit_floor(self) -> int:
        settings_row = await deployment_settings_repo.get(self.db)
        floor = getattr(settings_row, "audit_retention_floor_days", None)
        return floor if floor is not None else DEFAULT_AUDIT_FLOOR_DAYS

    async def _settings_access(self, organization_id: UUID, requester_id: UUID) -> Organization:
        """The organization, if this member may see and set its settings.

        `get_for_user` answers membership and non-existence together, which is
        what keeps a non-member from learning that an organization exists by the
        shape of the refusal.
        """
        from app.services.organization import OrganizationService

        organization, membership = await OrganizationService(self.db).get_for_user(
            organization_id, requester_id
        )
        if not role_has(membership.role, Perm.ORG_SETTINGS):
            raise AuthorizationError(message="Only Owner or Admin can read or change retention")
        return organization
