"""One model call the platform makes for a person on its own initiative (#2301).

Background work that needs a model - reading somebody's week to notice what they
keep asking for - is not an agent run: it has no tools, no conversation and
nobody watching. It still has to be paid for the way everything else is, so it
gets what a run gets where it matters:

- **The starter agent's model.** The organization chose it for its general
  assistant; the platform thinking for a person on that assistant's behalf uses
  the same one, and an organization without the starter agent gets nothing.
- **A run row**, `surface=proactive`, under the starter agent and the person -
  so the cost is in run history, the spend views and the organization's monthly
  total, and a failure is written down rather than lost.
- **Two limits, checked first.** The organization's monthly cap, and its
  per-person proactivity limit, measured against this person's background runs
  this month. At either, nothing is called.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.usage import UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.failures import run_failure_summary
from app.agents.spec import AgentSpec
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.agent import Agent as AgentRow
from app.db.models.agent_run import RunStatus, RunSurface
from app.repositories import agent_repo, agent_run_repo, organization_repo
from app.services.model_profile import ModelProfileService
from app.services.spend import month_start, organization_monthly_spend

logger = logging.getLogger(__name__)

STARTER_SLUG = "agenticos"
"""The starter agent whose model and whose run history background work goes through.

`facade._STARTER_SLUG` repeats it; `test_proactive` holds the two equal."""

# One request, and a second for the structured output's retry: there are no tools.
_LIMITS = UsageLimits(request_limit=2)


class ProactiveThinker:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def starter_agent(self, organization_id: UUID) -> AgentRow | None:
        """The organization's starter agent, published - or `None`, and then no background work."""
        agent = await agent_repo.get_by_slug(self.db, STARTER_SLUG, organization_id=organization_id)
        return agent if agent is not None and agent.current_version_id is not None else None

    async def within_limits(self, ctx: AuthContext) -> bool:
        """Whether this person's background work may spend this month."""
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None or organization.proactive_limit_usd <= 0 or ctx.user_id is None:
            return False
        if organization.monthly_budget_usd is not None:
            spent = await organization_monthly_spend(self.db, ctx.organization_id)
            if spent >= organization.monthly_budget_usd:
                return False
        mine = await agent_run_repo.proactive_spend_since(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            since=month_start(),
        )
        return mine < organization.proactive_limit_usd

    async def think[OutputT](
        self,
        ctx: AuthContext,
        *,
        output_type: type[OutputT],
        instructions: str,
        prompt: str,
    ) -> OutputT | None:
        """Ask the starter agent's model one structured question, as a run of its own.

        Returns `None` - having spent nothing - without a starter agent or past a
        limit, and `None` with the failure on the run row when the model could
        not answer. Background work has no one to raise to; the next night is the
        retry.
        """
        agent = await self.starter_agent(ctx.organization_id)
        if agent is None or agent.current_version_id is None:
            return None
        if not await self.within_limits(ctx):
            return None
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=ctx.organization_id
        )
        if version is None:
            return None
        spec = AgentSpec.model_validate(version.spec)
        try:
            request = await ModelProfileService(self.db).resolve(
                ctx, profile_id=spec.model_profile_id
            )
        except AppException:
            logger.info(
                "proactive_model_unavailable",
                extra={"organization_id": str(ctx.organization_id), "agent_id": str(agent.id)},
            )
            return None
        run = await agent_run_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            user_id=ctx.user_id,
            conversation_id=None,
            surface=RunSurface.PROACTIVE.value,
            model_label=request.label,
            provider=request.provider,
            secret_id=request.secret_id,
            started_at=datetime.now(UTC),
        )
        try:
            result = await Agent(
                request.build(), output_type=output_type, instructions=instructions
            ).run(prompt, usage_limits=_LIMITS)
        except (AgentRunError, httpx.HTTPError) as exc:
            logger.exception("proactive_run_failed", extra={"run_id": str(run.id)})
            await agent_run_repo.finish_run(
                self.db,
                run=run,
                status=RunStatus.FAILED.value,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal(0),
                cost_is_partial=True,
                ended_at=datetime.now(UTC),
                error=run_failure_summary(exc),
            )
            return None
        usage = result.usage
        cost = price_request(usage, result.response.model_name or request.model, request.provider)
        await agent_run_repo.finish_run(
            self.db,
            run=run,
            status=RunStatus.COMPLETED.value,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost if cost is not None else Decimal(0),
            cost_is_partial=cost is None,
            ended_at=datetime.now(UTC),
        )
        return result.output
