"""System agents: what the platform's own background work runs on, and what it has spent (#2575).

A system role is platform-owned work that needs a model. Its configuration is a
profile - a switch, a model and a monthly budget - and its history is the runs
recorded under it, attributed to the role rather than to the starter agent whose
instructions never ran.

There are two roles, and they are configured differently on purpose. **Memory
maintenance** has a profile of its own, stored here. **The daily briefing** is the
organization's proactivity setting: it is shown here with its history, and edited
where it already lives, so there is one model and one limit for it. Neither is ever
a row in the agent list and neither can be deleted - a role is disabled, not
removed.
"""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.db.models.system_agent_profile import DAILY_BRIEFING, MEMORY_MAINTENANCE
from app.repositories import (
    agent_run_repo,
    credential_repo,
    organization_repo,
    system_agent_repo,
)
from app.schemas.system_agent import (
    SystemAgentList,
    SystemAgentRead,
    SystemAgentRunRead,
    SystemAgentUpdate,
)
from app.services.model_outputs import model_outputs, not_chat_refusal
from app.services.proactive._thinker import ProactiveThinker
from app.services.spend import month_start

HISTORY = 10
"""How many recent executions a role's card lists."""


def _run(row: AgentRun) -> SystemAgentRunRead:
    assert row.started_at is not None, "a run row is written with its start"
    return SystemAgentRunRead(
        id=row.id,
        started_at=row.started_at,
        status=row.status,
        model_label=row.model_label,
        cost_usd=row.cost_usd or Decimal(0),
        error=row.error,
    )


class SystemAgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(self, ctx: AuthContext) -> SystemAgentList:
        """Both roles with their configuration, this month's spend and recent executions."""
        briefing = await self._briefing(ctx)
        maintenance = await self._maintenance(ctx)
        return SystemAgentList(items=[briefing, maintenance])

    async def update(self, ctx: AuthContext, role: str, data: SystemAgentUpdate) -> SystemAgentRead:
        """Replace memory maintenance's switch, model and budget.

        Refused for a model that is not this organization's or cannot chat, and for
        switching it on with no model chosen: the role spends money nobody asked
        for in the moment, so it never runs on a default.

        Raises:
            NotFoundError: `role` is not one with a profile of its own. The daily
                briefing is edited in the organization's proactivity setting.
        """
        if role != MEMORY_MAINTENANCE:
            raise NotFoundError(message="System agent not found", details={"role": role})
        if data.model_profile_id is not None:
            await self._check_model(ctx, data.model_profile_id)
        if data.enabled and data.model_profile_id is None:
            raise refused_field(
                "model_profile_id", "Choose the model this role runs on before turning it on"
            )
        profile = await system_agent_repo.provision(
            self.db, organization_id=ctx.organization_id, role=role
        )
        await system_agent_repo.update(
            self.db,
            profile,
            enabled=data.enabled,
            model_profile_id=data.model_profile_id,
            monthly_budget_usd=data.monthly_budget_usd,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="system_agent.updated",
            target_type="system_agent",
            target_id=role,
            details={
                "enabled": data.enabled,
                "model_profile_id": str(data.model_profile_id) if data.model_profile_id else None,
                "monthly_budget_usd": (
                    str(data.monthly_budget_usd) if data.monthly_budget_usd is not None else None
                ),
            },
        )
        return await self._maintenance(ctx)

    async def _check_model(self, ctx: AuthContext, profile_id: UUID) -> None:
        profile = await credential_repo.get_profile(
            self.db, profile_id, organization_id=ctx.organization_id
        )
        if profile is None:
            raise refused_field("model_profile_id", "That model is not one of this organization's")
        outputs = model_outputs(profile.provider, profile.model, base_url=profile.base_url)
        if not outputs.chat:
            raise refused_field(
                "model_profile_id", not_chat_refusal(profile.label, profile.model, outputs)
            )

    async def _unavailable(self, ctx: AuthContext) -> Literal["starter_agent"] | None:
        starter = await ProactiveThinker(self.db).starter_agent(ctx.organization_id)
        return None if starter is not None else "starter_agent"

    async def _label(self, ctx: AuthContext, profile_id: UUID | None) -> str | None:
        if profile_id is None:
            return None
        profile = await credential_repo.get_profile(
            self.db, profile_id, organization_id=ctx.organization_id
        )
        return None if profile is None else profile.label

    async def _spent(self, ctx: AuthContext, role: str) -> Decimal:
        return await agent_run_repo.role_spend_since(
            self.db, organization_id=ctx.organization_id, role=role, since=month_start()
        )

    async def _runs(self, ctx: AuthContext, role: str) -> list[SystemAgentRunRead]:
        rows = await agent_run_repo.recent_role_runs(
            self.db, organization_id=ctx.organization_id, role=role, limit=HISTORY
        )
        return [_run(row) for row in rows]

    async def _maintenance(self, ctx: AuthContext) -> SystemAgentRead:
        profile = await system_agent_repo.provision(
            self.db, organization_id=ctx.organization_id, role=MEMORY_MAINTENANCE
        )
        return SystemAgentRead(
            role=MEMORY_MAINTENANCE,
            unavailable=await self._unavailable(ctx),
            enabled=profile.enabled,
            model_profile_id=profile.model_profile_id,
            model_label=await self._label(ctx, profile.model_profile_id),
            monthly_budget_usd=profile.monthly_budget_usd,
            spent_this_month=await self._spent(ctx, MEMORY_MAINTENANCE),
            runs=await self._runs(ctx, MEMORY_MAINTENANCE),
        )

    async def _briefing(self, ctx: AuthContext) -> SystemAgentRead:
        organization: Any = await organization_repo.get_by_id(self.db, ctx.organization_id)
        profile_id = organization.proactive_model_profile_id
        return SystemAgentRead(
            role=DAILY_BRIEFING,
            unavailable=await self._unavailable(ctx),
            enabled=organization.proactive_enabled,
            model_profile_id=profile_id,
            model_label=await self._label(ctx, profile_id),
            monthly_budget_usd=None,
            spent_this_month=await self._spent(ctx, DAILY_BRIEFING),
            managed_in="proactivity",
            runs=await self._runs(ctx, DAILY_BRIEFING),
        )
