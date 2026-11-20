"""Organization opt-out and the acting member's per-agent learning choice both win."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingState,
    browser_procedure_teaching_stale_revision,
)
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.browser_procedure_teaching import (
    BrowserProcedureTeachingPolicy,
    BrowserProcedureTeachingPreference,
)
from app.repositories import agent as agent_repo
from app.repositories import browser_procedure_teaching as repo
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingPolicyRead,
    BrowserProcedureTeachingPolicyWrite,
    BrowserProcedureTeachingPreferenceRead,
    BrowserProcedureTeachingPreferenceWrite,
)
from app.services.access import AGENT, resolve_access

from . import _access
from ._service import erase, pause


async def cancel_pending(
    db: AsyncSession,
    organization_id: UUID,
    *,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    refinements_only: bool = False,
) -> None:
    rows = await repo.cancellation_candidates(
        db, organization_id, user_id=user_id, agent_id=agent_id, refinements_only=refinements_only
    )
    for row in rows:
        if row.source == "refinement":
            erase(
                row,
                BrowserProcedureTeachingState.DISCARDED,
                BrowserProcedureTeachingReason.OPTED_OUT,
            )
        else:
            pause(row, BrowserProcedureTeachingReason.DISABLED)
            if row.generation_state in {
                BrowserProcedureTeachingGeneration.QUEUED,
                BrowserProcedureTeachingGeneration.GENERATING,
            }:
                row.generation_state = BrowserProcedureTeachingGeneration.CANCELLED.value
                row.reason_code = BrowserProcedureTeachingReason.DISABLED.value
                row.revision += 1
    await db.flush()


class BrowserProcedureTeachingPolicyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, ctx: AuthContext) -> BrowserProcedureTeachingPolicyRead:
        current = await _access.person(self.db, ctx)
        row = await repo.policy(self.db, current.organization_id)
        return BrowserProcedureTeachingPolicyRead(
            enabled=False if row is None else row.enabled,
            generation=None if row is None else row.generation,
            deployment_enabled=_access.deployment_enabled(current.organization_id),
        )

    async def update(
        self, ctx: AuthContext, data: BrowserProcedureTeachingPolicyWrite
    ) -> BrowserProcedureTeachingPolicyRead:
        current = await _access.person(self.db, ctx)
        if not current.has(Perm.ORG_SETTINGS):
            raise AuthorizationError(
                message="Changing browser teaching policy requires org:settings"
            )
        await repo.lock_organization(self.db, current.organization_id)
        current = await _access.person(self.db, current)
        if not current.has(Perm.ORG_SETTINGS):
            raise AuthorizationError(
                message="Changing browser teaching policy requires org:settings"
            )
        row = await repo.policy(self.db, current.organization_id, locked=True)
        if (None if row is None else row.generation) != data.generation:
            raise browser_procedure_teaching_stale_revision()
        if row is not None and row.enabled == data.enabled:
            return await self.get(current)
        if row is None:
            row = BrowserProcedureTeachingPolicy(
                organization_id=current.organization_id, enabled=data.enabled, generation=uuid4()
            )
            self.db.add(row)
        else:
            row.enabled, row.generation = data.enabled, uuid4()
        if not data.enabled:
            await cancel_pending(self.db, current.organization_id)
        await self.db.flush()
        await record_audit(
            self.db,
            organization_id=current.organization_id,
            actor_user_id=current.user_id,
            action="browser_procedure_teaching.policy_changed",
            target_type="organization",
            target_id=str(current.organization_id),
            details={"enabled": data.enabled, "generation": str(row.generation)},
        )
        return await self.get(current)

    async def _agent(self, ctx: AuthContext, agent_id: UUID) -> bool:
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is not None:
            await self.db.refresh(agent)
        if (
            agent is None
            or agent.status == "archived"
            or not await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT)
        ):
            raise NotFoundError(message="Agent not found")
        if agent.current_version_id is None:
            return False
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=ctx.organization_id
        )
        if version is None or version.agent_id != agent.id:
            return False
        try:
            capture, learning = _access._configuration(version.spec)
        except BrowserProcedureTeachingRefused:
            return False
        return capture and learning

    async def _capable(self, ctx: AuthContext, agent_id: UUID, *, known: bool) -> bool:
        try:
            return await self._agent(ctx, agent_id)
        except NotFoundError:
            if not known:
                raise
            # A person may revoke a recorded choice after losing the agent grant.
            # No inaccessible agent metadata is exposed by this value-free choice.
            return False

    async def preference(
        self, ctx: AuthContext, agent_id: UUID
    ) -> BrowserProcedureTeachingPreferenceRead:
        current = await _access.person(self.db, ctx)
        assert current.user_id is not None
        row = await repo.preference(self.db, current.organization_id, current.user_id, agent_id)
        capable = await self._capable(current, agent_id, known=row is not None)
        policy = await repo.policy(self.db, current.organization_id)
        return BrowserProcedureTeachingPreferenceRead(
            agent_id=agent_id,
            enabled=False if row is None else row.enabled,
            generation=None if row is None else row.generation,
            allowed=capable
            and _access.deployment_enabled(current.organization_id)
            and policy is not None
            and policy.enabled,
        )

    async def update_preference(
        self, ctx: AuthContext, agent_id: UUID, data: BrowserProcedureTeachingPreferenceWrite
    ) -> BrowserProcedureTeachingPreferenceRead:
        current = await _access.person(self.db, ctx)
        assert current.user_id is not None
        await repo.lock_organization(self.db, current.organization_id)
        current = await _access.person(self.db, current)
        assert current.user_id is not None
        row = await repo.preference(
            self.db, current.organization_id, current.user_id, agent_id, locked=True
        )
        capable = await self._capable(current, agent_id, known=row is not None and not data.enabled)
        if data.enabled:
            await _access.enabled(self.db, current.organization_id)
            if not capable:
                raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.UNAVAILABLE)
        if (None if row is None else row.generation) != data.generation:
            raise browser_procedure_teaching_stale_revision()
        if row is not None and row.enabled == data.enabled:
            return await self.preference(current, agent_id)
        if row is None:
            row = BrowserProcedureTeachingPreference(
                organization_id=current.organization_id,
                user_id=current.user_id,
                agent_id=agent_id,
                enabled=data.enabled,
                generation=uuid4(),
            )
            self.db.add(row)
        else:
            row.enabled, row.generation = data.enabled, uuid4()
        if not data.enabled:
            await cancel_pending(
                self.db,
                current.organization_id,
                user_id=current.user_id,
                agent_id=agent_id,
                refinements_only=True,
            )
        await self.db.flush()
        await record_audit(
            self.db,
            organization_id=current.organization_id,
            actor_user_id=current.user_id,
            action="browser_procedure_teaching.preference_changed",
            target_type="agent",
            target_id=str(agent_id),
            details={"enabled": data.enabled, "generation": str(row.generation)},
        )
        return await self.preference(current, agent_id)
