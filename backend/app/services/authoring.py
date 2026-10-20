"""The authoring assistant: asking it, reading what it proposed, and deciding.

A person starts an Improve or a Verify on an agent - or an Improve on a skill -
after seeing what it would read and cost; the work happens in the worker
(:mod:`app.services.authoring_worker`). What it proposes waits here for a person:
each hunk of an agent's batch is accepted into the draft, dismissed or undone on
its own, and a skill change is applied or discarded on the Skills page. Nothing
publishes and nothing changes an agent without that decision.

**Who may do what.** Starting one needs `runs:view` - the evidence is runs -
edit access to the target through its own grants, and use of the organization's
improver, which also refuses while AI assistance is switched off. Deciding needs
edit access to the agent and nothing more: a decision is not a model call, so it
stays possible with the switch off.

**A decision is one transaction with what it writes.** It locks the batch row
first, so a decision and a newer request superseding the batch serialize; then
it moves the hunk with a compare-and-set, so of two people deciding the same
hunk one wins; then it writes the draft. A failure anywhere leaves all three as
they were.

"Check with evals" runs a dataset against the draft as it would be with every
pending hunk accepted - a projection, never stored - and leaves out the cases
taken from the conversations the hunks were derived from.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.capabilities.skills import SkillBody
from app.agents.spec import AgentSpec
from app.agents.system_agents import IMPROVER
from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.authoring import (
    AuthoringKind,
    AuthoringRequest,
    AuthoringStatus,
    AuthoringTarget,
    BatchStatus,
    HunkKind,
    HunkStatus,
    SpecProposalBatch,
    SpecProposalHunk,
)
from app.db.models.eval_run import EvalRunPurpose
from app.db.models.skill_proposal import ProposalStatus
from app.repositories import agent_run_repo, authoring_repo, organization_repo, skill_proposal_repo
from app.schemas.authoring import (
    AgentAuthoringRead,
    AgentWaiting,
    AuthoringEstimate,
    AuthoringRequestRead,
    AuthoringStart,
    AuthoringWaiting,
    BatchRead,
    DecisionRead,
    EvidenceItemRead,
    HunkDecision,
    HunkRead,
    ProposalCheck,
)
from app.schemas.eval_run import EvalRunEstimate, EvalRunRead, EvalRunRequest
from app.services import authoring_hunks
from app.services.access import AGENT, accessible_ids
from app.services.agent_registry import AgentRegistryService
from app.services.authoring_evidence import EvidencePack, EvidenceService
from app.services.eval_run import EvalRunService
from app.services.model_profile import ModelProfileService
from app.services.skills import SkillService
from app.services.spend import month_start, organization_monthly_spend
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=20)
"""A request still marked running this long after it was last heard from has stopped."""

_OUTPUT_TOKENS = 1_500
_PROMPT_TOKENS = 1_500
_CHARS_PER_TOKEN = 4
_CENT = Decimal("0.0001")


class AuthoringService:
    """Start the assistant, read what it proposed, and decide on it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.skills = SkillService(db)
        self.runner = SystemAgentRunner(db)
        self.evidence = EvidenceService(db)
        self.models = ModelProfileService(db)

    async def _improver(self, ctx: AuthContext) -> Agent:
        """The improver, once it is known the caller may run it now.

        Raises:
            AiAssistanceDisabledError: The organization switched AI assistance off.
            SystemAgentUnavailableError: It cannot run for this caller.
        """
        return await self.runner.require_runnable(ctx, key=IMPROVER.key)

    @staticmethod
    def _require_runs_view(ctx: AuthContext) -> None:
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="The assistant reads runs, which needs runs:view",
                details={"permission": Perm.RUNS_VIEW.value},
            )

    async def _editable(self, ctx: AuthContext, agent_id: UUID) -> Agent:
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        if agent.status == AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is archived", details={"agent_id": agent.id}
            )
        return agent

    async def _published(self, ctx: AuthContext, agent: Agent) -> AgentSpec | None:
        if agent.current_version_id is None:
            return None
        version = await self.registry.get_version(ctx, agent.id, agent.current_version_id)
        return AgentSpec.model_validate(version.spec)

    async def estimate_agent(
        self, ctx: AuthContext, agent_id: UUID, body: AuthoringStart
    ) -> AuthoringEstimate:
        """What an Improve or Verify on this agent would read and cost."""
        self._require_runs_view(ctx)
        agent = await self._editable(ctx, agent_id)
        improver = await self._improver(ctx)
        if body.kind == AuthoringKind.VERIFY.value:
            published = await self._published(ctx, agent)
            if published is None or published == AgentSpec.model_validate(agent.draft_spec):
                return await self._estimate(ctx, improver, EvidencePack(), "no_draft_change")
        pack = await self.evidence.for_agent(ctx, agent.id, window_days=body.window_days)
        return await self._estimate(ctx, improver, pack, None if pack.runs else "no_evidence")

    async def estimate_skill(
        self, ctx: AuthContext, skill_id: UUID, body: AuthoringStart
    ) -> AuthoringEstimate:
        """What an Improve on this skill would read and cost."""
        self._require_runs_view(ctx)
        skill = await self.skills.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        if body.kind != AuthoringKind.IMPROVE.value:
            raise BadRequestError(
                message="A skill has no draft to verify; review its pending change instead",
                details={"kind": body.kind},
            )
        improver = await self._improver(ctx)
        pack = await self.evidence.for_skill(ctx, skill.name, window_days=body.window_days)
        return await self._estimate(ctx, improver, pack, None if pack.runs else "no_evidence")

    async def _estimate(
        self, ctx: AuthContext, improver: Agent, pack: EvidencePack, reason: str | None
    ) -> AuthoringEstimate:
        groups = pack.groups()
        calls = 0 if not groups else (1 if len(groups) == 1 else len(groups) + 1)
        evidence_chars = sum(len(run.render()) for run in pack.runs)
        per_call = await self._per_call(ctx, improver, evidence_chars // max(1, len(groups)))
        total = (per_call * calls).quantize(_CENT)
        improver_left = await self._improver_left(ctx, improver)
        org_left = await self._org_left(ctx)
        return AuthoringEstimate(
            runs=len(pack.runs),
            rated_down=sum(1 for run in pack.runs if run.rating < 0),
            calls=calls,
            estimate_usd=total,
            affordable=(improver_left is None or total <= improver_left)
            and (org_left is None or total <= org_left),
            reason=reason,
        )

    async def _per_call(self, ctx: AuthContext, improver: Agent, chars: int) -> Decimal:
        """One improver call: its recent average, or a call this size at its model's price."""
        average = await agent_run_repo.average_cost(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=improver.id,
            sample=settings.EVAL_ESTIMATE_SAMPLE,
        )
        if average is not None:
            return average
        published = await self._published(ctx, improver)
        if published is not None and published.model_profile_id is not None:
            model = await self.models.resolve(ctx, profile_id=published.model_profile_id)
            usage = RunUsage(
                input_tokens=chars // _CHARS_PER_TOKEN + _PROMPT_TOKENS,
                output_tokens=_OUTPUT_TOKENS,
            )
            priced = price_request(usage, model.model, model.provider)
            if priced is not None:
                return Decimal(priced)
        return settings.EVAL_FALLBACK_CASE_COST_USD

    async def _improver_left(self, ctx: AuthContext, improver: Agent) -> Decimal | None:
        published = await self._published(ctx, improver)
        cap = (
            None if published is None or published.budget is None else published.budget.monthly_usd
        )
        if cap is None:
            return None
        spent = await agent_run_repo.sum_cost_since(
            self.db, organization_id=ctx.organization_id, since=month_start(), agent_id=improver.id
        )
        return Decimal(str(cap)) - spent

    async def _org_left(self, ctx: AuthContext) -> Decimal | None:
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None or organization.monthly_budget_usd is None:
            return None
        spent = await organization_monthly_spend(self.db, ctx.organization_id)
        return organization.monthly_budget_usd - spent

    async def start_agent(
        self, ctx: AuthContext, agent_id: UUID, body: AuthoringStart
    ) -> AuthoringRequestRead:
        """Queue an Improve or Verify on an agent, after the same checks its estimate makes.

        Raises:
            BadRequestError: Nothing to read (`no_evidence`), or nothing to verify
                (`no_draft_change`).
            PaymentRequiredError: The estimate is more than the improver or the
                organization has left this month. Nothing is written.
        """
        estimate = await self.estimate_agent(ctx, agent_id, body)
        return await self._start(
            ctx,
            estimate,
            body,
            target=AuthoringTarget.AGENT,
            agent_id=agent_id,
            skill_id=None,
        )

    async def start_skill(
        self, ctx: AuthContext, skill_id: UUID, body: AuthoringStart
    ) -> AuthoringRequestRead:
        """Queue an Improve on a skill. Raises as :meth:`start_agent` does."""
        estimate = await self.estimate_skill(ctx, skill_id, body)
        return await self._start(
            ctx,
            estimate,
            body,
            target=AuthoringTarget.SKILL,
            agent_id=None,
            skill_id=skill_id,
        )

    async def _start(
        self,
        ctx: AuthContext,
        estimate: AuthoringEstimate,
        body: AuthoringStart,
        *,
        target: AuthoringTarget,
        agent_id: UUID | None,
        skill_id: UUID | None,
    ) -> AuthoringRequestRead:
        if estimate.reason == "no_draft_change":
            raise BadRequestError(
                message="The draft is the same as the published version: there is nothing to verify",
                details={"reason": estimate.reason},
            )
        if estimate.reason == "no_evidence":
            raise BadRequestError(
                message=(
                    "Nothing to learn from yet: no run in this window was rated or failed. "
                    "Widen the window, or come back once people have rated some answers."
                ),
                details={"reason": estimate.reason},
            )
        if not estimate.affordable:
            raise PaymentRequiredError(
                message=(
                    "The authoring assistant has too little budget left this month for this. "
                    "Raise its monthly budget on its agent page, or the organization's."
                ),
                details={"estimate_usd": str(estimate.estimate_usd)},
            )
        request = await authoring_repo.create_request(
            self.db,
            organization_id=ctx.organization_id,
            kind=body.kind,
            target=target.value,
            agent_id=agent_id,
            skill_id=skill_id,
            created_by_user_id=ctx.user_id,
            estimate_usd=estimate.estimate_usd,
            window_days=body.window_days,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=f"authoring.{body.kind}_requested",
            target_type=target.value,
            target_id=str(agent_id or skill_id),
            details={"request_id": str(request.id), "estimate_usd": str(estimate.estimate_usd)},
        )
        from app.worker.tasks.authoring_tasks import dispatch_authoring_request

        spawn_after_commit(
            self.db,
            dispatch_authoring_request(str(request.id), str(ctx.organization_id)),
            name=f"authoring:{request.id}",
        )
        return AuthoringRequestRead.model_validate(request)

    async def _settled(self, request: AuthoringRequest) -> AuthoringRequest:
        """The request, marked failed when the worker stopped without saying so."""
        if request.status not in (AuthoringStatus.QUEUED.value, AuthoringStatus.RUNNING.value):
            return request
        heard = request.heartbeat_at or request.started_at or request.created_at
        if datetime.now(UTC) - heard < STALE_AFTER:
            return request
        return await authoring_repo.update_request(
            self.db,
            request=request,
            values={
                "status": AuthoringStatus.FAILED.value,
                "error": "The assistant stopped without finishing. Try again.",
                "finished_at": datetime.now(UTC),
            },
        )

    async def for_agent(self, ctx: AuthContext, agent_id: UUID) -> AgentAuthoringRead:
        """The open batch - or the last one - and the newest requests, for the Builder."""
        agent = await self.registry.get(ctx, agent_id)
        return await self._read(ctx, agent)

    async def waiting(self, ctx: AuthContext) -> AuthoringWaiting:
        """The suggestions waiting on agents the caller may edit, for the dashboard."""
        rows = await authoring_repo.agents_with_pending(
            self.db, organization_id=ctx.organization_id
        )
        editable = await accessible_ids(
            self.db, ctx, [agent for agent, _ in rows], Perm.AGENTS_EDIT, resource_type=AGENT
        )
        skills = (
            await authoring_repo.count_pending_skill_proposals(
                self.db, organization_id=ctx.organization_id
            )
            if ctx.has(Perm.SKILLS_EDIT)
            else 0
        )
        return AuthoringWaiting(
            agents=[
                AgentWaiting(
                    agent_id=agent.id,
                    name=agent.name,
                    instructions=counts.get(HunkKind.INSTRUCTIONS.value, 0),
                    tools=counts.get(HunkKind.TOOL_OVERRIDE.value, 0),
                )
                for agent, counts in rows
                if agent.id in editable
            ],
            skills=skills,
        )

    async def for_skill(self, ctx: AuthContext, skill_id: UUID) -> list[AuthoringRequestRead]:
        """The newest requests on one skill, for its page."""
        skill = await self.skills.get(ctx, skill_id)
        return [
            AuthoringRequestRead.model_validate(await self._settled(request))
            for request in await authoring_repo.list_requests(
                self.db, organization_id=ctx.organization_id, skill_id=skill.id
            )
        ]

    async def _read(self, ctx: AuthContext, agent: Agent) -> AgentAuthoringRead:
        requests = [
            await self._settled(request)
            for request in await authoring_repo.list_requests(
                self.db, organization_id=ctx.organization_id, agent_id=agent.id
            )
        ]
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id
        ) or await authoring_repo.latest_batch(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id
        )
        verify = next(
            (
                request
                for request in requests
                if request.kind == AuthoringKind.VERIFY.value
                and request.status == AuthoringStatus.COMPLETED.value
            ),
            None,
        )
        return AgentAuthoringRead(
            batch=None if batch is None else await self._batch(ctx, agent, batch),
            latest=None if not requests else AuthoringRequestRead.model_validate(requests[0]),
            verify=None if verify is None else AuthoringRequestRead.model_validate(verify),
        )

    async def _batch(self, ctx: AuthContext, agent: Agent, batch: SpecProposalBatch) -> BatchRead:
        spec = AgentSpec.model_validate(agent.draft_spec)
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=batch.id
        )
        quotes = ctx.has(Perm.RUNS_VIEW)
        return BatchRead(
            id=batch.id,
            agent_id=batch.agent_id,
            status=batch.status,
            expected_effect=batch.expected_effect,
            request_id=batch.request_id,
            hunks=[self._hunk(spec, hunk, quotes=quotes) for hunk in hunks],
            check_eval_run_ids=list(batch.check_eval_run_ids),
            created_at=batch.created_at,
        )

    @staticmethod
    def _hunk(spec: AgentSpec, hunk: SpecProposalHunk, *, quotes: bool) -> HunkRead:
        """One hunk as a reader sees it - quotes only for a reader of runs."""
        return HunkRead(
            id=hunk.id,
            kind=hunk.kind,
            origin=hunk.origin,
            status=hunk.status,
            old_text=hunk.old_text,
            new_text=hunk.new_text,
            accepted_text=hunk.accepted_text,
            context_before=hunk.context_before,
            context_after=hunk.context_after,
            capability_id=hunk.capability_id,
            tool_id=hunk.tool_id,
            base_name=hunk.base_name,
            base_description=hunk.base_description,
            new_name=hunk.new_name,
            new_description=hunk.new_description,
            rationale=hunk.rationale,
            evidence=[
                EvidenceItemRead(
                    run_id=UUID(item["run_id"]), quote=item.get("quote") if quotes else None
                )
                for item in hunk.evidence
            ],
            evidence_dropped=hunk.evidence_dropped,
            applies=authoring_hunks.applies(spec, hunk),
            decided_at=hunk.decided_at,
        )

    async def _open_batch_of(
        self, ctx: AuthContext, agent: Agent, batch_id: UUID
    ) -> SpecProposalBatch:
        batch = await authoring_repo.get_batch(
            self.db, batch_id, organization_id=ctx.organization_id, lock=True
        )
        if batch is None or batch.agent_id != agent.id:
            raise NotFoundError(message="Suggestion not found", details={"batch_id": batch_id})
        if batch.status != BatchStatus.OPEN.value:
            raise ConcurrentChangeError(
                message=(
                    "These suggestions were replaced by a newer run, or the draft they were "
                    "for was published. Reload to see what is waiting now."
                ),
                details={"batch_id": batch.id, "status": batch.status},
            )
        return batch

    async def decide(
        self, ctx: AuthContext, agent_id: UUID, hunk_id: UUID, decision: HunkDecision
    ) -> DecisionRead:
        """Accept, dismiss or undo one hunk, and write the draft when that changes it.

        Raises:
            NotFoundError: No such hunk on this agent, or the caller may not edit it.
            ConcurrentChangeError: The batch closed, or somebody decided the hunk first.
            BadRequestError: The hunk is stale - its passage or the tool's override
                moved on - or Undo would reverse a later manual edit.
        """
        agent = await self._editable(ctx, agent_id)
        hunk = await authoring_repo.get_hunk(self.db, hunk_id, organization_id=ctx.organization_id)
        if hunk is None:
            raise NotFoundError(message="Suggestion not found", details={"hunk_id": hunk_id})
        await self._open_batch_of(ctx, agent, hunk.batch_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        written: AgentSpec | None = None
        if decision.action == "accept":
            written, values = self._accepted(spec, hunk, decision.text)
            moved = await self._move(ctx, hunk, HunkStatus.PENDING, HunkStatus.ACCEPTED, values)
        elif decision.action == "dismiss":
            moved = await self._move(ctx, hunk, HunkStatus.PENDING, HunkStatus.DISMISSED)
        elif hunk.status == HunkStatus.DISMISSED.value:
            moved = await self._move(ctx, hunk, HunkStatus.DISMISSED, HunkStatus.PENDING)
        elif hunk.status == HunkStatus.PENDING.value:
            raise BadRequestError(
                message="This suggestion has not been decided, so there is nothing to undo",
                details={"hunk_id": hunk.id},
            )
        else:
            written = self._undone(spec, hunk)
            moved = await self._move(
                ctx,
                hunk,
                HunkStatus.ACCEPTED,
                HunkStatus.PENDING,
                {"accepted_text": None, "accepted_override": None},
            )
        if written is not None:
            agent = await self.registry.save_draft(ctx, agent.id, written)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=f"authoring.suggestion_{decision.action}",
            target_type="agent",
            target_id=str(agent.id),
            details={"hunk_id": str(moved.id), "kind": moved.kind},
        )
        return DecisionRead(
            authoring=await self._read(ctx, agent), draft_spec=dict(agent.draft_spec)
        )

    @staticmethod
    def _stale() -> BadRequestError:
        return BadRequestError(
            message=(
                "This suggestion no longer fits the draft: the passage or setting it changes "
                "was edited since. Edit the draft by hand, or run the assistant again."
            ),
            details={"reason": "stale"},
        )

    def _accepted(
        self, spec: AgentSpec, hunk: SpecProposalHunk, text: str | None
    ) -> tuple[AgentSpec, dict[str, Any]]:
        if hunk.kind == HunkKind.TOOL_OVERRIDE.value:
            applied = authoring_hunks.apply_tool(spec, hunk)
            if applied is None:
                raise self._stale()
            return applied[0], {"accepted_override": applied[1]}
        replacement = hunk.new_text if text is None else text
        written = authoring_hunks.apply(spec, hunk, text=replacement)
        if written is None:
            raise self._stale()
        return written, {"accepted_text": replacement}

    def _undone(self, spec: AgentSpec, hunk: SpecProposalHunk) -> AgentSpec:
        if hunk.kind == HunkKind.TOOL_OVERRIDE.value:
            undone = authoring_hunks.undo_tool(spec, hunk)
        else:
            text = authoring_hunks.undo_text(spec.instructions, hunk)
            undone = None if text is None else spec.model_copy(update={"instructions": text})
        if undone is None:
            raise BadRequestError(
                message=(
                    "This was edited by hand after it was accepted, so undoing it would "
                    "throw that edit away. Change the draft by hand instead."
                ),
                details={"reason": "stale"},
            )
        return undone

    async def _move(
        self,
        ctx: AuthContext,
        hunk: SpecProposalHunk,
        expected: HunkStatus,
        status: HunkStatus,
        values: dict[str, Any] | None = None,
    ) -> SpecProposalHunk:
        moved = await authoring_repo.decide_hunk(
            self.db,
            organization_id=ctx.organization_id,
            hunk_id=hunk.id,
            expected=expected,
            status=status,
            decided_by=ctx.user_id,
            values=values,
        )
        if moved is None:
            raise ConcurrentChangeError(
                message="Somebody decided this suggestion a moment ago. Reload to see what they chose.",
                details={"hunk_id": hunk.id},
            )
        return moved

    async def dismiss_all(self, ctx: AuthContext, agent_id: UUID) -> AgentAuthoringRead:
        """Dismiss every pending hunk of the open batch."""
        agent = await self._editable(ctx, agent_id)
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id, lock=True
        )
        if batch is not None:
            for hunk in await authoring_repo.list_hunks(
                self.db, organization_id=ctx.organization_id, batch_id=batch.id
            ):
                if hunk.status == HunkStatus.PENDING.value:
                    await authoring_repo.decide_hunk(
                        self.db,
                        organization_id=ctx.organization_id,
                        hunk_id=hunk.id,
                        expected=HunkStatus.PENDING,
                        status=HunkStatus.DISMISSED,
                        decided_by=ctx.user_id,
                    )
        return await self._read(ctx, agent)

    async def _projection(
        self, ctx: AuthContext, agent_id: UUID
    ) -> tuple[Agent, SpecProposalBatch, AgentSpec]:
        agent = await self._editable(ctx, agent_id)
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id
        )
        hunks = (
            []
            if batch is None
            else await authoring_repo.list_hunks(
                self.db, organization_id=ctx.organization_id, batch_id=batch.id
            )
        )
        pending = [hunk for hunk in hunks if hunk.status == HunkStatus.PENDING.value]
        if batch is None or not pending:
            raise BadRequestError(
                message="No suggestion is waiting to be checked",
                details={"agent_id": agent.id},
            )
        projected, _ = authoring_hunks.projection(
            AgentSpec.model_validate(agent.draft_spec), pending
        )
        return agent, batch, projected

    @staticmethod
    def _check_request(body: ProposalCheck) -> EvalRunRequest:
        return EvalRunRequest(
            dataset_id=body.dataset_id,
            dataset_version=body.dataset_version,
            environment_id=body.environment_id,
            paired_baseline=True,
        )

    async def estimate_check(
        self, ctx: AuthContext, agent_id: UUID, body: ProposalCheck
    ) -> EvalRunEstimate:
        """What checking the pending suggestions against a dataset would cost."""
        agent, batch, projected = await self._projection(ctx, agent_id)
        return await EvalRunService(self.db).estimate(
            ctx,
            agent.id,
            self._check_request(body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=projected,
            exclude_conversations=batch.evidence_conversation_ids,
        )

    async def _skill_check(
        self, ctx: AuthContext, skill_id: UUID, body: ProposalCheck
    ) -> tuple[Agent, AgentSpec, dict[UUID, SkillBody], list[UUID]]:
        """The agent a skill change is checked on, its published spec, the body, and what to leave out.

        Raises:
            NotFoundError: No such pending change to this skill.
            BadRequestError: No agent named, or one that does not use the skill.
        """
        skill = await self.skills.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        proposal = (
            None
            if body.proposal_id is None
            else await skill_proposal_repo.get(
                self.db, body.proposal_id, organization_id=ctx.organization_id
            )
        )
        if (
            proposal is None
            or proposal.skill_id != skill.id
            or proposal.status != ProposalStatus.PENDING.value
        ):
            raise NotFoundError(
                message="No change to this skill is waiting", details={"skill_id": skill.id}
            )
        if body.agent_id is None:
            raise BadRequestError(
                message="Pick an agent that uses this skill to check the change on",
                details={"skill_id": skill.id},
            )
        agent = await self.registry.get(ctx, body.agent_id, perm=Perm.AGENTS_RUN)
        published = await self._published(ctx, agent)
        if published is None or skill.id not in published.skill_ids:
            raise BadRequestError(
                message=f"'{agent.name}' does not use '{skill.name}' in its published version",
                details={"agent_id": agent.id, "skill_id": skill.id},
            )
        request = (
            None
            if proposal.authoring_request_id is None
            else await authoring_repo.get_request(
                self.db, proposal.authoring_request_id, organization_id=ctx.organization_id
            )
        )
        evidence = [] if request is None else request.evidence.get("conversation_ids", [])
        bodies = {skill.id: SkillBody(description=proposal.description, content=proposal.content)}
        return agent, published, bodies, [UUID(str(conversation)) for conversation in evidence]

    async def estimate_skill_check(
        self, ctx: AuthContext, skill_id: UUID, body: ProposalCheck
    ) -> EvalRunEstimate:
        """What checking a pending skill change on one agent would cost."""
        agent, published, bodies, evidence = await self._skill_check(ctx, skill_id, body)
        return await EvalRunService(self.db).estimate(
            ctx,
            agent.id,
            self._check_request(body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=published,
            candidate_skills=bodies,
            exclude_conversations=evidence,
        )

    async def check_skill(
        self, ctx: AuthContext, skill_id: UUID, body: ProposalCheck
    ) -> EvalRunRead:
        """Run a dataset on an agent using the skill, with the proposed body in place of its own.

        The agent is held still - its published version on both sides - so the
        comparison measures the skill change alone. Applying the change is live
        for every agent bound to the skill, which is why it is checked before.
        """
        agent, published, bodies, evidence = await self._skill_check(ctx, skill_id, body)
        return await EvalRunService(self.db).start(
            ctx,
            agent.id,
            self._check_request(body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=published,
            candidate_skills=bodies,
            exclude_conversations=evidence,
        )

    async def check(self, ctx: AuthContext, agent_id: UUID, body: ProposalCheck) -> EvalRunRead:
        """Run a dataset against the draft as it would be with every pending suggestion.

        The baseline - the published version - runs beside it in the same run, and
        the cases taken from the suggestions' own evidence are left out. The draft
        does not change.
        """
        agent, batch, projected = await self._projection(ctx, agent_id)
        started = await EvalRunService(self.db).start(
            ctx,
            agent.id,
            self._check_request(body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=projected,
            exclude_conversations=batch.evidence_conversation_ids,
        )
        await authoring_repo.update_batch(
            self.db,
            batch=batch,
            values={"check_eval_run_ids": [*batch.check_eval_run_ids, started.id]},
        )
        return started
