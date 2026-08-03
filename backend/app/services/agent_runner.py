"""Running a published agent, and recording what it cost.

Every surface - the playground, a Slack mention, the public API - goes through
here. That is deliberate: if each surface assembled its own agent, budgets and
run history would hold whatever each one remembered to record, and the first
surface someone added in a hurry would be the one with no limits.

The service owns the run lifecycle:

    resolve version -> resolve model -> build -> execute -> record cost

The cost row is written in a `finally` block. A run that crashed still spent
money, and a budget that only counts successful runs is not a budget.

The same reasoning is why the *limits* are resolved here too, not handed in.
A run is under exactly two caps - the agent's own monthly limit and the
organization's - and each is a
:class:`~app.agents.capabilities.budget.SpendLimit` carrying the lookup that
meters *its* spend: `agent.id` for the agent, `ctx.organization_id` for the
organization. Neither is collapsed into the other, because the tighter of two
numbers means nothing when the numbers count different things; whichever binds
first stops the run and names itself.

A run can also stop without an answer. When the approval gate parks a
side-effecting tool call, the run is recorded as `awaiting_approval` with
everything it needs to continue stored on the row, and :meth:`~AgentRunnerService.resume`
picks it up once a person has decided - in another process, possibly the next
day. Holding the coroutine open instead would cost a task and a connection per
pending decision, for however long the approver takes to look.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
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
from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendEntry, metered_by
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE, WorkspaceIdentity
from app.agents.capabilities.sandbox._identity import SessionScope
from app.agents.deps import AgentDeps
from app.agents.factory import BuiltAgent, build_agent
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    agent_run_repo,
    knowledge_base_repo,
)
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES, AgentRegistryService
from app.services.approvals import ApprovalService
from app.services.attachments import AttachmentRouter
from app.services.channels.attachments import files_written, workspace_snapshot
from app.services.channels.base import OutgoingAttachment
from app.services.mcp_connection import build_toolsets_for_agent
from app.services.model_profile import ModelProfileService
from app.services.notifications import NotificationService
from app.services.organization import OrganizationService
from app.services.organization_secret import OrganizationSecretService
from app.services.sandbox_workspace import OpenWorkspace, SandboxWorkspaceService
from app.services.skill_proposal import SkillProposalService
from app.services.skill_workspace import MaterialisedSkills, collect_changes
from app.services.skill_workspace import materialise as materialise_skills
from app.services.skills import SkillService
from app.services.spend import month_start, organization_monthly_spend

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ParkedApproval:
    """One tool call waiting for a person.

    Carries the `approvals` row id rather than the model's `tool_call_id`: the
    decision is recorded against that row, and it is the row the approvals queue
    and the notification email point at. A surface that invented its own
    identifier would be a second way to approve the same call.
    """

    approval_id: UUID
    tool_call_id: str
    """The model's own id for the call, so a surface can resolve the card it drew
    for it. Carried beside the row id rather than instead of it: one addresses the
    decision, the other addresses what is on screen."""

    tool_name: str
    tool_args: dict[str, Any]


@dataclass
class ApprovalChannel:
    """A run's connection to the approval queue.

    Handed to the agent as `AgentDeps.request_approval`: the gate asks, this
    answers. A first ask parks the call and returns pending; a resumed run is
    built with the recorded decisions already in hand.

    Decisions are consumed on use. If the model calls the same tool a second
    time after being approved once, that is a second act on the world and needs
    its own approval - reusing the first would let one "yes" authorise a loop.
    """

    approvals: ApprovalService
    organization_id: UUID
    agent_id: UUID
    run_id: UUID
    decided: dict[str, ApprovalDecision] = field(default_factory=dict)
    parked: dict[str, str] = field(default_factory=dict)

    requested: list[ParkedApproval] = field(default_factory=list)
    """What was parked, in enough detail for a surface to put it to somebody.

    Kept here rather than read back from the rows afterwards, because this is where
    the row was created - re-reading it would be a query per parked call to recover
    what this object had in hand.
    """

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
        self.requested.append(
            ParkedApproval(
                approval_id=approval.id,
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                tool_args=request.tool_args,
            )
        )
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
    workspace: OpenWorkspace | None = None
    """The sandbox this run writes to, when its spec asks for one.

    Carried on the prepared run rather than hidden in the agent because it has
    to be *closed*: a `state` workspace is only stored by the flush in
    :meth:`AgentRunnerService.finish`, and nothing else in the process knows the
    run is over.
    """

    materialised_skills: MaterialisedSkills | None = None
    """The skill files written into that workspace, as they were written.

    Kept so that `finish` can tell what the agent changed from what it was given.
    Diffing against the database instead would re-propose every change a reviewer
    already discarded, on every turn of a conversation whose workspace outlives
    the run.
    """

    workspace_at_start: set[str] = field(default_factory=set)
    """Every path the workspace held before the turn ran.

    What the turn *added* is the difference against this. Compared against a
    snapshot rather than modification times: a `state` workspace has none, and a
    container's clock is not ours to trust.
    """

    outbound: list[OutgoingAttachment] = field(default_factory=list)
    """Files the turn produced, read in `finish` before the workspace closes.

    Filled there rather than returned by the run, because a `run`-scoped workspace
    is released by `close` and a caller reading it afterwards would find nothing.
    """

    outbound_refused: list[str] = field(default_factory=list)
    """Produced files a reply cannot carry - too large, or past the per-reply cap.

    Named rather than dropped: an agent told its file was delivered will tell the
    user the same.
    """

    ctx: AuthContext | None = None
    """Who ran it, for recording a proposal in `finish`.

    A workspace flush needs no tenant - it writes a row it already holds - but a
    proposal does: it is stored against an organization and read by a reviewer
    there. Carried rather than re-derived, because `finish` is called from a
    `finally` where the request may already be gone.
    """

    @property
    def deps(self) -> AgentDeps:
        return self.built.deps


def _spend_already_booked(run: AgentRun) -> SpendEntry:
    """A resumed run's opening balance, as one ledger entry.

    A resumed run keeps its own row, so its ledger has to start with what the
    run already spent. Otherwise finishing it would overwrite the cost with only
    what the continuation cost, and the per-run budget would reset every time
    somebody approved something - which is exactly the run a budget is for.
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
        self.workspaces = SandboxWorkspaceService(db)
        self.proposals = SkillProposalService(db)

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
                # rather than failing the run - the answer is worse, not absent.
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
        channel_key: str | None = None,
        user_name: str | None = None,
        extra_toolsets: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        model_profile_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> PreparedRun:
        """Assemble everything a run needs and open its row.

        Args:
            exposure: The binding that admitted this run, when one did. It is
                stamped on the run row and its caps are enforced - so a run that
                arrived through a place the agent was published to is both
                attributable to that place and bounded by it.
            model_profile_id: Run on this model instead of the one the spec
                names. What an agent *does* - its instructions, its tools, its
                approval gates - is unchanged; only which model executes it is.
                The run row records the model that actually ran, so a cheaper or
                stronger model chosen for one conversation stays attributable
                and stays inside the same budget.
            environment_id: Run the version this environment pins instead of
                the default. Falls back to the exposure's environment - a bot
                bound to `dev` serves dev without every caller re-deriving it -
                and then to the default environment's version.

        Raises:
            BadRequestError: If the agent is unpublished, archived, or its spec
                no longer validates - surfaced before any tokens are spent.
        """
        effective_environment_id = environment_id or (
            exposure.environment_id if exposure is not None else None
        )
        agent, spec, version_id = await self.registry.get_runnable_spec(
            ctx, agent_id, environment_id=effective_environment_id
        )
        spec = await self._with_environment_observability(
            ctx, spec, environment_id=effective_environment_id
        )
        return await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=None,
            surface=surface,
            conversation_id=conversation_id,
            channel_key=channel_key,
            model_profile_id=model_profile_id,
            user_name=user_name,
            extra_toolsets=extra_toolsets,
            exposure=exposure,
            decided={},
            version_id=version_id,
            environment_id=effective_environment_id,
        )

    async def _assemble(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        spec: AgentSpec,
        existing_run: AgentRun | None,
        surface: RunSurface,
        conversation_id: UUID | None,
        channel_key: str | None = None,
        user_name: str | None,
        extra_toolsets: list[Any] | None,
        exposure: AgentExposure | None,
        decided: dict[str, ApprovalDecision],
        model_profile_id: UUID | None = None,
        version_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> PreparedRun:
        """Build the agent for a run, opening its row unless one is being resumed.

        The single funnel a fresh run and a resumed one share. Splitting them
        would mean two places that decide what an agent may reach, and the
        second one would eventually forget something.

        `version_id` is the version the spec was resolved from - stamped on a
        fresh run so history records what actually answered, which an
        environment can make different from `current_version_id`. A resumed
        run keeps the version it was parked on.
        """
        # A caller's override wins over the spec's choice. Only the model is
        # replaced - instructions, tools, budgets and the approval gate are the
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
        # which is what keeps the cap and the spend it is measured against - the
        # `period_spend` below - reading the same organization.
        organization = await self.organizations.get_by_id(ctx.organization_id)

        # Everything a capability needs but must not fetch itself. Resolved once,
        # server-side, so the model cannot influence what an agent reaches.
        resources: dict[str, Any] = {
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
                agent_version_id=version_id or agent.current_version_id,
                user_id=ctx.user_id,
                conversation_id=conversation_id,
                environment_id=environment_id,
                exposure_id=exposure.id if exposure else None,
                surface=surface.value,
                model_label=model_spec.label,
                provider=model_spec.provider,
                secret_id=model_spec.secret_id,
                started_at=datetime.now(UTC),
            )

        # Two lookups, because the caps they feed meter two different things. The
        # agent's own cap used to read the organization-wide number below, which
        # made `AgentSpec.budget.monthly_usd` a second organization cap wearing
        # an agent's name: an agent with a $10 limit was refused once its
        # *neighbours* had spent $10, and nothing ever isolated its own spend.
        async def agent_period_spend() -> Decimal:
            return await self.monthly_spend(ctx, agent_id=agent.id)

        async def org_period_spend() -> Decimal:
            return await self.monthly_spend(ctx)

        # Opened after the run row, because a run-scoped workspace keys on it,
        # and before the agent, because the capability reads the backend out of
        # `resources`. Nothing starts here for a container-backed one: the
        # client opens its session on the first tool call, so an agent granted a
        # workspace it never touches costs nothing.
        workspace = await self.workspaces.open(
            spec,
            ctx=ctx,
            identity=WorkspaceIdentity(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                run_id=run.id,
                conversation_id=conversation_id,
                user_id=None if ctx.user_id is None else str(ctx.user_id),
                channel_key=channel_key,
            ),
            # What the binding that admitted this run says, if it says anything.
            # The same agent in web chat and on a Slack bot is one agent in two
            # situations, and one value for both was the wrong shape.
            scope_override=(
                cast("SessionScope | None", exposure.session_scope)
                if exposure is not None and exposure.session_scope
                else None
            ),
        )
        materialised: MaterialisedSkills | None = None
        started_with: set[str] = set()
        if workspace is not None:
            resources[WORKSPACE_BACKEND_RESOURCE] = workspace.backend
            # Skills as files, beside the shell that can run them. A skill whose
            # resource is a script was previously handed to the model as text it
            # could quote and not execute, while the same agent had `execute` one
            # tool call away.
            materialised = materialise_skills(workspace.backend, resources["skills"])
            # After the skills are written, so materialising them does not read as
            # the turn's own output.
            started_with = workspace_snapshot(workspace.backend)

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
            granted_scopes=DEFAULT_GRANTED_SCOPES,
            resources=resources,
            secrets=secrets,
            extra_toolsets=[*(extra_toolsets or []), *spec_toolsets],
            agent_period_spend=agent_period_spend,
            org_period_spend=org_period_spend,
            org_monthly_budget_usd=organization.monthly_budget_usd,
            request_approval=channel,
        )

        return PreparedRun(
            run=run,
            agent=agent,
            spec=spec,
            built=built,
            approvals=channel,
            workspace=workspace,
            materialised_skills=materialised,
            workspace_at_start=started_with,
            ctx=ctx,
        )

    @staticmethod
    def _collect_outbound(prepared: PreparedRun) -> None:
        """Read what the turn wrote, for a surface that can deliver it.

        Read for every run rather than only for the channels that use it, because
        the alternative is a flag threaded from three surfaces into `prepare` to
        decide whether a glob happens - and a glob of a workspace the process is
        already holding is cheaper than that plumbing. A surface with nowhere to
        put a file simply ignores the list.
        """
        if prepared.workspace is None:
            return
        delivered = files_written(prepared.workspace.backend, prepared.workspace_at_start)
        prepared.outbound.extend(delivered.attachments)
        prepared.outbound_refused.extend(delivered.refused)

    async def _propose_skill_changes(self, prepared: PreparedRun) -> None:
        """Record what this run wrote to its skills, as something a person decides.

        Never raises. It is called from the same `finally` that records what the
        run cost, so a failure here - a name taken since, a workspace that cannot
        be listed - must not replace whatever actually happened to the run.

        The change is not applied. A skill is instructions every agent bound to it
        follows on every run, so an agent that could edit one directly could
        rewrite what another agent does, inside a conversation nobody is
        reviewing. `app/db/models/skill_proposal.py` has the rest of the
        reasoning.
        """
        workspace = prepared.workspace
        state = prepared.materialised_skills
        if workspace is None or state is None or prepared.ctx is None:
            return
        try:
            changes = collect_changes(workspace.backend, state)
            if changes:
                await self.proposals.record(
                    prepared.ctx,
                    changes,
                    agent_id=prepared.agent.id,
                    conversation_id=prepared.run.conversation_id,
                )
        except Exception:
            logger.exception("skill_proposal_record_failed", extra={"run_id": str(prepared.run.id)})

    async def finish(
        self,
        prepared: PreparedRun,
        *,
        status: RunStatus,
        error: str | None = None,
        logfire_trace_id: str | None = None,
        paused_state: PausedRunState | None = None,
        budget_scope: BudgetScope | None = None,
    ) -> AgentRun:
        """Record what the run consumed and how it ended.

        Called from a `finally` block by every surface: a crashed run still
        spent money, and a budget that ignores failures is not a budget.

        `paused_state` is what a parked run is resumed from. Passing nothing
        clears it, which is what makes a finished run un-resumable rather than
        replayable.

        `budget_scope` names which cap bound, for a `BUDGET_EXCEEDED` status. It
        is carried from the `except` clause that caught the refusal rather than
        re-derived here, because the alternative is matching a prefix on the
        error message - and it decides who gets mailed: an agent's cap is its
        author's to raise, the organization's is not.
        """
        # Both before the workspace closes, because a run-scoped one is released
        # by `close` and its files are gone afterwards.
        self._collect_outbound(prepared)
        await self._propose_skill_changes(prepared)

        # Before the run row is written, so a workspace flush that fails cannot
        # leave the run un-finished, and after the run has certainly stopped
        # using it. `close` never raises; it logs.
        await self.workspaces.close(prepared.workspace)

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
            await self._notify(
                finished,
                agent=prepared.agent,
                spec=prepared.spec,
                status=status,
                error=error,
                budget_scope=budget_scope,
            )
        except Exception:
            logger.exception("run_notification_failed", extra={"run_id": str(finished.id)})
        return finished

    async def _notify(
        self,
        run: AgentRun,
        *,
        agent: Agent,
        spec: AgentSpec,
        status: RunStatus,
        error: str | None,
        budget_scope: BudgetScope | None,
    ) -> None:
        """Tell somebody, when the run ended in a way nobody is watching for.

        Here rather than at the two places that raise, because this is where
        every surface converges and where the fact is already durable: a person
        told about a budget breach that the transaction then rolled back would
        go looking for a run that does not exist.

        A chat user watching the stream is told twice - once on screen, once by
        email - and that is the right trade: the alternative is guessing from
        the surface whether anybody was looking, and being wrong in the
        direction of silence.
        """
        notifications = NotificationService(self.db)
        if status is RunStatus.BUDGET_EXCEEDED:
            await notifications.budget_exceeded(
                run,
                agent=agent,
                spec=spec,
                reason=error or "A spending limit was reached.",
                # An agent's own cap unless the refusal said otherwise. A
                # `BUDGET_EXCEEDED` row with no scope recorded predates this
                # being carried, and the agent's audience is the narrower of the
                # two - so an unknown scope tells fewer people rather than
                # mailing the whole administration about somebody's draft.
                scope=budget_scope or BudgetScope.AGENT,
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
            await notifications.approval_requested(run, agent=agent, spec=spec, tools=pending)

    async def execute(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        *,
        surface: RunSurface = RunSurface.API,
        conversation_id: UUID | None = None,
        channel_key: str | None = None,
        message_history: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        environment_id: UUID | None = None,
        attachments: list[ChatFile] | None = None,
        outbound: list[OutgoingAttachment] | None = None,
        outbound_refused: list[str] | None = None,
    ) -> tuple[str, AgentRun]:
        """Run an agent to completion and return its answer.

        The non-streaming path, used by the API and chat channels. Surfaces that
        stream call :meth:`prepare` and :meth:`finish` around their own loop.

        `environment_id` runs the version that environment pins - the API's way
        of exercising a dev environment before promoting it.

        `attachments` are files that arrived with the message. They are routed
        here rather than by the caller because where an attachment *goes* depends
        on whether the agent has a workspace, and only `prepare` knows that - the
        same reason the streaming path routes them after preparing rather than
        before.

        `outbound` and `outbound_refused` are filled with what the agent produced
        and what a reply cannot carry. Lists the caller passes in rather than a
        third return value: the workspace is closed before this returns - a
        run-scoped one is released outright - so a caller cannot read it
        afterwards, and every other caller of this method would have to unpack a
        tuple it has no use for.

        An empty answer with the run in `awaiting_approval` means a tool call
        is parked; the caller shows the queue rather than an answer.
        """
        prepared = await self.prepare(
            ctx,
            agent_id,
            surface=surface,
            conversation_id=conversation_id,
            channel_key=channel_key,
            exposure=exposure,
            environment_id=environment_id,
        )
        # `str | list[Any]`, not `str`: an attached image is folded in as
        # `BinaryContent` beside the text, and narrowing that back to a string
        # would hand the model a path where it should have been handed a picture.
        assembled: str | list[Any] = prompt
        if attachments:
            assembled = await AttachmentRouter(
                prepared.workspace.backend if prepared.workspace is not None else None
            ).build_prompt(prompt, attachments)
        answered = await self._run(
            prepared,
            user_prompt=assembled,
            message_history=message_history,
            deferred_tool_results=None,
        )
        if outbound is not None:
            outbound.extend(prepared.outbound)
        if outbound_refused is not None:
            outbound_refused.extend(prepared.outbound_refused)
        return answered

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
        # The continuation traces where the original did: the environment that
        # routed the run still owns its observability.
        spec = await self._with_environment_observability(
            ctx, spec, environment_id=run.environment_id
        )
        prepared = await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=run,
            surface=RunSurface(run.surface),
            conversation_id=run.conversation_id,
            user_name=None,
            extra_toolsets=None,
            # A resumed run reuses its row, and the binding that admitted it was
            # stamped on that row when it was opened - there is nothing left for
            # the exposure to contribute here.
            exposure=None,
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

    async def _with_environment_observability(
        self, ctx: AuthContext, spec: AgentSpec, *, environment_id: UUID | None
    ) -> AgentSpec:
        """The spec, with the environment's tracing choices folded in.

        An environment can point its runs at their own Logfire project - the
        client's production traces in the client's project, dev noise in the
        operator's. The token and service name fall through to the spec's own
        block field by field; the Logfire environment tag is always the
        environment's *name*, never configured separately, so the tag and the
        environment cannot disagree. A run with no token from either source
        stays untraced rather than tagged into nowhere.
        """
        if environment_id is None:
            return spec
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None:
            return spec
        base = spec.observability
        token_secret_id = environment.logfire_token_secret_id or (
            base.token_secret_id if base else None
        )
        if token_secret_id is None:
            return spec
        merged = ObservabilitySpec(
            token_secret_id=token_secret_id,
            service_name=environment.service_name or (base.service_name if base else None),
            environment=environment.name,
        )
        return spec.model_copy(update={"observability": merged})

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
        user_prompt: str | list[Any] | None,
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
        budget_scope: BudgetScope | None = None
        try:
            # `metered_by` books what the request wrapper cannot see - the
            # embedding calls a knowledge search makes - to this run's ledger,
            # so they land in `cost_usd` next to the model requests.
            with metered_by(prepared.built.ledger):
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
            # Not a malfunction - the platform working. Recorded separately so
            # an operator filtering for problems does not wade through it.
            status = RunStatus.BUDGET_EXCEEDED
            error = str(exc)
            budget_scope = exc.scope
            logger.info("Run %s stopped by budget: %s", prepared.run.id, exc)
        except Exception as exc:
            error = str(exc)
            logger.exception("Agent run %s failed", prepared.run.id)
            raise
        finally:
            await self.finish(
                prepared,
                status=status,
                error=error,
                paused_state=paused,
                budget_scope=budget_scope,
            )

        return output, prepared.run

    async def monthly_spend(self, ctx: AuthContext, *, agent_id: UUID | None = None) -> Decimal:
        """Spend so far this calendar month, for the org or one agent.

        The organization's number includes what ingestion spent on embeddings,
        because that is money too and the organization's cap is a cap on the
        bill, not on one kind of line item. The agent's number does not:
        indexing a shared knowledge base is nobody's agent's spend.
        """
        if agent_id is not None:
            return await agent_run_repo.sum_cost_since(
                self.db,
                organization_id=ctx.organization_id,
                since=month_start(),
                agent_id=agent_id,
            )
        return await organization_monthly_spend(self.db, ctx.organization_id)

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
        """Spend per agent and model over a window - the dashboard's data."""
        since = datetime.now(UTC) - timedelta(days=days)
        return await agent_run_repo.cost_breakdown(
            self.db, organization_id=ctx.organization_id, since=since
        )
