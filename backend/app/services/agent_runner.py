"""Running a published agent, and recording what it cost.

Every surface — the playground, a Slack mention, the public API — goes through
here. That is deliberate: if each surface assembled its own agent, budgets and
run history would hold whatever each one remembered to record, and the first
surface someone added in a hurry would be the one with no limits.

The service owns the run lifecycle:

    resolve version -> resolve model -> build -> execute -> record cost

The cost row is written in a ``finally`` block. A run that crashed still spent
money, and a budget that only counts successful runs is not a budget.

The same reasoning is why the *limits* are resolved here too, not handed in.
A run is under as many caps as apply to it — the agent's own, the
organization's, and the exposure that admitted it — and every one of them is a
:class:`~app.agents.capabilities.budget.SpendLimit` carrying the lookup that
meters *its* spend: ``agent.id`` for the agent, ``ctx.organization_id`` for the
organization, the run's ``exposure_id`` for the exposure. None of them is
collapsed into another, because the tighter of two numbers means nothing when
the numbers count different things; whichever binds first stops the run and
names itself. Adding a fourth is a lookup and an entry, not a new argument every
surface has to remember.

A run can also stop without an answer. When the approval gate parks a
side-effecting tool call, the run is recorded as ``awaiting_approval`` with
everything it needs to continue stored on the row, and :meth:`~AgentRunnerService.resume`
picks it up once a person has decided — in another process, possibly the next
day. Holding the coroutine open instead would cost a task and a connection per
pending decision, for however long the approver takes to look.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.approval import (
    ApprovalDecision,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
)
from app.agents.capabilities.budget import BudgetExceeded, SpendEntry, SpendLimit
from app.agents.deps import AgentDeps
from app.agents.factory import BuiltAgent, build_agent
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface
from app.repositories import (
    agent_exposure_repo,
    agent_repo,
    agent_run_repo,
    knowledge_base_repo,
)
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES, AgentRegistryService
from app.services.approvals import ApprovalService
from app.services.mcp_connection import build_toolsets_for_agent
from app.services.model_profile import ModelProfileService
from app.services.notifications import NotificationService
from app.services.organization import OrganizationService
from app.services.organization_secret import OrganizationSecretService
from app.services.skills import SkillService

logger = logging.getLogger(__name__)


def month_start(now: datetime | None = None) -> datetime:
    """The start of the current calendar month, in UTC.

    Monthly budgets reset on the first, not on a rolling 30 days: people reason
    about "this month's spend" against an invoice, and a rolling window makes
    the number impossible to reconcile.
    """
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class PausedRunState(BaseModel):
    """What a parked run needs to pick up where it stopped.

    Stored on the run rather than on the approval because it describes the
    *run's* position, and a single step can park several calls at once.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(
        description="The conversation as of the parked call, in Pydantic AI's message format"
    )
    tool_call_ids: dict[str, str] = Field(
        description="Approval id -> the tool call it parked, so a decision can be replayed"
    )


@dataclass
class ApprovalChannel:
    """A run's connection to the approval queue.

    Handed to the agent as ``AgentDeps.request_approval``: the gate asks, this
    answers. A first ask parks the call and returns pending; a resumed run is
    built with the recorded decisions already in hand.

    Decisions are consumed on use. If the model calls the same tool a second
    time after being approved once, that is a second act on the world and needs
    its own approval — reusing the first would let one "yes" authorise a loop.
    """

    approvals: ApprovalService
    organization_id: UUID
    agent_id: UUID
    run_id: UUID
    decided: dict[str, ApprovalDecision] = field(default_factory=dict)
    parked: dict[str, str] = field(default_factory=dict)

    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        decision = self.decided.pop(request.tool_call_id, None)
        if decision is not None:
            return decision

        approval = await self.approvals.request(
            organization_id=self.organization_id,
            run_id=self.run_id,
            agent_id=self.agent_id,
            # The tool the model called, not the capability that owns it: the
            # approver is looking at "send_email", not at "email".
            tool_id=request.tool_name,
            tool_args=request.tool_args,
        )
        self.parked[str(approval.id)] = request.tool_call_id
        return ApprovalPending()


@dataclass
class PreparedRun:
    """An agent ready to execute, with its run row already open.

    Returned rather than executed inline because surfaces stream differently: a
    WebSocket iterates events, a Slack handler awaits a final answer, the API
    may do either. They share the setup and the accounting, not the loop.
    """

    run: AgentRun
    agent: Agent
    spec: AgentSpec
    built: BuiltAgent
    approvals: ApprovalChannel

    @property
    def deps(self) -> AgentDeps:
        return self.built.deps


def _spend_already_booked(run: AgentRun) -> SpendEntry:
    """A resumed run's opening balance, as one ledger entry.

    A resumed run keeps its own row, so its ledger has to start with what the
    run already spent. Otherwise finishing it would overwrite the cost with only
    what the continuation cost, and the per-run budget would reset every time
    somebody approved something — which is exactly the run a budget is for.
    """
    return SpendEntry(
        model_name=run.model_label or "unknown",
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=run.cost_usd,
        priced=not run.cost_is_partial,
    )


class AgentRunnerService:
    """Prepare, execute and account for agent runs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.models = ModelProfileService(db)
        self.skills = SkillService(db)
        self.secrets = OrganizationSecretService(db)
        self.approvals = ApprovalService(db)
        self.organizations = OrganizationService(db)

    async def _collection_names(self, spec: AgentSpec, ctx: AuthContext) -> list[str]:
        """Vector-store collection names for the agent's bound collections.

        Resolved server-side and passed through deps: the model asks *what* to
        search, never *where*.
        """
        names: list[str] = []
        for collection_id in spec.collection_ids:
            collection = await knowledge_base_repo.get_by_id(self.db, collection_id)
            if collection is None or collection.organization_id != ctx.organization_id:
                # A collection deleted after publish degrades the agent's reach
                # rather than failing the run — the answer is worse, not absent.
                logger.warning(
                    "Agent references collection %s which is gone from org %s",
                    collection_id,
                    ctx.organization_id,
                )
                continue
            names.append(collection.collection_name)
        return names

    async def prepare(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        surface: RunSurface = RunSurface.PLAYGROUND,
        conversation_id: UUID | None = None,
        user_name: str | None = None,
        extra_toolsets: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        model_profile_id: UUID | None = None,
    ) -> PreparedRun:
        """Assemble everything a run needs and open its row.

        Args:
            exposure: The binding that admitted this run, when one did. It is
                stamped on the run row and its caps are enforced — so a run that
                arrived through a place the agent was published to is both
                attributable to that place and bounded by it.
            model_profile_id: Run on this model instead of the one the spec
                names. What an agent *does* — its instructions, its tools, its
                approval gates — is unchanged; only which model executes it is.
                The run row records the model that actually ran, so a cheaper or
                stronger model chosen for one conversation stays attributable
                and stays inside the same budget.

        Raises:
            BadRequestError: If the agent is unpublished, archived, or its spec
                no longer validates — surfaced before any tokens are spent.
        """
        agent, spec = await self.registry.get_runnable_spec(ctx, agent_id)
        return await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=None,
            surface=surface,
            conversation_id=conversation_id,
            model_profile_id=model_profile_id,
            user_name=user_name,
            extra_toolsets=extra_toolsets,
            exposure=exposure,
            decided={},
        )

    async def _exposure_for(self, run: AgentRun) -> AgentExposure | None:
        """The binding a parked run arrived through, if it is still there.

        A binding deleted while the run sat in the approvals queue leaves the
        continuation uncapped by it, which is the honest outcome: the ceiling
        belonged to a place that no longer exists. The run keeps its
        ``exposure_id`` regardless — ``SET NULL`` on the column is what a
        *deleted* binding does, and that is a different fact from this one.
        """
        if run.exposure_id is None:
            return None
        return await agent_exposure_repo.get(
            self.db, run.exposure_id, organization_id=run.organization_id
        )

    def _exposure_limits(
        self, exposure: AgentExposure | None, *, run_exposure_id: UUID | None
    ) -> list[SpendLimit]:
        """The caps the binding that admitted this run imposes.

        Metered against that binding's own runs and nobody else's, which is the
        whole point: an exposure's ceiling checked against the organization's
        total would be exhausted by unrelated internal traffic while the
        binding's own spend stayed invisible in it. ``run_exposure_id`` rather
        than ``exposure.id`` is what a resumed run is metered on — the run
        already carries the binding it arrived through, and re-deriving it from
        an argument the resume path does not have would silently meter the
        continuation against nothing.

        Both caps are separate entries rather than one composed number: they
        measure different quantities, so the tighter of the two is not a
        meaningful thing to compute, and each names itself when it stops a run.
        """
        if exposure is None or run_exposure_id is None:
            return []

        limits: list[SpendLimit] = []
        if exposure.max_per_run_usd is not None:
            limits.append(
                SpendLimit(scope="Exposure run", limit_usd=Decimal(exposure.max_per_run_usd))
            )
        if exposure.monthly_usd is not None:

            async def exposure_spend() -> Decimal:
                return await agent_run_repo.sum_cost_since(
                    self.db,
                    organization_id=exposure.organization_id,
                    since=month_start(),
                    exposure_id=run_exposure_id,
                )

            limits.append(
                SpendLimit(
                    scope="Exposure monthly",
                    limit_usd=Decimal(exposure.monthly_usd),
                    period_spend=exposure_spend,
                )
            )
        return limits

    async def _assemble(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        spec: AgentSpec,
        existing_run: AgentRun | None,
        surface: RunSurface,
        conversation_id: UUID | None,
        user_name: str | None,
        extra_toolsets: list[Any] | None,
        exposure: AgentExposure | None,
        decided: dict[str, ApprovalDecision],
        model_profile_id: UUID | None = None,
    ) -> PreparedRun:
        """Build the agent for a run, opening its row unless one is being resumed.

        The single funnel a fresh run and a resumed one share. Splitting them
        would mean two places that decide what an agent may reach, and the
        second one would eventually forget something.
        """
        # A caller's override wins over the spec's choice. Only the model is
        # replaced — instructions, tools, budgets and the approval gate are the
        # agent's, so this cannot be used to run something the agent is not.
        model_spec = await self.models.resolve(
            ctx, profile_id=model_profile_id or spec.model_profile_id
        )

        # The organization's ceiling is read here rather than passed in by the
        # surface, for the reason this module exists: a limit each caller has to
        # remember is a limit the next surface will not have. It used to be a
        # parameter with a default of "no cap" and no production caller, so
        # twelve agents in one organization meant twelve independent caps and no
        # ceiling. `ctx.organization_id` is also the only tenant in scope here,
        # which is what keeps the cap and the spend it is measured against — the
        # `period_spend` below — reading the same organization.
        organization = await self.organizations.get_by_id(ctx.organization_id)

        # Everything a capability needs but must not fetch itself. Resolved once,
        # server-side, so the model cannot influence what an agent reaches.
        resources = {
            "kb_collection_names": await self._collection_names(spec, ctx),
            "skills": await self.skills.resolve_for_agent(ctx, spec.skill_ids),
        }

        # Unsealed here and handed straight to the factory, which hands them to
        # the capability instances that declared them. They are kept out of
        # `resources` deliberately: a resource may end up in a log line and a
        # secret may not.
        # The observability token rides along with the capability secrets: it is
        # the same kind of reference, resolved at the same moment, and a second
        # unsealing pass would be a second place for a tenant check to be missed.
        secret_ids = [binding.secret_id for binding in spec.capabilities if binding.secret_id]
        if spec.observability and spec.observability.token_secret_id:
            secret_ids.append(spec.observability.token_secret_id)
        secrets = await self.secrets.resolve_for_bindings(ctx, secret_ids)

        # The MCP servers the spec binds, resolved here rather than by each
        # surface. A surface that forgot would produce an agent missing half its
        # tools with nothing to show for it, and the answer would differ between
        # the playground and Slack for no reason anybody could see.
        spec_toolsets = await build_toolsets_for_agent(
            self.db, organization_id=ctx.organization_id, connection_ids=spec.mcp_server_ids
        )

        run = existing_run
        if run is None:
            run = await agent_run_repo.create_run(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                agent_version_id=agent.current_version_id,
                user_id=ctx.user_id,
                conversation_id=conversation_id,
                exposure_id=exposure.id if exposure else None,
                surface=surface.value,
                model_label=model_spec.label,
                provider=model_spec.provider,
                secret_id=model_spec.secret_id,
                started_at=datetime.now(UTC),
            )

        # Two lookups, because the caps they feed meter two different things. The
        # agent's own cap used to read the organization-wide number below, which
        # made ``AgentSpec.budget.monthly_usd`` a second organization cap wearing
        # an agent's name: an agent with a $10 limit was refused once its
        # *neighbours* had spent $10, and nothing ever isolated its own spend.
        async def agent_period_spend() -> Decimal:
            return await self.monthly_spend(ctx, agent_id=agent.id)

        async def org_period_spend() -> Decimal:
            return await self.monthly_spend(ctx)

        channel = ApprovalChannel(
            approvals=self.approvals,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            run_id=run.id,
            decided=decided,
        )

        built = build_agent(
            spec,
            model_spec,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            run_id=run.id,
            # Not `str(ctx.user_id)`: a context with no subject would stringify
            # to the literal "None" and hand it to every tool as the caller's
            # id. `AgentDeps.user_id` is already optional precisely so a surface
            # without a person can say so, and "None" is the one answer that
            # looks like an answer.
            user_id=None if ctx.user_id is None else str(ctx.user_id),
            user_name=user_name,
            extra_limits=self._exposure_limits(exposure, run_exposure_id=run.exposure_id),
            granted_scopes=DEFAULT_GRANTED_SCOPES,
            resources=resources,
            secrets=secrets,
            extra_toolsets=[*(extra_toolsets or []), *spec_toolsets],
            agent_period_spend=agent_period_spend,
            org_period_spend=org_period_spend,
            org_monthly_budget_usd=organization.monthly_budget_usd,
            request_approval=channel,
        )

        return PreparedRun(run=run, agent=agent, spec=spec, built=built, approvals=channel)

    async def finish(
        self,
        prepared: PreparedRun,
        *,
        status: RunStatus,
        error: str | None = None,
        logfire_trace_id: str | None = None,
        paused_state: PausedRunState | None = None,
    ) -> AgentRun:
        """Record what the run consumed and how it ended.

        Called from a ``finally`` block by every surface: a crashed run still
        spent money, and a budget that ignores failures is not a budget.

        ``paused_state`` is what a parked run is resumed from. Passing nothing
        clears it, which is what makes a finished run un-resumable rather than
        replayable.
        """
        ledger = prepared.built.ledger
        finished = await agent_run_repo.finish_run(
            self.db,
            run=prepared.run,
            status=status.value,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
            cost_usd=ledger.total_usd,
            cost_is_partial=ledger.has_unpriced_models,
            ended_at=datetime.now(UTC),
            error=error,
            logfire_trace_id=logfire_trace_id,
            paused_state=paused_state.model_dump(mode="json") if paused_state else None,
        )
        # Guarded, because `finish` is called from a `finally` block: an
        # exception raised while telling somebody about a failed run would
        # replace the failure itself, and the operator would debug the mail
        # server instead of the run.
        try:
            await self._notify(finished, agent=prepared.agent, status=status, error=error)
        except Exception:
            logger.exception("run_notification_failed", extra={"run_id": str(finished.id)})
        return finished

    async def _notify(
        self, run: AgentRun, *, agent: Agent, status: RunStatus, error: str | None
    ) -> None:
        """Tell somebody, when the run ended in a way nobody is watching for.

        Here rather than at the two places that raise, because this is where
        every surface converges and where the fact is already durable: a person
        told about a budget breach that the transaction then rolled back would
        go looking for a run that does not exist.

        A chat user watching the stream is told twice — once on screen, once by
        email — and that is the right trade: the alternative is guessing from
        the surface whether anybody was looking, and being wrong in the
        direction of silence.
        """
        notifications = NotificationService(self.db)
        if status is RunStatus.BUDGET_EXCEEDED:
            await notifications.budget_exceeded(
                run, agent=agent, reason=error or "A spending limit was reached."
            )
        elif status is RunStatus.AWAITING_APPROVAL:
            approvals = await agent_run_repo.list_approvals_for_run(
                self.db, run_id=run.id, organization_id=run.organization_id
            )
            pending = [
                approval.tool_id
                for approval in approvals
                if approval.status == ApprovalStatus.PENDING.value
            ]
            await notifications.approval_requested(run, agent=agent, tools=pending)

    async def execute(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        *,
        surface: RunSurface = RunSurface.API,
        conversation_id: UUID | None = None,
        message_history: list[Any] | None = None,
        exposure: AgentExposure | None = None,
    ) -> tuple[str, AgentRun]:
        """Run an agent to completion and return its answer.

        The non-streaming path, used by the API and chat channels. Surfaces that
        stream call :meth:`prepare` and :meth:`finish` around their own loop.

        An empty answer with the run in ``awaiting_approval`` means a tool call
        is parked; the caller shows the queue rather than an answer.
        """
        prepared = await self.prepare(
            ctx,
            agent_id,
            surface=surface,
            conversation_id=conversation_id,
            exposure=exposure,
        )
        return await self._run(
            prepared,
            user_prompt=prompt,
            message_history=message_history,
            deferred_tool_results=None,
        )

    async def resume(self, ctx: AuthContext, run_id: UUID) -> tuple[str, AgentRun]:
        """Continue a parked run now that its tool calls have been decided.

        Runs the *version the run was parked on*, not whatever is published now:
        the stored conversation was produced by that spec, and continuing it
        under a different one would answer a question nobody asked.

        Raises:
            NotFoundError: If the run is not in this organization.
            BadRequestError: If the run is not parked, has no stored state, or
                still has a decision outstanding. All three mean the caller is
                about to replay something it should not.
        """
        run = await agent_run_repo.claim_parked_run(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        if run.status != RunStatus.AWAITING_APPROVAL.value:
            raise BadRequestError(
                message="This run is not waiting for approval",
                details={"run_id": str(run_id), "status": run.status},
            )
        if run.paused_state is None:
            raise BadRequestError(
                message="This run was parked without the state needed to continue it",
                details={"run_id": str(run_id)},
            )
        state = PausedRunState.model_validate(run.paused_state)

        decided, deferred = await self._decisions(ctx, run=run, state=state)
        # Out of the queue before anything is replayed: the row lock above only
        # holds until this transaction commits, and what makes a second resume
        # refuse afterwards is the status it finds.
        await agent_run_repo.mark_running(self.db, run=run)

        agent, spec = await self._parked_spec(ctx, run)
        prepared = await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=run,
            surface=RunSurface(run.surface),
            conversation_id=run.conversation_id,
            user_name=None,
            extra_toolsets=None,
            # Read back from the run rather than passed in: a resumed run is
            # under the same caps the original was, and the row is the only
            # place that still knows which binding admitted it. A continuation
            # metered against nothing is how one approval reopens a spent budget.
            exposure=await self._exposure_for(run),
            decided=decided,
        )
        prepared.built.ledger.entries.append(_spend_already_booked(run))

        return await self._run(
            prepared,
            # No new prompt: the conversation resumes at the tool call it stopped
            # on, and inventing a user turn here would put words in their mouth.
            user_prompt=None,
            message_history=ModelMessagesTypeAdapter.validate_python(state.messages),
            deferred_tool_results=deferred,
        )

    async def _decisions(
        self, ctx: AuthContext, *, run: AgentRun, state: PausedRunState
    ) -> tuple[dict[str, ApprovalDecision], DeferredToolResults]:
        """The verdicts on this run's parked calls, keyed by tool call.

        Raises:
            BadRequestError: If any of them is still pending. Resuming with a
                decision outstanding would drop that call silently.
        """
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=run.id, organization_id=ctx.organization_id
        )
        undecided = [a for a in approvals if a.status == ApprovalStatus.PENDING.value]
        if undecided:
            raise BadRequestError(
                message=f"{len(undecided)} tool call(s) on this run are still awaiting a decision",
                details={"run_id": str(run.id), "pending": [str(a.id) for a in undecided]},
            )

        decided: dict[str, ApprovalDecision] = {}
        deferred = DeferredToolResults()
        for approval in approvals:
            tool_call_id = state.tool_call_ids.get(str(approval.id))
            if tool_call_id is None:
                # Decided during an earlier park of the same run and already
                # replayed. Answering it again would repeat the side effect.
                continue
            decided[tool_call_id] = (
                ApprovalGranted(tool_args=approval.tool_args)
                if approval.status == ApprovalStatus.APPROVED.value
                else ApprovalRejected(note=approval.note)
            )
            # "Approved" here means "let this call reach the tool pipeline", not
            # "do it": the gate is the only place allowed to decide that, and it
            # reads the verdict above. Denying here instead would give refusals
            # two sources of truth.
            deferred.approvals[tool_call_id] = ToolApproved(override_args=approval.tool_args)
        return decided, deferred

    async def _parked_spec(self, ctx: AuthContext, run: AgentRun) -> tuple[Agent, AgentSpec]:
        """The agent and the exact spec version this run was executing.

        Raises:
            BadRequestError: If the version is gone. A run cannot be continued
                on a guess about what it was running.
        """
        agent = await self.registry.get(ctx, run.agent_id, perm=Perm.AGENTS_RUN)
        version = (
            None
            if run.agent_version_id is None
            else await agent_repo.get_version(
                self.db, run.agent_version_id, organization_id=ctx.organization_id
            )
        )
        if version is None:
            raise BadRequestError(
                message="The agent version this run was parked on no longer exists",
                details={"run_id": str(run.id)},
            )
        return agent, AgentSpec.model_validate(version.spec)

    async def _run(
        self,
        prepared: PreparedRun,
        *,
        user_prompt: str | None,
        message_history: list[Any] | None,
        deferred_tool_results: DeferredToolResults | None,
    ) -> tuple[str, AgentRun]:
        """Execute the agent and account for it, however it ends.

        The one place a run is executed, so a parked call, a budget stop and a
        crash are all recorded the same way whether the run is new or resumed.
        """
        status = RunStatus.FAILED
        error: str | None = None
        output = ""
        paused: PausedRunState | None = None
        try:
            result = await prepared.built.agent.run(
                user_prompt,
                deps=prepared.built.deps,
                message_history=message_history,
                deferred_tool_results=deferred_tool_results,
                usage_limits=prepared.built.usage_limits,
            )
            if isinstance(result.output, DeferredToolRequests):
                paused = PausedRunState(
                    messages=ModelMessagesTypeAdapter.dump_python(
                        result.all_messages(), mode="json"
                    ),
                    tool_call_ids=prepared.approvals.parked,
                )
                status = RunStatus.AWAITING_APPROVAL
                logger.info(
                    "Run %s parked on %d approval(s)", prepared.run.id, len(paused.tool_call_ids)
                )
            else:
                output = result.output
                status = RunStatus.COMPLETED
        except BudgetExceeded as exc:
            # Not a malfunction — the platform working. Recorded separately so
            # an operator filtering for problems does not wade through it.
            status = RunStatus.BUDGET_EXCEEDED
            error = str(exc)
            logger.info("Run %s stopped by budget: %s", prepared.run.id, exc)
        except Exception as exc:
            error = str(exc)
            logger.exception("Agent run %s failed", prepared.run.id)
            raise
        finally:
            await self.finish(prepared, status=status, error=error, paused_state=paused)

        return output, prepared.run

    async def monthly_spend(self, ctx: AuthContext, *, agent_id: UUID | None = None) -> Decimal:
        """Spend so far this calendar month, for the org or one agent."""
        return await agent_run_repo.sum_cost_since(
            self.db,
            organization_id=ctx.organization_id,
            since=month_start(),
            agent_id=agent_id,
        )

    async def spend_by_provider(
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[str | None, Decimal, int]]:
        """What each model provider was paid over a window."""
        return await agent_run_repo.spend_by_provider(
            self.db,
            organization_id=ctx.organization_id,
            since=datetime.now(UTC) - timedelta(days=days),
        )

    async def spend_by_key(
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[UUID | None, str | None, Decimal, int]]:
        """What each stored key was spent through over a window."""
        return await agent_run_repo.spend_by_key(
            self.db,
            organization_id=ctx.organization_id,
            since=datetime.now(UTC) - timedelta(days=days),
        )

    async def cost_breakdown(
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[UUID, str | None, Decimal, int]]:
        """Spend per agent and model over a window — the dashboard's data."""
        since = datetime.now(UTC) - timedelta(days=days)
        return await agent_run_repo.cost_breakdown(
            self.db, organization_id=ctx.organization_id, since=since
        )
