"""Eval suites: an agent held to a dataset, run on schedule and on the changes that matter.

A suite is the standing version of an eval run somebody would otherwise have to
remember to start. It names the agent, the dataset, the environment whose
version is checked and the threshold a result must meet, and it runs:

- on a cron schedule kept in its owner's time zone - the production version
  checked daily catches a provider's model drifting and a knowledge base
  changing underneath it;
- when a version is published, measured against the one before it;
- when a version is promoted onto its environment, against the one it replaced;
- when a skill or knowledge base the checked version binds changes, once per
  burst of changes;
- when somebody presses "Run now".

Every trigger writes a `pending` result in the same transaction as whatever made
the suite due, so nothing is lost to a restart between the change and the run.
The worker's sweep (:mod:`app.worker.tasks.eval_suite_tasks`) starts each one as
an ordinary eval run through :class:`EvalRunService` - estimated, budget-checked,
metered - as the suite's owner, and settles it once that run ends: held to the
threshold frozen on the result, and the owner told once per run of failures.

A suite runs as whoever last saved it. Nobody watches a scheduled run start, so
it spends with the authority of the person who agreed to it; somebody else
changing what it does takes it over, and it stops - paused, with the reason - when
its owner leaves or loses what running it takes.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec
from app.agents.system_agents import refuse_system_agent
from app.core.audit import current_impersonator, record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.cron import cron_fires, cron_next
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthorizationError,
    BadRequestError,
    EvalSuiteInUseError,
    EvalSuiteNotRunnableError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.eval_run import EvalRunStatus
from app.db.models.eval_suite import (
    EvalSuite,
    EvalSuiteResult,
    EvalSuiteResultStatus,
    EvalSuiteTrigger,
)
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    eval_run_repo,
    eval_suite_repo,
    member_repo,
    promotion_gate_repo,
)
from app.schemas.change_event import ChangeEvent
from app.schemas.eval_run import (
    EvalComparisonRead,
    EvalRunRead,
    EvalRunRequest,
    EvalUngradedCaseRead,
)
from app.schemas.eval_suite import (
    DependencyKind,
    EvalSuiteCreate,
    EvalSuiteEstimate,
    EvalSuiteEstimateRequest,
    EvalSuiteList,
    EvalSuiteRead,
    EvalSuiteResultList,
    EvalSuiteResultRead,
    EvalSuiteSchedule,
    EvalSuiteSummary,
    EvalSuiteThreshold,
    EvalSuiteUpdate,
    FailingCase,
)
from app.services import change_feed
from app.services.access import AGENT, DATASET, accessible_ids, resolve_access
from app.services.agent_registry import AgentRegistryService, delegation_binding
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.eval_suite_threshold import judge

logger = logging.getLogger(__name__)

MAX_FAILING_CASES = 20
_INPUT_CHARS = 120
_SWEEP_SCHEDULES = 100
_SWEEP_STARTS = 20
_SWEEP_SETTLES = 50
# Enough to count an hourly schedule's month exactly; anything denser is extrapolated.
_FIRES_SAMPLE = 1000

_TRIGGERED: dict[EvalSuiteTrigger, Literal["on_publish", "on_promotion"]] = {
    EvalSuiteTrigger.PUBLISH: "on_publish",
    EvalSuiteTrigger.PROMOTION: "on_promotion",
}
_BOUND_FIELD: dict[DependencyKind, Literal["skill_ids", "collection_ids"]] = {
    "skill": "skill_ids",
    "knowledge_base": "collection_ids",
}
# A refusal the eval run gave that means the suite cannot run as set up, rather
# than that its owner lost access - the reason the console words for each.
_REFUSALS = ("ai_assistance_off", "no_scorer")


class _OverCap(Exception):
    def __init__(self, estimate: Decimal, cap: Decimal) -> None:
        super().__init__(f"estimate {estimate} over cap {cap}")
        self.estimate = estimate
        self.cap = cap


def binds(spec: AgentSpec, kind: DependencyKind, resource_id: UUID) -> bool:
    """Whether a version reads this skill or knowledge base - itself, or a specialist it defines.

    A specialist is part of the version that defines it, so its skills and
    collections change that version's answers as much as the parent's do. A
    delegate is another agent, with suites of its own.
    """
    field = _BOUND_FIELD[kind]
    if resource_id in getattr(spec, field):
        return True
    binding = delegation_binding(spec)
    if binding is None:
        return False
    try:
        config = SubagentsConfig.model_validate(binding.config)
    except ValidationError:
        return False
    return any(resource_id in getattr(specialist, field) for specialist in config.inline)


def fires_per_month(schedule: EvalSuiteSchedule, *, now: datetime) -> int:
    """How many times a schedule fires over the next thirty days."""
    return cron_fires(
        schedule.cron,
        start=now,
        end=now + timedelta(days=30),
        time_zone=schedule.timezone,
        sample=_FIRES_SAMPLE,
    )


def threshold_of(suite: EvalSuite) -> EvalSuiteThreshold:
    """The threshold a suite holds now, as a result freezes it."""
    return EvalSuiteThreshold(
        min_pass_rate=float(suite.min_pass_rate) if suite.min_pass_rate is not None else None,
        max_confirmed_regressions=suite.max_confirmed_regressions,
        max_cost_per_pass_rise=(
            float(suite.max_cost_per_pass_rise)
            if suite.max_cost_per_pass_rise is not None
            else None
        ),
        max_p95_rise=float(suite.max_p95_rise) if suite.max_p95_rise is not None else None,
    )


def _schedule(suite: EvalSuite) -> EvalSuiteSchedule | None:
    if suite.schedule_cron is None:
        return None
    return EvalSuiteSchedule(cron=suite.schedule_cron, timezone=suite.schedule_timezone)


def _line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _INPUT_CHARS else flat[: _INPUT_CHARS - 1] + "…"


class EvalSuiteService:
    """Setting suites up, firing them on the events they watch, and the sweep that runs them."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.datasets = DatasetService(db)
        self.evals = EvalRunService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> EvalSuiteList:
        """An agent's suites, for anyone who may see the agent and its runs."""
        self._require_runs_view(ctx)
        agent = await self.registry.get(ctx, agent_id)
        suites = await eval_suite_repo.list_for_agents(
            self.db, [agent.id], organization_id=ctx.organization_id
        )
        return EvalSuiteList(items=await self._reads(ctx, suites), total=len(suites))

    async def list_visible(self, ctx: AuthContext) -> EvalSuiteList:
        """Every suite of the organization on an agent the caller may see - the dashboard's view."""
        suites = await eval_suite_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id
        )
        agents = await agent_repo.get_many(
            self.db,
            sorted({suite.agent_id for suite in suites}),
            organization_id=ctx.organization_id,
        )
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        shown = [suite for suite in suites if suite.agent_id in visible]
        return EvalSuiteList(items=await self._reads(ctx, shown), total=len(shown))

    async def get(self, ctx: AuthContext, agent_id: UUID, suite_id: UUID) -> EvalSuiteRead:
        self._require_runs_view(ctx)
        suite = await self._suite(ctx, agent_id, suite_id)
        return (await self._reads(ctx, [suite]))[0]

    async def results(
        self, ctx: AuthContext, agent_id: UUID, suite_id: UUID, *, skip: int = 0, limit: int = 20
    ) -> EvalSuiteResultList:
        """A suite's results, newest first."""
        self._require_runs_view(ctx)
        suite = await self._suite(ctx, agent_id, suite_id)
        rows, total = await eval_suite_repo.list_results(
            self.db, suite.id, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        readable = await self.readable_datasets(
            ctx, [row.dataset_id for row in rows if row.dataset_id is not None]
        )
        return EvalSuiteResultList(
            items=[self.result_read(row, cases_visible=row.dataset_id in readable) for row in rows],
            total=total,
        )

    async def readable_datasets(self, ctx: AuthContext, dataset_ids: list[UUID]) -> set[UUID]:
        """Which of these datasets the reader may open - and so read the cases of."""
        datasets = await eval_run_repo.datasets(
            self.db, sorted(set(dataset_ids)), organization_id=ctx.organization_id
        )
        return await accessible_ids(
            self.db, ctx, list(datasets.values()), Perm.DATASETS_VIEW, resource_type=DATASET
        )

    async def _suite(self, ctx: AuthContext, agent_id: UUID, suite_id: UUID) -> EvalSuite:
        agent = await self.registry.get(ctx, agent_id)
        suite = await eval_suite_repo.get(self.db, suite_id, organization_id=ctx.organization_id)
        if suite is None or suite.agent_id != agent.id:
            raise NotFoundError(message="Eval suite not found", details={"suite_id": suite_id})
        return suite

    async def _reads(self, ctx: AuthContext, suites: list[EvalSuite]) -> list[EvalSuiteRead]:
        if not suites:
            return []
        org = ctx.organization_id
        ids = [suite.id for suite in suites]
        agents = await agent_repo.get_many(
            self.db, sorted({suite.agent_id for suite in suites}), organization_id=org
        )
        datasets = await eval_run_repo.datasets(
            self.db, sorted({suite.dataset_id for suite in suites}), organization_id=org
        )
        latest = await eval_suite_repo.latest_results(self.db, ids, organization_id=org)
        current = await eval_suite_repo.open_results(self.db, ids, organization_id=org)
        checked = [
            result.dataset_id
            for result in (*latest.values(), *current.values())
            if result.dataset_id is not None
        ]
        readable = await self.readable_datasets(ctx, [*datasets, *checked])
        environments: dict[UUID, AgentEnvironment] = {}
        for agent_id in agents:
            for environment in await agent_environment_repo.list_for_agent(
                self.db, agent_id=agent_id, organization_id=org
            ):
                environments[environment.id] = environment
        owners = await member_repo.get_emails_for_users(
            self.db,
            organization_id=org,
            user_ids=sorted({suite.owner_user_id for suite in suites if suite.owner_user_id}),
        )
        reads = []
        for suite in suites:
            environment = environments.get(suite.environment_id) if suite.environment_id else None
            last = latest.get(suite.id)
            now = current.get(suite.id)
            reads.append(
                EvalSuiteRead(
                    id=suite.id,
                    agent_id=suite.agent_id,
                    agent_name=agents[suite.agent_id].name,
                    dataset_id=suite.dataset_id,
                    dataset_name=(
                        datasets[suite.dataset_id].name if suite.dataset_id in readable else None
                    ),
                    environment_id=suite.environment_id,
                    environment_name=environment.name if environment else None,
                    owner_user_id=suite.owner_user_id,
                    owner_email=owners.get(suite.owner_user_id) if suite.owner_user_id else None,
                    name=suite.name,
                    description=suite.description,
                    is_active=suite.is_active,
                    paused_reason=suite.paused_reason,
                    threshold=threshold_of(suite),
                    on_publish=suite.on_publish,
                    on_promotion=suite.on_promotion,
                    on_dependency_change=suite.on_dependency_change,
                    schedule=_schedule(suite),
                    next_fire_at=suite.next_fire_at,
                    max_run_usd=suite.max_run_usd,
                    last_result=(
                        self.result_read(last, cases_visible=last.dataset_id in readable)
                        if last
                        else None
                    ),
                    open_result=(
                        self.result_read(now, cases_visible=now.dataset_id in readable)
                        if now
                        else None
                    ),
                    created_at=suite.created_at,
                    updated_at=suite.updated_at,
                )
            )
        return reads

    @staticmethod
    def result_read(result: EvalSuiteResult, *, cases_visible: bool) -> EvalSuiteResultRead:
        """A result as a reader sees it: the failing cases' questions only for one who
        may open the dataset they come from."""
        summary = (
            EvalSuiteSummary.model_validate(result.summary) if result.summary is not None else None
        )
        if summary is not None and not cases_visible:
            summary = summary.model_copy(update={"failing_cases": []})
        return EvalSuiteResultRead(
            id=result.id,
            suite_id=result.suite_id,
            trigger=EvalSuiteTrigger(result.trigger),
            trigger_detail=result.trigger_detail,
            version_number=result.version_number,
            baseline_version_number=result.baseline_version_number,
            environment_id=result.environment_id,
            status=EvalSuiteResultStatus(result.status),
            reason=result.reason,
            due_at=result.due_at,
            eval_run_id=result.eval_run_id,
            baseline_eval_run_id=result.baseline_eval_run_id,
            run_as_user_id=result.run_as_user_id,
            threshold=EvalSuiteThreshold.model_validate(result.threshold),
            summary=summary,
            notified_at=result.notified_at,
            created_at=result.created_at,
            started_at=result.started_at,
            settled_at=result.settled_at,
        )

    @staticmethod
    def _require_runs_view(ctx: AuthContext) -> None:
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Reading eval suites needs permission to view runs",
                details={"permission": Perm.RUNS_VIEW.value},
            )

    async def _editable(self, ctx: AuthContext, agent_id: UUID) -> Agent:
        """The agent, when the caller may set up suites on it, in person.

        A suite spends as whoever saves it, with nobody watching it start - so
        only a person may save one, not a script holding their key nor an
        administrator acting as them; and only somebody who may edit the agent,
        run it, start eval runs and read what they find.
        """
        if ctx.user_id is None or ctx.api_key_id is not None or current_impersonator() is not None:
            raise AuthorizationError(
                message=(
                    "An eval suite runs as the person who saves it, so it can only be "
                    "saved by that person, signed in"
                ),
                details={"agent_id": agent_id},
            )
        self._require_runs_view(ctx)
        agent = await self.registry.get(ctx, agent_id)
        refuse_system_agent(agent, action="have eval suites")
        if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
            raise AuthorizationError(
                message="Setting up eval suites needs edit access to the agent",
                details={"agent_id": agent.id},
            )
        if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
            raise AuthorizationError(
                message="An eval suite runs the agent, which needs permission to run it",
                details={"agent_id": agent.id},
            )
        return agent

    async def _check_environment(
        self, ctx: AuthContext, agent: Agent, environment_id: UUID
    ) -> None:
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            raise NotFoundError(
                message="Environment not found", details={"environment_id": environment_id}
            )

    async def _check_name(self, ctx: AuthContext, agent: Agent, name: str) -> None:
        if await eval_suite_repo.get_by_name(
            self.db, agent_id=agent.id, name=name, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message=f"'{agent.name}' already has an eval suite named '{name}'",
                details={"agent_id": agent.id, "name": name},
            )

    async def create(
        self, ctx: AuthContext, agent_id: UUID, data: EvalSuiteCreate
    ) -> EvalSuiteRead:
        """Set a suite up; it runs as the caller from now on."""
        agent = await self._editable(ctx, agent_id)
        await self.datasets.get(ctx, data.dataset_id, perm=Perm.DATASETS_RUN)
        if data.environment_id is not None:
            await self._check_environment(ctx, agent, data.environment_id)
        await self._check_name(ctx, agent, data.name)
        now = datetime.now(UTC)
        suite = await eval_suite_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            suite=EvalSuite(
                agent_id=agent.id,
                dataset_id=data.dataset_id,
                environment_id=data.environment_id,
                owner_user_id=ctx.user_id,
                name=data.name,
                description=data.description,
                is_active=True,
                on_publish=data.on_publish,
                on_promotion=data.on_promotion,
                on_dependency_change=data.on_dependency_change,
                max_run_usd=data.max_run_usd,
                **self._threshold_columns(data.threshold),
                **self._schedule_columns(data.schedule, now=now),
            ),
        )
        await self._audit(ctx, suite, "eval_suite.created", {"name": suite.name})
        return (await self._reads(ctx, [suite]))[0]

    async def update(
        self, ctx: AuthContext, agent_id: UUID, suite_id: UUID, data: EvalSuiteUpdate
    ) -> EvalSuiteRead:
        """Change, pause or resume a suite. The caller becomes its owner."""
        agent = await self._editable(ctx, agent_id)
        suite = await self._suite(ctx, agent.id, suite_id)
        fields = data.model_fields_set
        values: dict[str, Any] = {"owner_user_id": ctx.user_id}
        if data.name is not None and data.name != suite.name:
            await self._check_name(ctx, agent, data.name)
            values["name"] = data.name
        if "description" in fields:
            values["description"] = data.description
        if data.dataset_id is not None and data.dataset_id != suite.dataset_id:
            values["dataset_id"] = data.dataset_id
        await self.datasets.get(
            ctx, values.get("dataset_id", suite.dataset_id), perm=Perm.DATASETS_RUN
        )
        if "environment_id" in fields:
            if data.environment_id is not None:
                await self._check_environment(ctx, agent, data.environment_id)
            if data.environment_id != suite.environment_id:
                values["environment_id"] = data.environment_id
            if suite.paused_reason == "environment_gone":
                values["paused_reason"] = None
        elif data.is_active and suite.paused_reason == "environment_gone":
            raise refused_field(
                "environment_id",
                "Its environment was removed. Choose the one this suite checks to resume it.",
            )
        if data.threshold is not None:
            values.update(self._threshold_columns(data.threshold))
        for flag in ("on_publish", "on_promotion", "on_dependency_change"):
            if getattr(data, flag) is not None:
                values[flag] = getattr(data, flag)
        if "max_run_usd" in fields:
            values["max_run_usd"] = data.max_run_usd
        now = datetime.now(UTC)
        resuming = data.is_active is True and not suite.is_active
        if "schedule" in fields or resuming:
            schedule = data.schedule if "schedule" in fields else _schedule(suite)
            values.update(self._schedule_columns(schedule, now=now))
        await self._guarding_change(ctx, suite, data=data, values=values)
        if "dataset_id" in values or "environment_id" in values:
            # A waiting result was queued for the version and cases as they were set
            # up; run against the new ones it would record a check nobody asked for.
            await eval_suite_repo.discard_pending(
                self.db, suite.id, organization_id=ctx.organization_id
            )
        action = "eval_suite.updated"
        if data.is_active is not None and data.is_active != suite.is_active:
            values["is_active"] = data.is_active
            values["paused_reason"] = None
            action = "eval_suite.resumed" if data.is_active else "eval_suite.paused"
            if not data.is_active:
                await eval_suite_repo.discard_pending(
                    self.db, suite.id, organization_id=ctx.organization_id
                )
        suite = await eval_suite_repo.update(self.db, suite=suite, values=values)
        await self._audit(ctx, suite, action, {"fields": sorted(fields)})
        return (await self._reads(ctx, [suite]))[0]

    async def _guarding_change(
        self, ctx: AuthContext, suite: EvalSuite, *, data: EvalSuiteUpdate, values: dict[str, Any]
    ) -> None:
        """Refuse a change to what a guarding suite checks, unless the caller may override.

        A lower bar, an easier dataset or another environment's connections is
        a guard taken off by another road, so it needs what taking one off needs,
        and is recorded the same way. Pausing is not: a paused guard holds a
        promotion back.
        """
        changed = sorted(
            field
            for field, moved in (
                ("threshold", data.threshold is not None and data.threshold != threshold_of(suite)),
                ("dataset_id", "dataset_id" in values),
                ("environment_id", "environment_id" in values),
            )
            if moved
        )
        if not changed:
            return
        guarded = await promotion_gate_repo.guarded_by(
            self.db, suite.id, organization_id=ctx.organization_id
        )
        if not guarded:
            return
        from app.services.promotion_gate import PromotionGateService

        names = ", ".join(environment.name for environment in guarded)
        if not PromotionGateService.may_override(ctx):
            raise AuthorizationError(
                message=(
                    f"'{suite.name}' guards {names}. Changing what it checks needs "
                    "permission to override promotions."
                ),
                details={"suite_id": suite.id, "permission": Perm.PROMOTIONS_OVERRIDE.value},
            )
        for environment in guarded:
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="agent.environment_guards_changed",
                target_type="agent",
                target_id=str(suite.agent_id),
                details={
                    "environment_id": str(environment.id),
                    "name": environment.name,
                    "suite_id": str(suite.id),
                    "fields": changed,
                },
            )

    async def delete(self, ctx: AuthContext, agent_id: UUID, suite_id: UUID) -> None:
        """Remove a suite and its results. The eval runs it started stay.

        Raises:
            EvalSuiteInUseError: The suite guards an environment - removing it would
                unguard that environment without anybody deciding to.
        """
        agent = await self._editable(ctx, agent_id)
        suite = await self._suite(ctx, agent.id, suite_id)
        guarded = await promotion_gate_repo.guarded_by(
            self.db, suite.id, organization_id=ctx.organization_id
        )
        if guarded:
            names = ", ".join(environment.name for environment in guarded)
            raise EvalSuiteInUseError(
                message=f"'{suite.name}' guards {names}. Take it off there before deleting it.",
                details={"suite_id": suite.id, "environments": [e.id for e in guarded]},
            )
        await self._audit(ctx, suite, "eval_suite.deleted", {"name": suite.name})
        await eval_suite_repo.delete_suite(self.db, suite=suite)

    @staticmethod
    def _threshold_columns(threshold: EvalSuiteThreshold) -> dict[str, Any]:
        def fraction(value: float | None) -> Decimal | None:
            return None if value is None else Decimal(str(value))

        return {
            "min_pass_rate": fraction(threshold.min_pass_rate),
            "max_confirmed_regressions": threshold.max_confirmed_regressions,
            "max_cost_per_pass_rise": fraction(threshold.max_cost_per_pass_rise),
            "max_p95_rise": fraction(threshold.max_p95_rise),
        }

    @staticmethod
    def _schedule_columns(schedule: EvalSuiteSchedule | None, *, now: datetime) -> dict[str, Any]:
        if schedule is None:
            return {"schedule_cron": None, "schedule_timezone": "UTC", "next_fire_at": None}
        return {
            "schedule_cron": schedule.cron,
            "schedule_timezone": schedule.timezone,
            "next_fire_at": cron_next(schedule.cron, now=now, time_zone=schedule.timezone),
        }

    async def _audit(
        self, ctx: AuthContext, suite: EvalSuite, action: str, details: dict[str, Any]
    ) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="agent",
            target_id=str(suite.agent_id),
            details={"suite_id": str(suite.id), **details},
        )

    async def estimate(
        self, ctx: AuthContext, agent_id: UUID, data: EvalSuiteEstimateRequest
    ) -> EvalSuiteEstimate:
        """What a run of a suite set up this way costs, and a month of its schedule."""
        agent = await self._editable(ctx, agent_id)
        version = await self._served(
            agent, data.environment_id, organization_id=ctx.organization_id
        )
        if version is None:
            raise BadRequestError(
                message=f"'{agent.name}' has no published version to check yet",
                details={"agent_id": agent.id},
            )
        request = EvalRunRequest(
            dataset_id=data.dataset_id, environment_id=data.environment_id, version=version.version
        )
        run = await self.evals.estimate(ctx, agent.id, request)
        previous = await agent_repo.version_before(
            self.db, agent_id=agent.id, number=version.version, organization_id=ctx.organization_id
        )
        paired = (
            await self.evals.estimate(
                ctx,
                agent.id,
                request.model_copy(
                    update={"paired_baseline": True, "baseline_version": previous.version}
                ),
            )
            if previous is not None
            else None
        )
        fires = (
            fires_per_month(data.schedule, now=datetime.now(UTC))
            if data.schedule is not None
            else None
        )
        return EvalSuiteEstimate(
            run=run,
            paired_run=paired,
            fires_per_month=fires,
            monthly_usd=None if fires is None else run.total_usd * fires,
        )

    async def run_now(
        self, ctx: AuthContext, agent_id: UUID, suite_id: UUID
    ) -> EvalSuiteResultRead:
        """Run a suite now, as the caller, on the version it checks.

        Raises:
            EvalSuiteNotRunnableError: The suite is paused, or already running.
            BadRequestError: There is no published version to check, or the eval
                run refused - its message says why.
            PaymentRequiredError: The run would cost more than is left.
        """
        agent = await self._editable(ctx, agent_id)
        suite = await self._suite(ctx, agent.id, suite_id)
        version = await self._served(
            agent, suite.environment_id, organization_id=ctx.organization_id
        )
        if version is None:
            raise BadRequestError(
                message=f"'{agent.name}' has no published version to check yet",
                details={"agent_id": agent.id},
            )
        result = await self._run_by_hand(
            ctx, agent, suite, version, trigger=EvalSuiteTrigger.MANUAL, baseline_version=None
        )
        return self.result_read(result, cases_visible=True)

    async def run_on_version(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        suite_id: UUID,
        *,
        version: AgentVersion,
        baseline_version: int | None,
    ) -> EvalSuiteResult:
        """Run a suite now, as the caller, on a version an environment may take,
        beside the version it would replace.

        Raises the same refusals as `run_now`.
        """
        agent = await self._editable(ctx, agent_id)
        suite = await self._suite(ctx, agent.id, suite_id)
        return await self._run_by_hand(
            ctx,
            agent,
            suite,
            version,
            trigger=EvalSuiteTrigger.GATE,
            baseline_version=baseline_version if baseline_version != version.version else None,
        )

    async def _run_by_hand(
        self,
        ctx: AuthContext,
        agent: Agent,
        suite: EvalSuite,
        version: AgentVersion,
        *,
        trigger: EvalSuiteTrigger,
        baseline_version: int | None,
    ) -> EvalSuiteResult:
        # Held until this request commits, so a second press or the sweep starting
        # this suite waits and then sees the run this one started.
        await eval_suite_repo.lock(self.db, suite.id, organization_id=ctx.organization_id)
        if not suite.is_active:
            raise EvalSuiteNotRunnableError(
                message=f"'{suite.name}' is paused. Resume it to run it.",
                details={"suite_id": suite.id, "reason": "paused"},
            )
        if await eval_suite_repo.running_for(
            self.db, suite.id, organization_id=ctx.organization_id
        ):
            raise EvalSuiteNotRunnableError(
                message=f"'{suite.name}' is already running.",
                details={"suite_id": suite.id, "reason": "running"},
            )
        now = datetime.now(UTC)
        values = self._result_values(
            suite,
            trigger=trigger,
            version=version,
            due_at=now,
            baseline_version=baseline_version,
        )
        baseline = (
            None
            if baseline_version is not None
            else await self._earlier_run(suite, version.id, now=now)
        )
        request = self._request(
            suite, version.version, baseline_version=baseline_version, baseline_run=baseline
        )
        try:
            await self._within_cap(ctx, suite, request)
        except _OverCap as over:
            raise BadRequestError(
                message=(
                    f"A run of '{suite.name}' is estimated at ${over.estimate:.2f}, over "
                    f"the suite's ${over.cap:.2f} ceiling. Raise the ceiling to run it."
                ),
                details={
                    "suite_id": suite.id,
                    "reason": "over_cost_cap",
                    # Money is stringified deliberately: a Decimal encodes to a float.
                    "estimate_usd": str(over.estimate),
                    "max_run_usd": str(over.cap),
                },
            ) from None
        run = await self.evals.start(ctx, agent.id, request)
        result = await eval_suite_repo.add_result(
            self.db,
            organization_id=ctx.organization_id,
            values={
                **values,
                "status": EvalSuiteResultStatus.RUNNING.value,
                "run_as_user_id": ctx.user_id,
                "eval_run_id": run.id,
                "baseline_eval_run_id": baseline,
                "started_at": now,
            },
        )
        assert result is not None, "a running result never conflicts with a waiting one"
        self._announce(suite)
        return result

    async def _within_cap(
        self, ctx: AuthContext, suite: EvalSuite, request: EvalRunRequest
    ) -> None:
        if suite.max_run_usd is None:
            return
        estimate = await self.evals.estimate(ctx, suite.agent_id, request)
        if estimate.total_usd > suite.max_run_usd:
            raise _OverCap(estimate.total_usd, suite.max_run_usd)

    async def version_published(
        self, ctx: AuthContext, *, agent: Agent, version: AgentVersion
    ) -> None:
        """Queue the suites a publish starts: those set to run on publish, against the
        previous version, and those whose environment followed the publish onto it."""
        org = ctx.organization_id
        previous = await agent_repo.version_before(
            self.db, agent_id=agent.id, number=version.version, organization_id=org
        )
        now = datetime.now(UTC)
        for suite in await eval_suite_repo.list_watching(
            self.db, organization_id=org, flag="on_publish", agent_id=agent.id
        ):
            await self._enqueue(
                suite,
                trigger=EvalSuiteTrigger.PUBLISH,
                version=version,
                due_at=now,
                baseline_version=previous.version if previous else None,
            )
        environments = await agent_environment_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=org
        )
        guarded = await promotion_gate_repo.guards_for(
            self.db,
            [env.id for env in environments if env.tracks_latest],
            organization_id=org,
        )
        for environment in environments:
            for suite_id in guarded.get(environment.id, []):
                suite = await eval_suite_repo.get(self.db, suite_id, organization_id=org)
                assert suite is not None, "a suite that guards cannot be deleted"
                serving = await agent_repo.get_version(
                    self.db, environment.version_id, organization_id=org
                )
                if suite.is_active:
                    await self._enqueue(
                        suite,
                        trigger=EvalSuiteTrigger.GATE,
                        version=version,
                        due_at=now,
                        baseline_version=serving.version if serving else None,
                    )
        moved = {env.id for env in environments if env.version_id == version.id}
        default = next((env.id for env in environments if env.is_default), None)
        for suite in await eval_suite_repo.list_watching(
            self.db, organization_id=org, flag="on_promotion", agent_id=agent.id
        ):
            if (suite.environment_id or default) in moved:
                await self._enqueue(
                    suite,
                    trigger=EvalSuiteTrigger.PROMOTION,
                    version=version,
                    due_at=now,
                    baseline_version=previous.version if previous else None,
                )

    async def environment_promoted(
        self,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
        replaced_version_id: UUID,
    ) -> None:
        """Queue the suites watching promotions onto this environment, each measured
        against the version the promotion replaced."""
        replaced = await agent_repo.get_version(
            self.db, replaced_version_id, organization_id=agent.organization_id
        )
        now = datetime.now(UTC)
        for suite in await eval_suite_repo.list_watching(
            self.db, organization_id=agent.organization_id, flag="on_promotion", agent_id=agent.id
        ):
            watched = suite.environment_id or (environment.id if environment.is_default else None)
            if watched != environment.id:
                continue
            await self._enqueue(
                suite,
                trigger=EvalSuiteTrigger.PROMOTION,
                version=version,
                due_at=now,
                baseline_version=replaced.version if replaced is not None else None,
            )

    async def environment_removed(self, environment: AgentEnvironment) -> None:
        """Pause the suites checking an environment that is going away, those
        already paused included.

        Its reference would be set null and the suite would quietly check the
        agent's current version instead - a different version than its owner
        chose - so it resumes only once somebody names the environment again.
        """
        for suite in await eval_suite_repo.list_on_environment(
            self.db, environment.id, organization_id=environment.organization_id
        ):
            await self._pause(suite, reason="environment_gone")

    async def dependency_changed(
        self, *, organization_id: UUID, kind: DependencyKind, resource_id: UUID
    ) -> None:
        """Queue the suites whose checked version binds what changed.

        Due a quiet period later, so the burst of edits one change usually is -
        a document upload of thirty files, a skill and its resources - is one
        run, on the content as it ends up.
        """
        due = datetime.now(UTC) + timedelta(seconds=settings.EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS)
        for suite in await eval_suite_repo.list_watching(
            self.db, organization_id=organization_id, flag="on_dependency_change"
        ):
            agent = await agent_repo.get(self.db, suite.agent_id, organization_id=organization_id)
            assert agent is not None, "a suite goes with its agent"
            version = await self._served(
                agent, suite.environment_id, organization_id=organization_id
            )
            if version is None or not binds(
                AgentSpec.model_validate(version.spec), kind, resource_id
            ):
                continue
            await self._enqueue(
                suite,
                trigger=EvalSuiteTrigger.DEPENDENCY,
                version=version,
                due_at=due,
                detail={"kind": kind, "id": str(resource_id)},
            )

    async def _served(
        self, agent: Agent, environment_id: UUID | None, *, organization_id: UUID
    ) -> AgentVersion | None:
        """The version a suite checks: its environment's, or the agent's current one."""
        version_id = agent.current_version_id
        if environment_id is not None:
            environment = await agent_environment_repo.get(
                self.db, environment_id, organization_id=organization_id
            )
            # The suite's reference is set null when the environment goes.
            assert environment is not None, "a suite names only an environment that exists"
            version_id = environment.version_id
        if version_id is None:
            return None
        return await agent_repo.get_version(self.db, version_id, organization_id=organization_id)

    def _result_values(
        self,
        suite: EvalSuite,
        *,
        trigger: EvalSuiteTrigger,
        version: AgentVersion,
        due_at: datetime,
        baseline_version: int | None = None,
        detail: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "suite_id": suite.id,
            "trigger": trigger.value,
            "trigger_detail": detail,
            "agent_version_id": version.id,
            "version_number": version.version,
            "baseline_version_number": baseline_version,
            "dataset_id": suite.dataset_id,
            "environment_id": suite.environment_id,
            "status": EvalSuiteResultStatus.PENDING.value,
            "due_at": due_at,
            "threshold": threshold_of(suite).model_dump(mode="json"),
        }

    async def _enqueue(
        self,
        suite: EvalSuite,
        *,
        trigger: EvalSuiteTrigger,
        version: AgentVersion,
        due_at: datetime,
        baseline_version: int | None = None,
        detail: dict[str, str] | None = None,
    ) -> EvalSuiteResult | None:
        result = await eval_suite_repo.add_result(
            self.db,
            organization_id=suite.organization_id,
            values=self._result_values(
                suite,
                trigger=trigger,
                version=version,
                due_at=due_at,
                baseline_version=baseline_version,
                detail=detail,
            ),
        )
        if result is not None:
            self._announce(suite)
        return result

    async def fire_schedules(self, *, now: datetime) -> int:
        """Queue a run of every suite whose schedule came due, and move its schedule on.

        A suite missing a fire while the worker was down runs once, not once per
        fire it missed - the next fire is measured from now.
        """
        fired = 0
        for suite in await eval_suite_repo.claim_due_schedules(
            self.db, now=now, limit=_SWEEP_SCHEDULES
        ):
            schedule = _schedule(suite)
            assert schedule is not None, "a due suite has a schedule; the CHECK holds the pair"
            await eval_suite_repo.update(
                self.db,
                suite=suite,
                values={
                    "next_fire_at": cron_next(schedule.cron, now=now, time_zone=schedule.timezone)
                },
            )
            agent = await agent_repo.get(
                self.db, suite.agent_id, organization_id=suite.organization_id
            )
            assert agent is not None, "a suite goes with its agent"
            version = await self._served(
                agent, suite.environment_id, organization_id=suite.organization_id
            )
            if version is None:
                await self._finish_unstarted(
                    suite,
                    trigger=EvalSuiteTrigger.SCHEDULE,
                    reason="not_published",
                    message=f"'{agent.name}' has no published version to check.",
                    now=now,
                )
                continue
            await self._enqueue(
                suite, trigger=EvalSuiteTrigger.SCHEDULE, version=version, due_at=now
            )
            fired += 1
        return fired

    async def start_due(self, *, now: datetime) -> int:
        """Start the results that are due, each as an eval run of its suite's owner."""
        started = 0
        for result in await eval_suite_repo.claim_pending(self.db, now=now, limit=_SWEEP_STARTS):
            if await self._isolated(
                result, lambda row=result: self._start(row, now=now), step="start", now=now
            ):
                started += 1
        return started

    async def _isolated(
        self,
        result: EvalSuiteResult,
        work: Callable[[], Awaitable[bool | None]],
        *,
        step: Literal["start", "settle"],
        now: datetime,
    ) -> bool:
        """One result's step in a savepoint of its own.

        A failure nobody planned for - a provider client misconfigured, a bug -
        ends that result in error, logged, rather than rolling back every other
        suite's start or settlement in the tick and failing the same way each
        minute after.
        """
        result_id, organization_id = result.id, result.organization_id
        try:
            async with self.db.begin_nested():
                return bool(await work())
        except Exception as failure:
            logger.exception(
                "eval_suite_step_failed", extra={"result_id": str(result_id), "step": step}
            )
            row = await eval_suite_repo.get_result(
                self.db, result_id, organization_id=organization_id
            )
            assert row is not None, "the savepoint rolled back the step, not the result"
            await self._finish(
                row,
                EvalSuiteResultStatus.ERROR,
                reason=f"{step}_failed",
                message=failure.message if isinstance(failure, AppException) else None,
                now=now,
            )
            return False

    async def _start(self, result: EvalSuiteResult, *, now: datetime) -> bool:
        org = result.organization_id
        suite = await eval_suite_repo.lock(self.db, result.suite_id, organization_id=org)
        assert suite is not None, "a result goes with its suite"
        if not suite.is_active:
            # Pausing discards what was waiting, but a trigger that read the suite
            # as running before the pause committed can still have queued one.
            await eval_suite_repo.discard_pending(self.db, suite.id, organization_id=org)
            return False
        if await eval_suite_repo.running_for(self.db, suite.id, organization_id=org):
            # Started by hand after this result was claimed: it waits for that run.
            return False
        owner = await self._person(org, suite.owner_user_id)
        if owner is None:
            await self._finish(
                result, EvalSuiteResultStatus.SKIPPED, reason="owner_inactive", now=now
            )
            await self._pause(suite, reason="owner_inactive")
            return False
        if result.version_number is None or result.agent_version_id is None:
            await self._finish(
                result, EvalSuiteResultStatus.SKIPPED, reason="version_gone", now=now
            )
            return False
        baseline = (
            None
            if result.baseline_version_number is not None
            else await self._earlier_run(suite, result.agent_version_id, now=now)
        )
        request = self._request(
            suite,
            result.version_number,
            baseline_version=result.baseline_version_number,
            baseline_run=baseline,
        )
        try:
            async with self.db.begin_nested():
                await self._within_cap(owner, suite, request)
                run = await self.evals.start(owner, suite.agent_id, request)
        except _OverCap as over:
            message = (
                f"The run was estimated at ${over.estimate:.2f}, over this suite's "
                f"${over.cap:.2f} ceiling."
            )
            await self._finish(
                result,
                EvalSuiteResultStatus.SKIPPED,
                reason="over_cost_cap",
                message=message,
                now=now,
            )
            return False
        except PaymentRequiredError as refused:
            await self._finish(
                result,
                EvalSuiteResultStatus.SKIPPED,
                reason="budget",
                message=refused.message,
                now=now,
            )
            return False
        except (NotFoundError, AuthorizationError) as refused:
            await self._finish(
                result,
                EvalSuiteResultStatus.ERROR,
                reason="owner_lacks_access",
                message=refused.message,
                now=now,
            )
            await self._pause(suite, reason="owner_lacks_access")
            return False
        except BadRequestError as refused:
            code = refused.details.get("reason") if isinstance(refused.details, dict) else None
            await self._finish(
                result,
                EvalSuiteResultStatus.SKIPPED,
                reason=code if code in _REFUSALS else "not_runnable",
                message=refused.message,
                now=now,
            )
            return False
        await eval_suite_repo.update_result(
            self.db,
            result=result,
            values={
                "status": EvalSuiteResultStatus.RUNNING.value,
                "run_as_user_id": owner.user_id,
                "eval_run_id": run.id,
                "baseline_eval_run_id": baseline,
                "started_at": now,
            },
        )
        self._announce(suite)
        return True

    def _request(
        self,
        suite: EvalSuite,
        version: int,
        *,
        baseline_version: int | None,
        baseline_run: UUID | None,
    ) -> EvalRunRequest:
        """A publish or a promotion runs its baseline beside it; any other run is measured
        against the suite's last run of the same version, so it shows drift."""
        return EvalRunRequest(
            dataset_id=suite.dataset_id,
            environment_id=suite.environment_id,
            version=version,
            paired_baseline=baseline_version is not None,
            baseline_version=baseline_version,
            baseline_run_id=baseline_run,
        )

    async def _earlier_run(
        self, suite: EvalSuite, version_id: UUID, *, now: datetime
    ) -> UUID | None:
        """The eval run of this suite's last passing result on the same version and
        dataset, to measure drift against.

        The last state known to be good, not merely the last run: measured against
        yesterday's failure, a case still broken today would not have flipped, and
        a suite that had just gone red would read green again with the agent
        unchanged. None once a later result could not be compared with it - the
        judge or the scoring changed since - so the next run is held to its own
        numbers and, passing, becomes the state the ones after it are measured
        against.
        """
        passed = await eval_suite_repo.previous_settled(
            self.db,
            suite_id=suite.id,
            agent_version_id=version_id,
            before=now,
            organization_id=suite.organization_id,
            passed_on_dataset=suite.dataset_id,
        )
        if passed is None or passed.settled_at is None:
            return None
        if await eval_suite_repo.incomparable_since(
            self.db,
            suite_id=suite.id,
            agent_version_id=version_id,
            since=passed.settled_at,
            organization_id=suite.organization_id,
        ):
            return None
        return passed.eval_run_id

    async def settle_finished(self, *, now: datetime) -> int:
        """Hold every result whose eval run has ended to its threshold."""
        settled = 0
        for result in await eval_suite_repo.claim_finished(self.db, limit=_SWEEP_SETTLES):
            await self._isolated(
                result, lambda row=result: self._settle(row, now=now), step="settle", now=now
            )
            settled += 1
        return settled

    async def _settle(self, result: EvalSuiteResult, *, now: datetime) -> None:
        org = result.organization_id
        run = (
            await eval_run_repo.get(self.db, result.eval_run_id, organization_id=org)
            if result.eval_run_id is not None
            else None
        )
        if run is None:
            await self._finish(result, EvalSuiteResultStatus.ERROR, reason="run_gone", now=now)
            return
        if run.status != EvalRunStatus.COMPLETED.value:
            await self._finish(
                result, EvalSuiteResultStatus.ERROR, reason=run.status, message=run.error, now=now
            )
            return
        reader = await self._person(org, result.run_as_user_id)
        if reader is None:
            await self._finish(
                result, EvalSuiteResultStatus.ERROR, reason="owner_inactive", now=now
            )
            await self._pause_for_owner(result, reason="owner_inactive")
            return
        try:
            read = await self.evals.get(reader, run.id)
            comparison = await self.evals.compare(reader, run.id)
        except (NotFoundError, AuthorizationError) as refused:
            await self._finish(
                result,
                EvalSuiteResultStatus.ERROR,
                reason="owner_lacks_access",
                message=refused.message,
                now=now,
            )
            await self._pause_for_owner(result, reason="owner_lacks_access")
            return
        threshold = EvalSuiteThreshold.model_validate(result.threshold)
        candidate = next(arm for arm in read.arms if arm.role == "candidate")
        status, reasons = judge(
            threshold, candidate.summary, comparison, ungraded=len(candidate.ungraded_cases)
        )
        summary = EvalSuiteSummary(
            pass_rate=candidate.summary.pass_rate,
            first_pass_rate=candidate.summary.first_pass_rate,
            cases=candidate.summary.cases,
            baseline_pass_rate=(
                comparison.baseline_summary.pass_rate if comparison.baseline_summary else None
            ),
            baseline_run_id=comparison.baseline.run_id if comparison.baseline else None,
            baseline_version=comparison.baseline.version_number if comparison.baseline else None,
            paired=comparison.paired,
            verdict=comparison.verdict,
            overall=comparison.overall,
            invalid_reason=comparison.invalid_reason,
            regressions_confirmed=comparison.regressions_confirmed,
            regressions_unconfirmed=comparison.regressions_unconfirmed,
            fixed_confirmed=comparison.fixed_confirmed,
            cost_per_pass_usd=comparison.candidate_summary.cost_per_pass_usd,
            baseline_cost_per_pass_usd=(
                comparison.baseline_summary.cost_per_pass_usd
                if comparison.baseline_summary
                else None
            ),
            p95_ms=comparison.candidate_summary.p95_ms,
            baseline_p95_ms=(
                comparison.baseline_summary.p95_ms if comparison.baseline_summary else None
            ),
            reasons=reasons,
            failing_cases=await self._failing(reader, read, comparison, candidate.ungraded_cases),
        )
        await self._finish(result, status, summary=summary, now=now)

    async def _failing(
        self,
        reader: AuthContext,
        read: EvalRunRead,
        comparison: EvalComparisonRead,
        ungraded: list[EvalUngradedCaseRead],
    ) -> list[FailingCase]:
        """The cases to name: confirmed regressions first, then the ones no scorer
        decided, then first answers that failed."""
        named = [
            FailingCase(case_id=case.case_id, input=_line(case.input), kind="regression")
            for case in comparison.cases
            if case.flip == "regression" and case.confirmed
        ]
        named += [
            FailingCase(case_id=case.case_id, input=_line(case.input), kind="ungraded")
            for case in ungraded
        ]
        seen = {case.case_id for case in named}
        failed = await self.evals.cases(reader, read.id, outcome="failed", limit=MAX_FAILING_CASES)
        named += [
            FailingCase(case_id=case.case_id, input=_line(case.input), kind="failed")
            for case in failed.items
            if case.case_id not in seen
        ]
        return named[:MAX_FAILING_CASES]

    async def _finish_unstarted(
        self,
        suite: EvalSuite,
        *,
        trigger: EvalSuiteTrigger,
        reason: str,
        message: str,
        now: datetime,
    ) -> None:
        """Record a run that could not even be queued - nothing published to check."""
        result = await eval_suite_repo.add_result(
            self.db,
            organization_id=suite.organization_id,
            values={
                "suite_id": suite.id,
                "trigger": trigger.value,
                "dataset_id": suite.dataset_id,
                "environment_id": suite.environment_id,
                "status": EvalSuiteResultStatus.PENDING.value,
                "due_at": now,
                "threshold": threshold_of(suite).model_dump(mode="json"),
            },
        )
        assert result is not None, "a result naming no version never coalesces"
        await self._finish(
            result, EvalSuiteResultStatus.SKIPPED, reason=reason, message=message, now=now
        )

    async def _finish(
        self,
        result: EvalSuiteResult,
        status: EvalSuiteResultStatus,
        *,
        now: datetime,
        reason: str | None = None,
        message: str | None = None,
        summary: EvalSuiteSummary | None = None,
    ) -> None:
        """Settle a result, and tell the owner when it opens a run of failures."""
        previous = await eval_suite_repo.previous_settled(
            self.db,
            suite_id=result.suite_id,
            agent_version_id=result.agent_version_id,
            before=now,
            organization_id=result.organization_id,
        )
        alerting_since = None
        if status.alerting:
            carried = (
                previous is not None
                and EvalSuiteResultStatus(previous.status).alerting
                and previous.alerting_since_id is not None
            )
            alerting_since = previous.alerting_since_id if carried and previous else result.id
        if summary is None and message is not None:
            summary = EvalSuiteSummary(
                pass_rate=None, first_pass_rate=None, cases=0, message=message
            )
        await eval_suite_repo.update_result(
            self.db,
            result=result,
            values={
                "status": status.value,
                "reason": reason,
                "summary": None if summary is None else summary.model_dump(mode="json"),
                "settled_at": now,
                "alerting_since_id": alerting_since,
            },
        )
        suite = await eval_suite_repo.get(
            self.db, result.suite_id, organization_id=result.organization_id
        )
        assert suite is not None, "a result goes with its suite"
        if status is EvalSuiteResultStatus.PASSED and result.agent_version_id is not None:
            await self._follow(suite, result)
        if alerting_since is not None and alerting_since == result.id:
            from app.services.notifications import NotificationService

            agent = await agent_repo.get(
                self.db, suite.agent_id, organization_id=suite.organization_id
            )
            assert agent is not None, "a suite goes with its agent"
            await NotificationService(self.db).eval_suite_failed(suite, result, agent=agent)
            await eval_suite_repo.update_result(self.db, result=result, values={"notified_at": now})
        self._announce(suite)

    async def _follow(self, suite: EvalSuite, result: EvalSuiteResult) -> None:
        """Move the environments this pass lets through, apart from the pass.

        A promotion that fails here must not turn a real pass into an error: it
        rolls back alone, and the sweep's reconcile step tries it again.
        """
        from app.services.promotion_gate import PromotionGateService

        assert result.agent_version_id is not None, "a passed result checked a version"
        try:
            async with self.db.begin_nested():
                await PromotionGateService(self.db).follow(
                    organization_id=result.organization_id,
                    agent_id=suite.agent_id,
                    version_id=result.agent_version_id,
                )
        except Exception:
            logger.exception("promotion_gate_follow_failed", extra={"result_id": str(result.id)})

    async def reconcile_followers(self) -> int:
        """The sweep's look at guarded environments that follow publishes."""
        from app.services.promotion_gate import PromotionGateService

        return await PromotionGateService(self.db).reconcile()

    async def _pause_for_owner(self, result: EvalSuiteResult, *, reason: str) -> None:
        """Pause the suite when the member a result ran as is still its owner.

        A run somebody else started by hand says nothing about the owner.
        """
        suite = await eval_suite_repo.get(
            self.db, result.suite_id, organization_id=result.organization_id
        )
        assert suite is not None, "a result goes with its suite"
        if suite.is_active and suite.owner_user_id == result.run_as_user_id:
            await self._pause(suite, reason=reason)

    async def _pause(self, suite: EvalSuite, *, reason: str) -> None:
        """Stop a suite the platform can no longer run as its owner, saying why."""
        await eval_suite_repo.update(
            self.db, suite=suite, values={"is_active": False, "paused_reason": reason}
        )
        await eval_suite_repo.discard_pending(
            self.db, suite.id, organization_id=suite.organization_id
        )
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=suite.organization_id,
            action="eval_suite.disabled",
            target_type="agent",
            target_id=str(suite.agent_id),
            details={"suite_id": str(suite.id), "reason": reason},
        )

    async def _person(self, organization_id: UUID, user_id: UUID | None) -> AuthContext | None:
        """A member's authority as it is now, so a role changed since applies; None once
        they are no longer an active member."""
        membership = (
            None
            if user_id is None
            else await member_repo.get_active(
                self.db, organization_id=organization_id, user_id=user_id
            )
        )
        if user_id is None or membership is None:
            return None
        return AuthContext(
            user_id=user_id,
            organization_id=organization_id,
            role=membership.role,
            subject_is_publisher_fallback=True,
        )

    def _announce(self, suite: EvalSuite) -> None:
        """Tell open consoles the agent's suites changed, once this is committed.

        The event names the agent, as a routine's does: that is what a reader's
        access to its suites is decided by.
        """
        spawn_after_commit(
            self.db,
            change_feed.publish(
                ChangeEvent(
                    organization_id=suite.organization_id,
                    resource="eval_suite",
                    id=suite.agent_id,
                    action="updated",
                    surface="run",
                    actor_user_id=None,
                    actor_name=None,
                )
            ),
            name=f"eval-suite-announce:{suite.id}",
        )
