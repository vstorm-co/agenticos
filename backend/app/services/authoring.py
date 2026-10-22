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

**A decision is one transaction with what it writes.** It locks the agent row
and reads its draft afresh, so two decisions on one draft serialize instead of
the second writing over the first; then it locks the batch row, so a decision
and a newer request superseding the batch serialize; then it moves the hunk
with a compare-and-set, so of two people deciding the same hunk one wins; then
it writes the draft. A failure anywhere leaves all of it as it was.

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
from app.agents.capabilities.context import ContextBody
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
from app.db.models.eval_run import ArmRole, EvalRunPurpose, EvalRunStatus
from app.db.models.skill_proposal import ProposalStatus
from app.repositories import (
    agent_repo,
    agent_run_repo,
    authoring_repo,
    context_proposal_repo,
    eval_run_repo,
    organization_repo,
    skill_proposal_repo,
)
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
from app.schemas.eval_threshold import EvalSuiteCheck
from app.services import authoring_fields, authoring_hunks
from app.services.access import AGENT, accessible_ids
from app.services.agent_registry import AgentRegistryService
from app.services.authoring_config import ConfigurationService
from app.services.authoring_evidence import EvidencePack, EvidenceService
from app.services.context import ContextService
from app.services.eval_run import EvalRunService
from app.services.eval_suite import EvalSuiteService
from app.services.model_profile import ModelProfileService
from app.services.skills import SkillService
from app.services.spend import month_start, organization_monthly_spend
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=20)
"""A request still marked running this long after it was last heard from has stopped."""

QUEUED_STALE_AFTER = timedelta(hours=24)
"""A request still waiting this long for a worker was lost rather than delayed.

Far longer than :data:`STALE_AFTER`: a queue backed up behind long eval runs is
slow, not broken, and a request it has not reached yet is still going to run.
"""

_OUTPUT_TOKENS = 1_500
_PROMPT_TOKENS = 1_500
_CHARS_PER_TOKEN = 4
_CENT = Decimal("0.0001")


_EDITABLE = frozenset(
    {
        "description",
        "max_steps",
        "model_settings/temperature",
        "model_settings/top_p",
        "model_settings/max_tokens",
        "model_settings/timeout",
        "model_settings/parallel_tool_calls",
    }
)
"""The field changes whose value a person may edit before accepting, besides descriptions."""

_STANDING_REFUSALS = {
    "not_a_target": (
        "This suggestion changes something the assistant may not propose. Make that change "
        "in the Builder, or dismiss it."
    ),
    "weakens_protection": (
        "This suggestion removes or reconfigures a safeguard, which the assistant may not "
        "propose. Change safeguards in the Builder, or dismiss it."
    ),
}

_GATE_MESSAGES = {
    "check_first": (
        "A change of model is accepted once it has paid off: run Check with evals on "
        "these suggestions first, and accept it when the check shows no confirmed regression."
    ),
    "inconclusive": (
        "The last check of this model decided nothing - some answers went ungraded or "
        "there was no verdict. Grade them or run the check again before accepting."
    ),
    "regression": (
        "The last check of this model broke cases it used to pass. Fix the suggestions "
        "or dismiss the change of model."
    ),
}


def _changes_model(hunk: SpecProposalHunk) -> bool:
    return hunk.kind == HunkKind.SPEC_FIELD.value and hunk.path == "model_profile_id"


def _refers_to(hunk: SpecProposalHunk, key: str) -> bool:
    """Whether a name belongs on this hunk's card."""
    if hunk.kind != HunkKind.SPEC_FIELD.value:
        return False
    values = [hunk.base_value, hunk.new_value]
    if hunk.path == "capabilities":
        return any(
            (value.get("id") if isinstance(value, dict) else value) == key for value in values
        )
    return any(str(value) == key for value in values) or key in (hunk.path or "")


class AuthoringService:
    """Start the assistant, read what it proposed, and decide on it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.skills = SkillService(db)
        self.contexts = ContextService(db)
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

    async def estimate_context(
        self, ctx: AuthContext, context_id: UUID, body: AuthoringStart
    ) -> AuthoringEstimate:
        """What an Improve on this context file would read and cost."""
        self._require_runs_view(ctx)
        file = await self.contexts.get(ctx, context_id, perm=Perm.CONTEXT_EDIT)
        if body.kind != AuthoringKind.IMPROVE.value:
            raise BadRequestError(
                message="A context file has no draft to verify; review its pending change instead",
                details={"kind": body.kind},
            )
        improver = await self._improver(ctx)
        pack = await self.evidence.for_context(ctx, file.id, window_days=body.window_days)
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

    async def start_context(
        self, ctx: AuthContext, context_id: UUID, body: AuthoringStart
    ) -> AuthoringRequestRead:
        """Queue an Improve on a context file. Raises as :meth:`start_agent` does."""
        estimate = await self.estimate_context(ctx, context_id, body)
        return await self._start(
            ctx,
            estimate,
            body,
            target=AuthoringTarget.CONTEXT,
            agent_id=None,
            skill_id=None,
            context_id=context_id,
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
        context_id: UUID | None = None,
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
            context_id=context_id,
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
            target_id=str(agent_id or skill_id or context_id),
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
        if request.status == AuthoringStatus.QUEUED.value:
            heard, after = request.created_at, QUEUED_STALE_AFTER
        else:
            heard = request.heartbeat_at or request.started_at or request.created_at
            after = STALE_AFTER
        if datetime.now(UTC) - heard < after:
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
        contexts = (
            await context_proposal_repo.count_pending(self.db, organization_id=ctx.organization_id)
            if ctx.has(Perm.CONTEXT_EDIT)
            else 0
        )
        return AuthoringWaiting(
            agents=[
                AgentWaiting(
                    agent_id=agent.id,
                    name=agent.name,
                    instructions=counts.get(HunkKind.INSTRUCTIONS.value, 0),
                    tools=counts.get(HunkKind.TOOL_OVERRIDE.value, 0),
                    fields=counts.get(HunkKind.SPEC_FIELD.value, 0),
                )
                for agent, counts in rows
                if agent.id in editable
            ],
            skills=skills,
            contexts=contexts,
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

    async def for_context(self, ctx: AuthContext, context_id: UUID) -> list[AuthoringRequestRead]:
        """The newest requests on one context file, for its page."""
        file = await self.contexts.get(ctx, context_id)
        return [
            AuthoringRequestRead.model_validate(await self._settled(request))
            for request in await authoring_repo.list_requests(
                self.db, organization_id=ctx.organization_id, context_id=file.id
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
        quotes = ctx.has(Perm.RUNS_VIEW)
        return AgentAuthoringRead(
            batch=None if batch is None else await self._batch(ctx, agent, batch),
            latest=None if not requests else self._request(requests[0], quotes=quotes),
            verify=None if verify is None else self._request(verify, quotes=quotes),
        )

    @staticmethod
    def _request(request: AuthoringRequest, *, quotes: bool) -> AuthoringRequestRead:
        """A request as a reader sees it - a verify's quotes only for a reader of runs."""
        read = AuthoringRequestRead.model_validate(request)
        findings = None if read.report is None else read.report.get("findings")
        if quotes or read.report is None or not isinstance(findings, list):
            return read
        redacted = [
            {
                **finding,
                "evidence": [{"run_id": item["run_id"]} for item in finding.get("evidence", [])],
            }
            for finding in findings
        ]
        return read.model_copy(update={"report": {**read.report, "findings": redacted}})

    async def _batch(self, ctx: AuthContext, agent: Agent, batch: SpecProposalBatch) -> BatchRead:
        spec = AgentSpec.model_validate(agent.draft_spec)
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=batch.id
        )
        quotes = ctx.has(Perm.RUNS_VIEW)
        names = await ConfigurationService(self.db).names(ctx, hunks)
        gates = {
            hunk.id: await self._model_gate(ctx, batch, hunk)
            for hunk in hunks
            if hunk.status == HunkStatus.PENDING.value and _changes_model(hunk)
        }
        return BatchRead(
            id=batch.id,
            agent_id=batch.agent_id,
            status=batch.status,
            expected_effect=batch.expected_effect,
            request_id=batch.request_id,
            hunks=[
                self._hunk(spec, hunk, quotes=quotes, names=names, blocked=gates.get(hunk.id))
                for hunk in hunks
            ],
            check_eval_run_ids=list(batch.check_eval_run_ids),
            created_at=batch.created_at,
        )

    async def _model_gate(
        self, ctx: AuthContext, batch: SpecProposalBatch, hunk: SpecProposalHunk
    ) -> str | None:
        """Why a change of model may not be accepted yet, or `None` when it may.

        It pays off only once a check of the batch - one that ran this very model
        and that the reader can see - came out with nothing graded left open, a
        verdict, and no confirmed regression. `check_first` until there is one,
        `inconclusive` when it decided nothing, `regression` when it broke cases.
        """
        evals = EvalRunService(self.db)
        for run_id in reversed(batch.check_eval_run_ids):
            try:
                run = await evals.get(ctx, run_id)
            except (AuthorizationError, NotFoundError):
                continue
            candidate = next((arm for arm in run.arms if arm.role == ArmRole.CANDIDATE), None)
            if run.status != EvalRunStatus.COMPLETED.value or candidate is None:
                continue
            stored = await eval_run_repo.get_arm(
                self.db, candidate.id, organization_id=ctx.organization_id
            )
            ran = None if stored is None or stored.spec is None else stored.spec
            if ran is None or str(ran.get("model_profile_id")) != str(hunk.new_value):
                continue
            if candidate.ungraded_cases or run.outcome is None:
                return "inconclusive"
            if run.outcome.regressions_confirmed or run.outcome.verdict in ("worse", "mixed"):
                return "regression"
            if run.outcome.verdict in (None, "invalid"):
                return "inconclusive"
            return None
        return "check_first"

    @staticmethod
    def _hunk(
        spec: AgentSpec,
        hunk: SpecProposalHunk,
        *,
        quotes: bool,
        names: dict[str, str],
        blocked: str | None,
    ) -> HunkRead:
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
            path=hunk.path,
            op=hunk.op,
            base_value=hunk.base_value,
            new_value=hunk.new_value,
            accepted_value=hunk.accepted_value,
            effect=hunk.effect,
            names={key: name for key, name in names.items() if _refers_to(hunk, key)},
            blocked=blocked,
            rationale=hunk.rationale,
            expected_effect=hunk.expected_effect,
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

    async def _locked(self, ctx: AuthContext, agent: Agent) -> Agent:
        """The agent locked for this transaction, so its draft is the one a decision writes over."""
        locked = await agent_repo.lock(self.db, agent.id, organization_id=ctx.organization_id)
        if locked is None:
            raise NotFoundError(message="Agent not found", details={"agent_id": agent.id})
        return locked

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
        agent = await self._locked(ctx, await self._editable(ctx, agent_id))
        hunk = await authoring_repo.get_hunk(self.db, hunk_id, organization_id=ctx.organization_id)
        if hunk is None:
            raise NotFoundError(message="Suggestion not found", details={"hunk_id": hunk_id})
        batch = await self._open_batch_of(ctx, agent, hunk.batch_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        written: AgentSpec | None = None
        if decision.action == "accept" and hunk.kind == HunkKind.SPEC_FIELD.value:
            written, values = await self._accepted_field(ctx, spec, batch, hunk, decision)
            moved = await self._move(ctx, hunk, HunkStatus.PENDING, HunkStatus.ACCEPTED, values)
        elif decision.action == "accept":
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
                {"accepted_text": None, "accepted_override": None, "accepted_value": None},
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

    async def _accepted_field(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        batch: SpecProposalBatch,
        hunk: SpecProposalHunk,
        decision: HunkDecision,
    ) -> tuple[AgentSpec, dict[str, Any]]:
        """The draft with a field change accepted, as the person accepting it.

        Raises:
            BadRequestError: It is not a change the assistant may propose, it
                removes or reconfigures a safeguard, the value was edited where
                editing is not offered or does not validate, the draft moved since,
                or - for a change of model - no check of the batch shows it pays
                off yet.
            AuthorizationError: It adds something the person accepting it may not
                grant: a capability, a collection, a context file, a model, MCP tools.
        """
        refused = authoring_fields.standing_refusal(
            hunk.path or "", hunk.op or "", hunk.base_value, hunk.new_value
        )
        if refused is not None:
            raise BadRequestError(
                message=_STANDING_REFUSALS[refused], details={"hunk_id": hunk.id, "reason": refused}
            )
        value = hunk.new_value
        if decision.value is not None:
            if hunk.path not in _EDITABLE and not (hunk.path or "").endswith("/description"):
                raise BadRequestError(
                    message="Only a single setting or a text can be edited before accepting",
                    details={"hunk_id": hunk.id},
                )
            staged = authoring_fields.stage(spec, hunk.path or "", hunk.op or "", decision.value)
            if isinstance(staged, str):
                raise BadRequestError(
                    message="That value cannot be accepted here", details={"reason": staged}
                )
            value = staged[1]
        written = authoring_hunks.apply_field(spec, hunk, value)
        if written is None:
            raise self._stale()
        problems = await self.registry.reference_problems(
            ctx, written, path=hunk.path or "", op=hunk.op or ""
        )
        if problems:
            raise AuthorizationError(
                message=(
                    "This suggestion adds something you may not grant. Ask somebody who "
                    "can reach it, or dismiss it."
                ),
                details={"problems": problems},
            )
        if _changes_model(hunk):
            reason = await self._model_gate(ctx, batch, hunk)
            if reason is not None:
                raise BadRequestError(message=_GATE_MESSAGES[reason], details={"reason": reason})
        return written, {"accepted_value": value}

    def _undone(self, spec: AgentSpec, hunk: SpecProposalHunk) -> AgentSpec:
        if hunk.kind == HunkKind.SPEC_FIELD.value:
            undone = authoring_hunks.undo_field(spec, hunk)
        elif hunk.kind == HunkKind.TOOL_OVERRIDE.value:
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
        projected, skipped = authoring_hunks.projection(
            AgentSpec.model_validate(agent.draft_spec), pending
        )
        if skipped:
            # A check that silently left suggestions out would be read as having measured them.
            raise BadRequestError(
                message=(
                    f"{len(skipped)} of the {len(pending)} waiting suggestions no longer fit the "
                    "draft, or clash with another. Accept or dismiss them first, so the check "
                    "measures exactly what is waiting."
                ),
                details={"hunk_ids": [hunk.id for hunk in skipped]},
            )
        return agent, batch, projected

    async def _check_request(
        self, ctx: AuthContext, agent_id: UUID, body: ProposalCheck
    ) -> EvalRunRequest:
        """The run a check makes: on the dataset named, or on a suite's dataset and environment."""
        if body.suite_id is not None:
            suite = await EvalSuiteService(self.db).get(ctx, agent_id, body.suite_id)
            return EvalRunRequest(
                dataset_id=suite.dataset_id,
                environment_id=suite.environment_id,
                paired_baseline=True,
            )
        assert body.dataset_id is not None, "ProposalCheck names a dataset or a suite"
        return EvalRunRequest(
            dataset_id=body.dataset_id,
            dataset_version=body.dataset_version,
            environment_id=body.environment_id,
            paired_baseline=True,
        )

    async def _suite(
        self, ctx: AuthContext, agent_id: UUID, body: ProposalCheck
    ) -> EvalSuiteCheck | None:
        """The suite a check runs on, as it stands now - none for a check on a dataset."""
        if body.suite_id is None:
            return None
        suite = await EvalSuiteService(self.db).get(ctx, agent_id, body.suite_id)
        return EvalSuiteCheck(suite_id=suite.id, name=suite.name, threshold=suite.threshold)

    async def estimate_check(
        self, ctx: AuthContext, agent_id: UUID, body: ProposalCheck
    ) -> EvalRunEstimate:
        """What checking the pending suggestions against a dataset would cost."""
        agent, batch, projected = await self._projection(ctx, agent_id)
        return await EvalRunService(self.db).estimate(
            ctx,
            agent.id,
            await self._check_request(ctx, agent.id, body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=projected,
            exclude_conversations=batch.evidence_conversation_ids,
        )

    async def _skill_check(
        self, ctx: AuthContext, skill_id: UUID, body: ProposalCheck
    ) -> tuple[Agent, EvalRunRequest, dict[UUID, SkillBody], list[UUID]]:
        """The agent a skill change is checked on, the run that checks it, the body, and what to leave out.

        Both sides run the agent's published version - frozen and already
        validated at publish - so checking needs only `agents:run` on it, and
        the skill's body is the one difference.

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
        version = (
            None
            if agent.current_version_id is None
            else await self.registry.get_version(ctx, agent.id, agent.current_version_id)
        )
        if version is None or skill.id not in AgentSpec.model_validate(version.spec).skill_ids:
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
        request = (await self._check_request(ctx, agent.id, body)).model_copy(
            update={"version": version.version, "baseline_version": version.version}
        )
        return agent, request, bodies, [UUID(str(conversation)) for conversation in evidence]

    async def estimate_skill_check(
        self, ctx: AuthContext, skill_id: UUID, body: ProposalCheck
    ) -> EvalRunEstimate:
        """What checking a pending skill change on one agent would cost."""
        agent, request, bodies, evidence = await self._skill_check(ctx, skill_id, body)
        return await EvalRunService(self.db).estimate(
            ctx,
            agent.id,
            request,
            purpose=EvalRunPurpose.GATE,
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
        agent, request, bodies, evidence = await self._skill_check(ctx, skill_id, body)
        return await EvalRunService(self.db).start(
            ctx,
            agent.id,
            request,
            purpose=EvalRunPurpose.GATE,
            candidate_skills=bodies,
            exclude_conversations=evidence,
            suite=await self._suite(ctx, agent.id, body),
        )

    async def _context_check(
        self, ctx: AuthContext, context_id: UUID, body: ProposalCheck
    ) -> tuple[Agent, EvalRunRequest, dict[UUID, ContextBody], list[UUID]]:
        """The agent a context change is checked on, the run, the body, and what to leave out.

        As for a skill: both sides run the agent's published version, and the
        file's body is the one difference.

        Raises:
            NotFoundError: No such pending change to this file.
            BadRequestError: No agent named, or one that does not bind the file.
        """
        file = await self.contexts.get(ctx, context_id, perm=Perm.CONTEXT_EDIT)
        proposal = (
            None
            if body.proposal_id is None
            else await context_proposal_repo.get(
                self.db, body.proposal_id, organization_id=ctx.organization_id
            )
        )
        if (
            proposal is None
            or proposal.context_id != file.id
            or proposal.status != ProposalStatus.PENDING.value
        ):
            raise NotFoundError(
                message="No change to this context file is waiting",
                details={"context_id": file.id},
            )
        if body.agent_id is None:
            raise BadRequestError(
                message="Pick an agent that uses this context file to check the change on",
                details={"context_id": file.id},
            )
        agent = await self.registry.get(ctx, body.agent_id, perm=Perm.AGENTS_RUN)
        version = (
            None
            if agent.current_version_id is None
            else await self.registry.get_version(ctx, agent.id, agent.current_version_id)
        )
        if version is None or file.id not in AgentSpec.model_validate(version.spec).context_ids:
            raise BadRequestError(
                message=f"'{agent.name}' does not use '{file.name}' in its published version",
                details={"agent_id": agent.id, "context_id": file.id},
            )
        request = (
            None
            if proposal.authoring_request_id is None
            else await authoring_repo.get_request(
                self.db, proposal.authoring_request_id, organization_id=ctx.organization_id
            )
        )
        evidence = [] if request is None else request.evidence.get("conversation_ids", [])
        bodies = {file.id: ContextBody(description=proposal.description, content=proposal.content)}
        checked = (await self._check_request(ctx, agent.id, body)).model_copy(
            update={"version": version.version, "baseline_version": version.version}
        )
        return agent, checked, bodies, [UUID(str(conversation)) for conversation in evidence]

    async def estimate_context_check(
        self, ctx: AuthContext, context_id: UUID, body: ProposalCheck
    ) -> EvalRunEstimate:
        """What checking a pending context change on one agent would cost."""
        agent, request, bodies, evidence = await self._context_check(ctx, context_id, body)
        return await EvalRunService(self.db).estimate(
            ctx,
            agent.id,
            request,
            purpose=EvalRunPurpose.GATE,
            candidate_contexts=bodies,
            exclude_conversations=evidence,
        )

    async def check_context(
        self, ctx: AuthContext, context_id: UUID, body: ProposalCheck
    ) -> EvalRunRead:
        """Run a dataset on an agent using the file, with the proposed body in place of its own.

        Applying the change is live for every agent bound to the file, which is
        why it is checked before.
        """
        agent, request, bodies, evidence = await self._context_check(ctx, context_id, body)
        return await EvalRunService(self.db).start(
            ctx,
            agent.id,
            request,
            purpose=EvalRunPurpose.GATE,
            candidate_contexts=bodies,
            exclude_conversations=evidence,
            suite=await self._suite(ctx, agent.id, body),
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
            await self._check_request(ctx, agent.id, body),
            purpose=EvalRunPurpose.GATE,
            candidate_spec=projected,
            exclude_conversations=batch.evidence_conversation_ids,
            suite=await self._suite(ctx, agent.id, body),
        )
        await authoring_repo.update_batch(
            self.db,
            batch=batch,
            values={"check_eval_run_ids": [*batch.check_eval_run_ids, started.id]},
        )
        return started
