"""`FailureLearningService` - mine real failures, curate them, try fixes.

Mining is a live aggregation over `agent_runs` and `message_ratings` when
the patterns endpoint is called - no ETL table, no background job. A count
is not a diagnosis: a human curates a mined pattern into a ledger entry,
writes the rule's rationale, and builds an eval case that reproduces one
bad experience. A try runs each case twice per sample - once on the current
published spec ("old"), once with the proposed instructions or skill content
("new") - through the test-run path, and the gate passes only when old fails
and new passes. Skill proposals snapshot their prior content at apply for an
audited, one-shot rollback. Nothing here auto-applies.

Reads use `AGENTS_VIEW` on the agent, writes `AGENTS_EDIT`, applying
`AGENTS_PUBLISH` (or `SKILLS_EDIT` on the skill), resolved in the service
with `resolve_access` - a refusal answers as "not found", the workflow-eval
pattern. Only the org-wide patterns list is different: it is an
aggregation, not a resource, so its route carries a `RUNS_VIEW` gate.
"""

import hashlib
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.failure_learning import (
    AgentEvalCase,
    AgentEvalRun,
    AgentFailureLedger,
    AgentInstructionProposal,
)
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    agent_run_repo,
    conversation_repo,
    credential_repo,
    failure_learning_repo,
)
from app.schemas.conversation import ConversationCreate
from app.schemas.eval_judging import EvalExpectation
from app.schemas.failure_learning import (
    MAX_EVAL_CASES,
    AppliedVersionRead,
    EvalCaseCreate,
    EvalCaseLatestTry,
    EvalCaseList,
    EvalCaseRead,
    EvalTryCaseRead,
    EvalTryCreate,
    EvalTryRead,
    FailurePattern,
    FailurePatternList,
    LedgerEntryCreate,
    LedgerEntryList,
    LedgerEntryRead,
    LedgerEntryUpdate,
    ProposalCreate,
    ProposalList,
    ProposalRead,
    ProposalReject,
)
from app.schemas.skill import SkillUpdate
from app.services import rate_limit
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.conversation import ConversationService
from app.services.eval_judging import judge
from app.services.skills import SkillService

WINDOW_DAYS = 7
"""The mining window: patterns count occurrences in the last 7 days."""

MIN_COUNT_PER_AGENT = 3
"""Occurrences in the window for one (agent, error class) to surface."""

MIN_COUNT_PER_MODEL = 5
"""Occurrences in the window for one (model, error class), across agents."""

MIN_COUNT_DOWN_RATED = 3
"""Down-rated answers in the window for one agent to surface."""

STALLED_AFTER = timedelta(minutes=10)
"""A running run whose heartbeat is older than this is stalled now."""

NON_TERMINAL_STATUSES = frozenset(
    {RunStatus.RUNNING.value, RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value}
)
"""A run in one of these has no verdict yet - it may still answer."""

HANG_NOTE = (
    "A run stuck in a model call keeps beating its heartbeat, so a running run "
    "with a fresh heartbeat may still be hung - mining cannot see it. Only "
    "heartbeat-stale runs surface here."
)
MODEL_NOTE = (
    "Per-model patterns are approximate: model_label is the primary model, "
    "not necessarily the one that served a request when a fallback answered."
)

_APPROVAL_EXPIRED = "No decision within 72h"
_QUESTION_EXPIRED = "No answer within 24h"
_HTTP_ERROR = re.compile(r"ModelHTTPError, HTTP (\d+)")


def parse_error_class(error: str | None, status: str) -> str:
    """The class of a stored failure sentence, from its known shapes.

    The stored `error` is a sentence, not a code (`agents/failures.py`),
    so mining parses the shapes it knows: the expiry sentences, the
    `ModelHTTPError, HTTP <code>` sentence, the step-limit sentence.
    Anything else is `other` - a count, not a diagnosis, and a human
    curating the entry says what it actually was.
    """
    if status == RunStatus.LOOP_STOPPED.value:
        return "loop_stopped"
    if status == RunStatus.BUDGET_EXCEEDED.value:
        return "budget_exceeded"
    if error:
        if _APPROVAL_EXPIRED in error:
            return "approval_expired"
        if _QUESTION_EXPIRED in error:
            return "question_expired"
        match = _HTTP_ERROR.search(error)
        if match is not None:
            return f"ModelHTTPError:{match.group(1)}"
        if "UsageLimitExceeded" in error:
            return "UsageLimitExceeded"
    return "other"


def pattern_key_for(status: str, error_class: str) -> str:
    """The machine key for a pattern, e.g. `failed:ModelHTTPError:400`."""
    if status == RunStatus.FAILED.value:
        return f"failed:{error_class}"
    if error_class in ("approval_expired", "question_expired", "loop_stopped", "budget_exceeded"):
        return error_class
    return f"{status}:{error_class}"


def _window(from_date: date | None, to_date: date | None) -> tuple[datetime, datetime]:
    """Inclusive ISO dates into a half-open UTC window, defaulting to 7 days."""
    anchor = datetime.now(UTC).date()
    to_actual = to_date or anchor
    from_actual = from_date or (to_actual - timedelta(days=WINDOW_DAYS - 1))
    if from_actual > to_actual:
        raise ValidationError(
            message="from is after to",
            details={"from": str(from_actual), "to": str(to_actual)},
        )
    start = datetime(from_actual.year, from_actual.month, from_actual.day, tzinfo=UTC)
    end = datetime(to_actual.year, to_actual.month, to_actual.day, tzinfo=UTC) + timedelta(days=1)
    return start, end


def _history_messages(case_input: dict[str, Any]) -> list[ModelMessage]:
    """A case's prior turns as model messages, for the try to run with."""
    messages: list[ModelMessage] = []
    for turn in case_input.get("history") or []:
        if turn.get("role") == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=str(turn.get("text", "")))]))
        else:
            messages.append(ModelRequest(parts=[UserPromptPart(content=str(turn.get("text", "")))]))
    return messages


class FailureLearningService:
    """Mine an agent's real failures, curate them, and try fixes against them."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.runner = AgentRunnerService(db)
        self.conversations = ConversationService(db)
        self.skills = SkillService(db)

    async def list_org_patterns(
        self,
        ctx: AuthContext,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        agent_id: UUID | None = None,
        model: str | None = None,
        status: str | None = None,
        min_count: int | None = None,
    ) -> FailurePatternList:
        """Org-wide failure patterns, grouped by (agent, model, status, class).

        The route carries the `RUNS_VIEW` gate - this is an aggregation, not
        a resource - so the service only scopes it to the organization.
        """
        start, end = _window(from_date, to_date)
        return await self._mine(
            ctx,
            agent_id=agent_id,
            start=start,
            end=end,
            model=model,
            status=status,
            min_count=min_count or MIN_COUNT_PER_AGENT,
        )

    async def list_agent_patterns(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        model: str | None = None,
        status: str | None = None,
        min_count: int | None = None,
    ) -> FailurePatternList:
        """The same aggregation, for one agent the caller may view."""
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        start, end = _window(from_date, to_date)
        return await self._mine(
            ctx,
            agent_id=agent_id,
            start=start,
            end=end,
            model=model,
            status=status,
            min_count=min_count or MIN_COUNT_PER_AGENT,
        )

    async def _mine(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID | None,
        start: datetime,
        end: datetime,
        model: str | None,
        status: str | None,
        min_count: int,
    ) -> FailurePatternList:
        groups = await agent_run_repo.failure_groups(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, since=start, until=end
        )
        merged: dict[tuple[UUID, str | None, str, str], FailurePattern] = {}
        group_keys: dict[
            tuple[UUID, str | None, str, str], list[tuple[UUID, str | None, str, str | None]]
        ] = defaultdict(list)
        for group in groups:
            error_class = parse_error_class(group.error, group.status)
            key = (group.agent_id, group.model_label, group.status, error_class)
            group_keys[key].append((group.agent_id, group.model_label, group.status, group.error))
            pattern = merged.get(key)
            if pattern is None:
                merged[key] = FailurePattern(
                    agent_id=group.agent_id,
                    model=group.model_label,
                    status=group.status,
                    error_class=error_class,
                    pattern_key=pattern_key_for(group.status, error_class),
                    count=group.count,
                    first_seen=group.first_seen,
                    last_seen=group.last_seen,
                )
            else:
                pattern.count += group.count
                if group.first_seen is not None and (
                    pattern.first_seen is None or group.first_seen < pattern.first_seen
                ):
                    pattern.first_seen = group.first_seen
                if group.last_seen is not None and (
                    pattern.last_seen is None or group.last_seen > pattern.last_seen
                ):
                    pattern.last_seen = group.last_seen
        kept: list[FailurePattern] = []
        for key, pattern in merged.items():
            if pattern.count < min_count:
                continue
            for agent, model_label, group_status, error in group_keys[key]:
                pattern.sample_run_ids.extend(
                    await agent_run_repo.failure_group_samples(
                        self.db,
                        organization_id=ctx.organization_id,
                        agent_id=agent,
                        model_label=model_label,
                        status=group_status,
                        error=error,
                    )
                )
            pattern.sample_run_ids = pattern.sample_run_ids[:5]
            kept.append(pattern)
        # Per-model patterns: the same failures read across agents, for a
        # model whose failure mode follows it from agent to agent.
        if agent_id is None:
            # Apply the model threshold to every merged agent group. Per-agent
            # patterns below MIN_COUNT_PER_AGENT still contribute to the
            # cross-agent total.
            by_model: dict[
                tuple[str | None, str, str],
                list[tuple[tuple[UUID, str | None, str, str], FailurePattern]],
            ] = defaultdict(list)
            for key, pattern in merged.items():
                by_model[(pattern.model, pattern.status, pattern.error_class)].append(
                    (key, pattern)
                )
            for (model_label, model_status, error_class), members in by_model.items():
                total = sum(member.count for _, member in members)
                if total < MIN_COUNT_PER_MODEL:
                    continue
                first = min(
                    (member.first_seen for _, member in members if member.first_seen is not None),
                    default=None,
                )
                last = max(
                    (member.last_seen for _, member in members if member.last_seen is not None),
                    default=None,
                )
                sample_run_ids = [
                    run_id for _, member in members for run_id in member.sample_run_ids
                ][:5]
                for key, member in members:
                    if len(sample_run_ids) == 5:
                        break
                    if member.sample_run_ids:
                        continue
                    for agent, member_model, member_status, error in group_keys[key]:
                        sample_run_ids.extend(
                            await agent_run_repo.failure_group_samples(
                                self.db,
                                organization_id=ctx.organization_id,
                                agent_id=agent,
                                model_label=member_model,
                                status=member_status,
                                error=error,
                            )
                        )
                        if len(sample_run_ids) >= 5:
                            break
                kept.append(
                    FailurePattern(
                        agent_id=None,
                        model=model_label,
                        status=model_status,
                        error_class=error_class,
                        pattern_key=pattern_key_for(model_status, error_class),
                        count=total,
                        first_seen=first,
                        last_seen=last,
                        sample_run_ids=sample_run_ids[:5],
                    )
                )
        stalled = await agent_run_repo.stalled_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            stale_before=datetime.now(UTC) - STALLED_AFTER,
        )
        by_agent_model: dict[tuple[UUID, str | None], list[AgentRun]] = defaultdict(list)
        for run in stalled:
            by_agent_model[(run.agent_id, run.model_label)].append(run)
        for (stalled_agent_id, model_label), runs in by_agent_model.items():
            started = [run.started_at for run in runs if run.started_at is not None]
            kept.append(
                FailurePattern(
                    agent_id=stalled_agent_id,
                    model=model_label,
                    status=RunStatus.RUNNING.value,
                    error_class="stalled",
                    pattern_key="stalled",
                    count=len(runs),
                    first_seen=min(started) if started else None,
                    last_seen=max(started) if started else None,
                    sample_run_ids=[run.id for run in runs[:5]],
                )
            )
        down_rated = await agent_run_repo.down_rated_messages(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, since=start, until=end
        )
        by_rated: dict[tuple[UUID, str | None], list[Any]] = defaultdict(list)
        for row in down_rated:
            by_rated[(row.agent_id, row.model_label)].append(row)
        for (rated_agent_id, model_label), rows in by_rated.items():
            if len(rows) < MIN_COUNT_DOWN_RATED:
                continue
            rated_at = [row.rated_at for row in rows if row.rated_at is not None]
            kept.append(
                FailurePattern(
                    agent_id=rated_agent_id,
                    model=model_label,
                    status="downrated",
                    error_class="downrated",
                    pattern_key="downrated",
                    count=len(rows),
                    first_seen=min(rated_at) if rated_at else None,
                    last_seen=max(rated_at) if rated_at else None,
                    sample_run_ids=[row.run_id for row in rows[:5]],
                    sample_message_ids=[row.message_id for row in rows[:5]],
                )
            )
        items = kept
        if model is not None:
            items = [pattern for pattern in items if pattern.model == model]
        if status is not None:
            items = [pattern for pattern in items if pattern.status == status]
        tracked = await self._tracked_keys(ctx)
        for pattern in items:
            pattern.already_tracked = self._is_tracked(pattern, tracked)
        names = await self._agent_names(ctx, {p.agent_id for p in items if p.agent_id is not None})
        for pattern in items:
            if pattern.agent_id is not None:
                pattern.agent_name = names.get(pattern.agent_id)
        items.sort(
            key=lambda p: (p.count, p.last_seen or datetime.min.replace(tzinfo=UTC)), reverse=True
        )
        return FailurePatternList(items=items, total=len(items), notes=[HANG_NOTE, MODEL_NOTE])

    @staticmethod
    def _is_tracked(
        pattern: FailurePattern, tracked: set[tuple[UUID | None, str | None, str]]
    ) -> bool:
        """Whether an open ledger entry already covers this pattern.

        Same scope only, the same rule the partial unique indexes enforce:
        an agent pattern is covered by an open entry for that agent, a model
        pattern by an open entry for that model.
        """
        for agent_id, model, pattern_key in tracked:
            if pattern_key != pattern.pattern_key:
                continue
            if pattern.agent_id is None:
                if agent_id is None and model == pattern.model:
                    return True
            elif agent_id == pattern.agent_id:
                return True
        return False

    async def _tracked_keys(self, ctx: AuthContext) -> set[tuple[UUID | None, str | None, str]]:
        """The open ledger entries, as (agent_id, model, pattern_key) triples."""
        entries = await failure_learning_repo.open_entries(
            self.db, organization_id=ctx.organization_id
        )
        return {(entry.agent_id, entry.model, entry.pattern_key) for entry in entries}

    async def _agent_names(self, ctx: AuthContext, agent_ids: set[UUID]) -> dict[UUID, str]:
        if not agent_ids:
            return {}
        agents, _ = await agent_repo.list_by_ids(
            self.db, organization_id=ctx.organization_id, agent_ids=agent_ids
        )
        return {agent.id: agent.name for agent in agents}

    async def list_ledger(
        self, ctx: AuthContext, agent_id: UUID, *, status: str | None = None
    ) -> LedgerEntryList:
        """An agent's ledger entries, newest first.

        Model-scoped entries are org-wide pattern records, so they list
        beside the agent's own - there is no org-wide ledger route in
        Phase 1, and otherwise a model entry created here would surface
        nowhere.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        entries = await failure_learning_repo.list_entries(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, status=status
        )
        entries.extend(
            await failure_learning_repo.list_entries(
                self.db, organization_id=ctx.organization_id, agent_id=None, status=status
            )
        )
        entries.sort(key=lambda entry: entry.created_at, reverse=True)
        items = [await self._ledger_read(entry) for entry in entries]
        return LedgerEntryList(items=items, total=len(items))

    async def create_ledger(
        self, ctx: AuthContext, agent_id: UUID, data: LedgerEntryCreate
    ) -> LedgerEntryRead:
        """A pattern, accepted as real and worth a rule.

        Raises:
            NotFoundError: The agent is out of reach.
            BadRequestError: A model-scoped entry names no model.
            AlreadyExistsError: An open entry already covers this pattern.
        """
        agent = await self._agent(ctx, agent_id, Perm.AGENTS_EDIT, lock=True)
        if data.scope == "model" and not data.model:
            raise BadRequestError(
                message="A model-scoped entry names its model",
                details={"model": None},
            )
        entry_agent_id = agent.id if data.scope == "agent" else None
        existing = await failure_learning_repo.list_entries(
            self.db, organization_id=ctx.organization_id, agent_id=entry_agent_id
        )
        if any(
            entry.pattern_key == data.pattern_key
            and entry.status in ("draft", "open")
            and (entry_agent_id is not None or entry.model == data.model)
            for entry in existing
        ):
            raise AlreadyExistsError(
                message="An open ledger entry already covers this pattern",
                details={"pattern_key": data.pattern_key},
            )
        entry = await failure_learning_repo.create_entry(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=entry_agent_id,
            scope=data.scope,
            model=data.model,
            pattern_key=data.pattern_key,
            title=data.title,
            summary=data.summary,
            evidence=data.evidence,
            status="draft",
            created_by_user_id=ctx.subject_id,
        )
        return await self._ledger_read(entry)

    async def get_ledger(self, ctx: AuthContext, agent_id: UUID, entry_id: UUID) -> LedgerEntryRead:
        """One entry, with its case count.

        Raises:
            NotFoundError: The agent or the entry is out of reach.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        entry = await self._entry(ctx, agent_id, entry_id)
        return await self._ledger_read(entry)

    async def update_ledger(
        self, ctx: AuthContext, agent_id: UUID, entry_id: UUID, data: LedgerEntryUpdate
    ) -> LedgerEntryRead:
        """Curate an entry: accept it, dismiss it, rewrite why.

        Resolving is the apply's job - a bare status change to `resolved`
        is refused, and only an apply sets it.

        Raises:
            NotFoundError: The agent or the entry is out of reach.
            BadRequestError: The change would mark the entry resolved.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_EDIT)
        entry = await self._entry(ctx, agent_id, entry_id)
        update_data = writable(data, over=AgentFailureLedger)
        if update_data.get("status") == "resolved":
            raise BadRequestError(
                message="An entry is resolved by applying a proposal, not by a status change",
                details={"status": "resolved"},
            )
        entry = await failure_learning_repo.update_entry(
            self.db, entry=entry, update_data=update_data
        )
        return await self._ledger_read(entry)

    async def delete_ledger(self, ctx: AuthContext, agent_id: UUID, entry_id: UUID) -> None:
        """Remove an entry. Its eval cases keep what they said (they record the
        entry as gone - the workflow-eval "a case outlives its step" rule).

        Raises:
            NotFoundError: The agent or the entry is out of reach.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_EDIT)
        entry = await self._entry(ctx, agent_id, entry_id)
        await failure_learning_repo.delete_entry(self.db, entry=entry)

    async def list_proposals(
        self, ctx: AuthContext, agent_id: UUID, *, status: str | None = None
    ) -> ProposalList:
        """An agent's proposals, newest first, optionally one status.

        An `applied` entry carries `applied_version_id` and its eval
        evidence - this is the applied-changes list; there is no separate
        endpoint for it.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        proposals = await failure_learning_repo.list_proposals(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, status=status
        )
        items = [await self._proposal_read(proposal) for proposal in proposals]
        return ProposalList(items=items, total=len(items))

    async def create_proposal(
        self, ctx: AuthContext, agent_id: UUID, data: ProposalCreate
    ) -> ProposalRead:
        """Propose a change: new text for the agent's instructions, or for one skill.

        An instruction target is written against the agent's current
        published version unless the body names one, and is gated on the
        linked try when it is applied. A skill target is written against
        the skill's content now - its SHA-256 is recorded as the base - and
        is human-reviewed only, never eval-gated.

        Raises:
            NotFoundError: The agent, the named ledger entry, the named
                try, the named base version, or the skill is out of reach.
            BadRequestError: The target names no skill, or names one for an
                instructions target.
        """
        if data.target.type == "instructions" and data.target.skill_id is not None:
            raise BadRequestError(
                message="An instructions-targeted proposal names no skill",
                details={"skill_id": str(data.target.skill_id)},
            )
        if data.ledger_entry_id is not None:
            await self._entry(ctx, agent_id, data.ledger_entry_id)
        if data.eval_try_id is not None:
            await self._try_row(ctx, agent_id, data.eval_try_id)
        if data.target.type == "skill":
            await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
            skill_id = data.target.skill_id
            if skill_id is None:
                raise BadRequestError(
                    message="A skill-targeted proposal names its skill",
                    details={"skill_id": None},
                )
            skill = await self.skills.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
            base_version_id = None
            base_content_sha256 = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
        else:
            agent = await self._agent(ctx, agent_id, Perm.AGENTS_EDIT, lock=True)
            base_version_id = data.base_agent_version_id or agent.current_version_id
            if base_version_id is not None:
                version = await agent_repo.get_version(
                    self.db, base_version_id, organization_id=ctx.organization_id
                )
                if version is None or version.agent_id != agent.id:
                    raise NotFoundError(
                        message="Agent version not found",
                        details={"version_id": str(base_version_id)},
                    )
            base_content_sha256 = None
        proposal = await failure_learning_repo.create_proposal(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            ledger_entry_id=data.ledger_entry_id,
            eval_try_id=data.eval_try_id,
            target_type=data.target.type,
            skill_id=data.target.skill_id,
            old_text=data.old_text,
            new_text=data.new_text,
            rationale=data.rationale,
            base_agent_version_id=base_version_id,
            base_content_sha256=base_content_sha256,
            status="draft",
            created_by_user_id=ctx.subject_id,
        )
        return await self._proposal_read(proposal)

    async def get_proposal(
        self, ctx: AuthContext, agent_id: UUID, proposal_id: UUID
    ) -> ProposalRead:
        """One proposal, its eval evidence, and its apply record if applied.

        Raises:
            NotFoundError: The agent or the proposal is out of reach.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        proposal = await self._proposal(ctx, agent_id, proposal_id)
        return await self._proposal_read(proposal)

    async def reject_proposal(
        self, ctx: AuthContext, agent_id: UUID, proposal_id: UUID, data: ProposalReject
    ) -> ProposalRead:
        """Reject a proposal, with the reason.

        The reason is recorded in the audit trail - the proposal row carries
        no decision note. Only a draft can be rejected.

        Raises:
            NotFoundError: The agent or the proposal is out of reach.
            ConflictError: The proposal is already applied or rejected.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_EDIT)
        proposal = await self._proposal(ctx, agent_id, proposal_id)
        if proposal.status != "draft":
            raise ConflictError(
                message=f"A {proposal.status} proposal cannot be rejected",
                details={"proposal_id": str(proposal.id), "status": proposal.status},
            )
        proposal = await failure_learning_repo.update_proposal(
            self.db,
            proposal=proposal,
            update_data={
                "status": "rejected",
                "decided_by_user_id": ctx.subject_id,
                "decided_at": datetime.now(UTC),
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.instruction_proposal_rejected",
            target_type="skill" if proposal.target_type == "skill" else "agent",
            target_id=str(proposal.skill_id) if proposal.target_type == "skill" else str(agent_id),
            details={"proposal_id": str(proposal.id), "reason": data.reason},
        )
        return await self._proposal_read(proposal)

    async def apply_proposal(
        self, ctx: AuthContext, agent_id: UUID, proposal_id: UUID
    ) -> ProposalRead:
        """Apply a proposal: the change lands, audited, and the loop closes.

        An instruction target publishes the new text as a new version; a
        skill target edits the skill live. Applying is the approval - there
        is no separate approve step - and nothing auto-applies.

        Raises:
            NotFoundError: The agent, the proposal, or the skill is out of reach.
            ConflictError: The proposal is not a draft, the agent was
                republished since it was written, the agent has unpublished
                draft edits, or the skill changed since it was written.
            BadRequestError: An instruction target names no gate-passed try,
                or the agent's published version is missing.
        """
        proposal = await self._proposal(ctx, agent_id, proposal_id)
        if proposal.status != "draft":
            raise ConflictError(
                message=f"A {proposal.status} proposal cannot be applied",
                details={"proposal_id": str(proposal.id), "status": proposal.status},
            )
        if proposal.target_type == "skill":
            await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
            proposal = await self._apply_skill(ctx, agent_id, proposal)
        else:
            agent = await self._agent(ctx, agent_id, Perm.AGENTS_PUBLISH, lock=True)
            proposal = await self._apply_instructions(ctx, agent, proposal)
        return await self._proposal_read(proposal)

    async def revert_proposal(
        self, ctx: AuthContext, agent_id: UUID, proposal_id: UUID
    ) -> ProposalRead:
        """Restore the skill content snapshotted when this proposal applied."""
        proposal = await self._proposal(ctx, agent_id, proposal_id)
        if (
            proposal.target_type != "skill"
            or proposal.status != "applied"
            or proposal.reverted_at is not None
            or proposal.prior_skill_content is None
        ):
            raise ConflictError(
                message="This proposal has no available skill rollback",
                details={"proposal_id": str(proposal.id)},
            )
        if proposal.skill_id is None or proposal.applied_content_sha256 is None:
            raise ConflictError(
                message="This proposal has no complete skill rollback record",
                details={"proposal_id": str(proposal.id)},
            )
        restored_content = proposal.prior_skill_content
        skill = await self.skills.get(ctx, proposal.skill_id, perm=Perm.SKILLS_EDIT)
        current_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
        if current_hash != proposal.applied_content_sha256:
            raise ConflictError(
                message="The skill changed after this proposal applied; refusing to overwrite it",
                details={"proposal_id": str(proposal.id), "skill_id": str(skill.id)},
            )
        await self.skills.update(ctx, skill.id, SkillUpdate(content=restored_content))
        proposal = await failure_learning_repo.update_proposal(
            self.db,
            proposal=proposal,
            update_data={"reverted_by_user_id": ctx.subject_id, "reverted_at": datetime.now(UTC)},
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.skill_proposal_reverted",
            target_type="skill",
            target_id=str(skill.id),
            details={
                "proposal_id": str(proposal.id),
                "restored_content_sha256": hashlib.sha256(
                    restored_content.encode("utf-8")
                ).hexdigest(),
                "reverted_from_content_sha256": current_hash,
            },
        )
        return await self._proposal_read(proposal)

    async def _apply_instructions(
        self, ctx: AuthContext, agent: Agent, proposal: AgentInstructionProposal
    ) -> AgentInstructionProposal:
        """`save_draft` + `publish` in one audited action, in order.

        The eval gate is judged on read, the same way the try-read endpoint
        judges it: the gate must have passed, so a proposal whose try is
        missing, pending, or failed cannot land. This is the design §2.4
        rule that "the gate must have passed", read as a check at apply
        time rather than a stored verdict.
        """
        await self._require_gate_passed(ctx, agent.id, proposal)
        if agent.current_version_id != proposal.base_agent_version_id:
            raise ConflictError(
                message="The agent has been republished since this proposal was "
                "written - re-base the proposal instead",
                details={
                    "proposal_id": str(proposal.id),
                    "base_version_id": str(proposal.base_agent_version_id)
                    if proposal.base_agent_version_id is not None
                    else None,
                    "current_version_id": str(agent.current_version_id)
                    if agent.current_version_id is not None
                    else None,
                },
            )
        if agent.current_version_id is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' has not been published yet",
                details={"agent_id": str(agent.id)},
            )
        published = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=ctx.organization_id
        )
        if published is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' points at a missing version",
                details={"agent_id": str(agent.id)},
            )
        if agent.draft_spec != published.spec:
            raise ConflictError(
                message="The agent has unpublished draft edits - publish or discard them first",
                details={"agent_id": str(agent.id)},
            )
        spec = AgentSpec.model_validate(agent.draft_spec)
        spec.instructions = proposal.new_text
        await self.registry.save_draft(ctx, agent.id, spec)
        version = await self.registry.publish(
            ctx, agent.id, note=f"failure-learning proposal {proposal.id}"
        )
        proposal = await self._mark_applied(
            ctx,
            proposal,
            applied_version_id=version.id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.instruction_proposal_applied",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "proposal_id": str(proposal.id),
                "version_id": str(version.id),
                "eval_try_id": str(proposal.eval_try_id)
                if proposal.eval_try_id is not None
                else None,
                "base_version_id": str(proposal.base_agent_version_id)
                if proposal.base_agent_version_id is not None
                else None,
            },
        )
        return proposal

    async def _apply_skill(
        self, ctx: AuthContext, agent_id: UUID, proposal: AgentInstructionProposal
    ) -> AgentInstructionProposal:
        """A live skill edit, audited - human-reviewed only, never eval-gated.

        Skills have no versions and no per-run override, so no try can
        evidence one: a linked try, if any, is not consulted. There is no
        skill rollback - a bad apply is undone by a new edit, not a version
        restore. The applied content hash is recorded in the audit entry,
        since the proposal row carries no version to point at.
        """
        skill_id = proposal.skill_id
        if skill_id is None:
            raise BadRequestError(
                message="A skill-targeted proposal names its skill",
                details={"proposal_id": str(proposal.id)},
            )
        skill = await self.skills.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        if proposal.base_content_sha256 is None:
            raise ConflictError(
                message="This proposal records no base content hash - re-base it "
                "against the skill as it stands",
                details={"proposal_id": str(proposal.id)},
            )
        current_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
        if current_hash != proposal.base_content_sha256:
            raise ConflictError(
                message="The skill has changed since this proposal was written - "
                "re-base the proposal instead",
                details={
                    "proposal_id": str(proposal.id),
                    "base_content_sha256": proposal.base_content_sha256,
                },
            )
        await self._require_gate_passed(ctx, agent_id, proposal)
        await self.skills.update(ctx, skill.id, SkillUpdate(content=proposal.new_text))
        proposal = await self._mark_applied(
            ctx,
            proposal,
            applied_version_id=None,
            prior_skill_content=skill.content,
            applied_content_sha256=hashlib.sha256(proposal.new_text.encode("utf-8")).hexdigest(),
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.instruction_proposal_applied",
            target_type="skill",
            target_id=str(skill.id),
            details={
                "proposal_id": str(proposal.id),
                "content_sha256": hashlib.sha256(proposal.new_text.encode("utf-8")).hexdigest(),
            },
        )
        return proposal

    async def _mark_applied(
        self,
        ctx: AuthContext,
        proposal: AgentInstructionProposal,
        *,
        applied_version_id: UUID | None,
        prior_skill_content: str | None = None,
        applied_content_sha256: str | None = None,
    ) -> AgentInstructionProposal:
        """Mark the proposal applied and resolve its ledger entry, if any.

        The entry resolves the same way for a skill target as for an
        instruction target: the pattern is fixed either way, and leaving it
        open would mark the pattern already-tracked forever.
        """
        proposal = await failure_learning_repo.update_proposal(
            self.db,
            proposal=proposal,
            update_data={
                "status": "applied",
                "applied_version_id": applied_version_id,
                "decided_by_user_id": ctx.subject_id,
                "decided_at": datetime.now(UTC),
                "prior_skill_content": prior_skill_content,
                "applied_content_sha256": applied_content_sha256,
            },
        )
        if proposal.ledger_entry_id is not None:
            entry = await failure_learning_repo.get_entry(
                self.db,
                proposal.ledger_entry_id,
                organization_id=ctx.organization_id,
                agent_id=proposal.agent_id,
            )
            if entry is not None and entry.status != "resolved":
                await failure_learning_repo.update_entry(
                    self.db,
                    entry=entry,
                    update_data={
                        "status": "resolved",
                        "resolved_proposal_id": proposal.id,
                    },
                )
        return proposal

    async def _require_gate_passed(
        self, ctx: AuthContext, agent_id: UUID, proposal: AgentInstructionProposal
    ) -> None:
        """Refuse unless the linked try exists and gate-passed, judged now.

        Raises:
            BadRequestError: No try is linked, the linked try is gone, or
                its verdict is not a pass - pending included, since a run
                still going is not evidence the new text works.
        """
        if proposal.eval_try_id is None:
            raise BadRequestError(
                message="This proposal names no eval try - link a try that "
                "gate-passed before applying",
                details={"proposal_id": str(proposal.id), "eval_try_id": None},
            )
        run = await failure_learning_repo.get_run(
            self.db,
            proposal.eval_try_id,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
        )
        if run is None:
            raise BadRequestError(
                message="The linked eval try is gone - link a try that gate-passed before applying",
                details={
                    "proposal_id": str(proposal.id),
                    "eval_try_id": str(proposal.eval_try_id),
                },
            )
        expected_hash = hashlib.sha256(proposal.new_text.encode("utf-8")).hexdigest()
        if (
            run.proposal_id != proposal.id
            or run.tested_content_sha256 != expected_hash
            or (proposal.target_type == "skill" and run.target_skill_id != proposal.skill_id)
        ):
            raise ConflictError(
                message="The linked eval try did not test this exact proposal",
                details={"proposal_id": str(proposal.id), "eval_try_id": str(run.id)},
            )
        judged = await self._judged(run)
        if judged.gate_passed is not True:
            raise BadRequestError(
                message="The linked try has not passed the eval gate",
                details={
                    "proposal_id": str(proposal.id),
                    "eval_try_id": str(proposal.eval_try_id),
                    "gate_passed": judged.gate_passed,
                },
            )

    async def _proposal(
        self, ctx: AuthContext, agent_id: UUID, proposal_id: UUID
    ) -> AgentInstructionProposal:
        proposal = await failure_learning_repo.get_proposal(
            self.db, proposal_id, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if proposal is None:
            raise NotFoundError(
                message="Proposal not found", details={"proposal_id": str(proposal_id)}
            )
        return proposal

    async def _try_row(self, ctx: AuthContext, agent_id: UUID, try_id: UUID) -> AgentEvalRun:
        run = await failure_learning_repo.get_run(
            self.db, try_id, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if run is None:
            raise NotFoundError(message="Eval run not found", details={"eval_run_id": str(try_id)})
        return run

    async def _proposal_read(self, proposal: AgentInstructionProposal) -> ProposalRead:
        evidence = None
        if proposal.eval_try_id is not None:
            run = await failure_learning_repo.get_run(
                self.db,
                proposal.eval_try_id,
                organization_id=proposal.organization_id,
                agent_id=proposal.agent_id,
            )
            if run is not None:
                evidence = await self._judged(run)
        applied_version = None
        if proposal.applied_version_id is not None:
            version = await agent_repo.get_version(
                self.db, proposal.applied_version_id, organization_id=proposal.organization_id
            )
            if version is not None:
                applied_version = AppliedVersionRead(id=version.id, number=version.version)
        return ProposalRead(
            id=proposal.id,
            organization_id=proposal.organization_id,
            agent_id=proposal.agent_id,
            ledger_entry_id=proposal.ledger_entry_id,
            eval_try_id=proposal.eval_try_id,
            target_type=proposal.target_type,  # ty: ignore[invalid-argument-type]
            skill_id=proposal.skill_id,
            old_text=proposal.old_text,
            new_text=proposal.new_text,
            rationale=proposal.rationale,
            base_agent_version_id=proposal.base_agent_version_id,
            base_content_sha256=proposal.base_content_sha256,
            applied_content_sha256=proposal.applied_content_sha256,
            reverted_at=proposal.reverted_at,
            rollback_available=(
                proposal.target_type == "skill"
                and proposal.status == "applied"
                and proposal.prior_skill_content is not None
                and proposal.reverted_at is None
            ),
            status=proposal.status,  # ty: ignore[invalid-argument-type]
            applied_version_id=proposal.applied_version_id,
            created_by_user_id=proposal.created_by_user_id,
            decided_by_user_id=proposal.decided_by_user_id,
            decided_at=proposal.decided_at,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            eval_evidence=evidence,
            applied_version=applied_version,
            eval_gated=True,
        )

    async def _ledger_read(self, entry: AgentFailureLedger) -> LedgerEntryRead:
        case_count = await failure_learning_repo.count_cases_for_entry(
            self.db, organization_id=entry.organization_id, ledger_entry_id=entry.id
        )
        proposal_count = await failure_learning_repo.count_proposals_for_entry(
            self.db, organization_id=entry.organization_id, ledger_entry_id=entry.id
        )
        return LedgerEntryRead(
            id=entry.id,
            organization_id=entry.organization_id,
            agent_id=entry.agent_id,
            scope=entry.scope,  # ty: ignore[invalid-argument-type]
            model=entry.model,
            pattern_key=entry.pattern_key,
            title=entry.title,
            summary=entry.summary,
            evidence=entry.evidence,
            status=entry.status,  # ty: ignore[invalid-argument-type]
            created_by_user_id=entry.created_by_user_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            eval_case_count=case_count,
            proposal_count=proposal_count,
            open_since=entry.created_at,
        )

    async def _entry(self, ctx: AuthContext, agent_id: UUID, entry_id: UUID) -> AgentFailureLedger:
        entry = await failure_learning_repo.get_entry(
            self.db, entry_id, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if entry is None:
            raise NotFoundError(
                message="Ledger entry not found", details={"entry_id": str(entry_id)}
            )
        return entry

    async def list_cases(self, ctx: AuthContext, agent_id: UUID) -> EvalCaseList:
        """An agent's cases, oldest first, each with its latest try's verdict."""
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        cases = await failure_learning_repo.list_cases(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        latest_by_case: dict[UUID, EvalCaseLatestTry] = {}
        latest = await failure_learning_repo.latest_run(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if latest is not None:
            judged = await self._judged(latest)
            for result in judged.cases:
                latest_by_case[result.eval_id] = EvalCaseLatestTry(
                    try_id=latest.id,
                    old_passed=result.old_passed,
                    new_passed=result.new_passed,
                    gate_passed=result.gate_passed,
                    status=result.status,
                )
        items = [
            EvalCaseRead(
                id=case.id,
                agent_id=case.agent_id,
                ledger_entry_id=case.ledger_entry_id,
                name=case.name,
                position=case.position,
                input=case.input,  # type: ignore[arg-type]
                expectation=EvalExpectation.model_validate(case.expectation),
                model_profile_id=case.model_profile_id,
                source_run_id=case.source_run_id,
                created_by_user_id=case.created_by_user_id,
                created_at=case.created_at,
                updated_at=case.updated_at,
                latest_try=latest_by_case.get(case.id),
            )
            for case in cases
        ]
        return EvalCaseList(items=items, total=len(items))

    async def create_case(
        self, ctx: AuthContext, agent_id: UUID, data: EvalCaseCreate
    ) -> EvalCaseRead:
        """A case for an agent: an input, and what its answer should say.

        The agent row serializes case count and position allocation against
        other creators.

        Raises:
            NotFoundError: The agent, the named ledger entry, the source run,
                or the model profile is out of reach.
            BadRequestError: The agent already holds `MAX_EVAL_CASES` cases.
        """
        agent = await self._agent(ctx, agent_id, Perm.AGENTS_EDIT, lock=True)
        if (
            await failure_learning_repo.count_cases(
                self.db, organization_id=ctx.organization_id, agent_id=agent.id
            )
            >= MAX_EVAL_CASES
        ):
            raise BadRequestError(
                message=f"An agent holds at most {MAX_EVAL_CASES} eval cases",
                details={"agent_id": str(agent.id)},
            )
        if data.ledger_entry_id is not None:
            await self._entry(ctx, agent.id, data.ledger_entry_id)
        if data.source_run_id is not None:
            run = await agent_run_repo.get_run(
                self.db, data.source_run_id, organization_id=ctx.organization_id
            )
            if run is None or run.agent_id != agent.id:
                raise NotFoundError(
                    message="Source run not found", details={"run_id": str(data.source_run_id)}
                )
        if data.model_profile_id is not None:
            profile = await credential_repo.get_profile(
                self.db, data.model_profile_id, organization_id=ctx.organization_id
            )
            if profile is None:
                raise NotFoundError(
                    message="Model profile not found",
                    details={"model_profile_id": str(data.model_profile_id)},
                )
        case = await failure_learning_repo.create_case(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            ledger_entry_id=data.ledger_entry_id,
            name=data.name,
            position=await failure_learning_repo.last_position(
                self.db, organization_id=ctx.organization_id, agent_id=agent.id
            )
            + 1,
            input=data.input.model_dump(mode="json"),
            expectation=data.expectation.model_dump(mode="json"),
            model_profile_id=data.model_profile_id,
            source_run_id=data.source_run_id,
            created_by_user_id=ctx.subject_id,
        )
        return EvalCaseRead(
            id=case.id,
            agent_id=case.agent_id,
            ledger_entry_id=case.ledger_entry_id,
            name=case.name,
            position=case.position,
            input=case.input,  # type: ignore[arg-type]
            expectation=EvalExpectation.model_validate(case.expectation),
            model_profile_id=case.model_profile_id,
            source_run_id=case.source_run_id,
            created_by_user_id=case.created_by_user_id,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    async def delete_case(self, ctx: AuthContext, agent_id: UUID, case_id: UUID) -> None:
        """Remove a case. Tries already made keep what they said then.

        Raises:
            NotFoundError: The agent or the case is out of reach.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_EDIT)
        case = await failure_learning_repo.get_case(
            self.db, case_id, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if case is None:
            raise NotFoundError(message="Eval case not found", details={"eval_id": str(case_id)})
        await failure_learning_repo.delete_case(self.db, case=case)

    async def start_try(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        data: EvalTryCreate,
        *,
        first_run_charged: bool = False,
    ) -> EvalTryRead:
        """Start a try of the named cases: old text against new, per sample.

        Each case runs twice per sample - once on the current published spec,
        once with the proposal's instruction or skill content - as test runs
        in fresh conversations. A case whose run cannot start is recorded as
        refused with the reason, and the others still start. The try returns
        with the run ids; verdicts are judged when the try is read.

        A try runs the agent, so it needs the published spec: an agent that
        was never published, or is archived, is refused before any tokens
        are spent.

        Raises:
            NotFoundError: The agent, a named case, or the named proposal is
                out of reach.
            BadRequestError: The try names both a proposal and an override,
                names neither, names a non-draft proposal,
                or the agent has nothing published to try against.
        """
        agent = await self._agent(ctx, agent_id, Perm.AGENTS_EDIT)
        if data.proposal_id is not None and data.instructions_override is not None:
            raise BadRequestError(
                message="A try names a proposal or an instructions override, not both",
                details={"proposal_id": str(data.proposal_id)},
            )
        proposal = None
        target_skill_id = None
        tested_content_sha256 = None
        if data.proposal_id is not None:
            proposal = await self._proposal(ctx, agent.id, data.proposal_id)
            if proposal.status != "draft":
                raise BadRequestError(
                    message="Only a draft proposal can be tried",
                    details={"proposal_id": str(proposal.id), "status": proposal.status},
                )
            new_text = proposal.new_text
            if proposal.target_type == "skill":
                if proposal.skill_id is None:
                    raise BadRequestError("A skill proposal must name its skill")
                skill = await self.skills.get(ctx, proposal.skill_id, perm=Perm.SKILLS_EDIT)
                current_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
                if current_hash != proposal.base_content_sha256:
                    raise ConflictError(
                        message="The skill has changed since this proposal was written",
                        details={"proposal_id": str(proposal.id)},
                    )
                target_skill_id = skill.id
            tested_content_sha256 = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        else:
            new_text = data.instructions_override
        if new_text is None:
            raise BadRequestError(
                message="A try needs new instruction text to try",
                details={"instructions_override": None},
            )
        cases = await failure_learning_repo.get_cases_by_ids(
            self.db, data.case_ids, organization_id=ctx.organization_id, agent_id=agent.id
        )
        if len(cases) != len(data.case_ids):
            found = {case.id for case in cases}
            missing = [case_id for case_id in data.case_ids if case_id not in found]
            raise NotFoundError(message="Eval case not found", details={"eval_id": str(missing[0])})
        published_spec = await self._refuse_unrunnable(agent)
        if target_skill_id is not None and target_skill_id not in published_spec.skill_ids:
            raise BadRequestError(
                message="The skill proposal must target a skill attached to the published agent",
                details={"skill_id": str(target_skill_id)},
            )
        tried: list[dict[str, Any]] = []
        run_index = 0
        for case in cases:
            entry: dict[str, Any] = {
                "eval_id": str(case.id),
                "name": case.name,
                "expectation": case.expectation,
                "old_run_ids": [],
                "new_run_ids": [],
                "samples": data.samples,
                "refused": None,
            }
            for _sample in range(data.samples):
                for side in ("old", "new"):
                    run_id, refused = await self._try_side(
                        ctx,
                        agent,
                        case,
                        instructions_override=(
                            new_text if target_skill_id is None and side == "new" else None
                        ),
                        skill_content_overrides=(
                            {target_skill_id: new_text}
                            if target_skill_id is not None and side == "new"
                            else None
                        ),
                        charge=run_index != 0 or not first_run_charged,
                    )
                    run_index += 1
                    if run_id is not None:
                        entry[f"{side}_run_ids"].append(str(run_id))
                    elif entry["refused"] is None:
                        entry["refused"] = refused
            tried.append(entry)
        run_row = await failure_learning_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            proposal_id=data.proposal_id,
            target_skill_id=target_skill_id,
            tested_content_sha256=tested_content_sha256,
            started_by_user_id=ctx.subject_id,
            cases=tried,
        )
        if proposal is not None:
            await failure_learning_repo.update_proposal(
                self.db, proposal=proposal, update_data={"eval_try_id": run_row.id}
            )
        return await self._judged(run_row)

    async def _try_side(
        self,
        ctx: AuthContext,
        agent: Agent,
        case: AgentEvalCase,
        *,
        instructions_override: str | None,
        skill_content_overrides: dict[UUID, str] | None = None,
        charge: bool,
    ) -> tuple[UUID | None, str | None]:
        """One side of one sample: a fresh test conversation, one test run.

        Returns the run id, or `None` with the refusal when no run started.
        A run that started and then failed is not a refusal - its row is
        there to be judged, and a non-completed side fails the gate.
        """
        captured: list[AgentRun] = []

        async def _capture(run: AgentRun) -> None:
            captured.append(run)

        try:
            if charge:
                decision = await rate_limit.consume(
                    surface="agent_eval_run",
                    caller=f"user:{ctx.subject_id}",
                    limit=rate_limit.run_limit(),
                )
                if not decision.allowed:
                    raise RateLimitError(
                        message="Too many agent eval runs in the last minute. Wait and try again.",
                        details={"retry_after_seconds": decision.retry_after_seconds},
                    )
            conversation = await self.conversations.create_conversation(
                ConversationCreate(
                    organization_id=ctx.organization_id,
                    user_id=ctx.subject_id,
                    title=f"Eval: {case.name}",
                )
            )
            _, run = await self.runner.execute(
                ctx,
                agent.id,
                str(case.input.get("message", "")),
                surface=RunSurface.API,
                conversation_id=conversation.id,
                message_history=_history_messages(case.input),
                model_profile_id=case.model_profile_id,
                instructions_override=instructions_override,
                skill_content_overrides=skill_content_overrides,
                test=True,
                on_run_open=_capture,
            )
        except AppException as exc:
            if captured:
                return captured[0].id, None
            return None, exc.message
        else:
            return run.id, None

    async def get_try(self, ctx: AuthContext, agent_id: UUID, try_id: UUID) -> EvalTryRead:
        """A try of a set of cases, judged as its runs stand now.

        Raises:
            NotFoundError: The agent or the try is out of reach.
        """
        await self._agent(ctx, agent_id, Perm.AGENTS_VIEW)
        run = await failure_learning_repo.get_run(
            self.db, try_id, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if run is None:
            raise NotFoundError(message="Eval run not found", details={"eval_run_id": str(try_id)})
        return await self._judged(run)

    async def _refuse_unrunnable(self, agent: Agent) -> AgentSpec:
        """Refuse a try against an agent with nothing published to try.

        The published version is read off the agent row directly - access
        was already resolved as `AGENTS_EDIT` above - rather than through
        `get_runnable_spec`, which would re-check `AGENTS_RUN` and refuse an
        editor who may test the draft but not run the agent.
        """
        if agent.status == "archived":
            raise BadRequestError(
                message=f"Agent '{agent.name}' is archived", details={"agent_id": str(agent.id)}
            )
        if agent.current_version_id is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' has not been published yet",
                details={"agent_id": str(agent.id)},
            )
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=agent.organization_id
        )
        if version is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' points at a missing version",
                details={"agent_id": str(agent.id)},
            )
        return AgentSpec.model_validate(version.spec)

    async def _judged(self, eval_run: AgentEvalRun) -> EvalTryRead:
        results = [await self._judge_case(eval_run, entry) for entry in eval_run.cases]
        passed = sum(1 for result in results if result.gate_passed is True)
        failed = sum(1 for result in results if result.gate_passed is False)
        pending = sum(1 for result in results if result.gate_passed is None)
        return EvalTryRead(
            id=eval_run.id,
            agent_id=eval_run.agent_id,
            proposal_id=eval_run.proposal_id,
            target_skill_id=eval_run.target_skill_id,
            tested_content_sha256=eval_run.tested_content_sha256,
            created_at=eval_run.created_at,
            cases=results,
            passed=passed,
            failed=failed,
            pending=pending,
            gate_passed=True if pending == 0 and failed == 0 else False if failed > 0 else None,
        )

    async def _judge_case(self, eval_run: AgentEvalRun, entry: dict[str, Any]) -> EvalTryCaseRead:
        """One case as its runs stand: still going, answered, or failed."""
        eval_id, name = UUID(entry["eval_id"]), str(entry["name"])
        expectation = EvalExpectation.model_validate(entry["expectation"])
        old_passed = await self._judge_side(
            entry.get("old_run_ids") or [], expectation, eval_run.organization_id
        )
        new_passed = await self._judge_side(
            entry.get("new_run_ids") or [], expectation, eval_run.organization_id
        )
        refused = entry.get("refused")
        if not entry.get("old_run_ids") or not entry.get("new_run_ids"):
            # A side that never started is not evidence the old text fails:
            # the gate needs a run that ran and failed, not a refusal to run.
            gate, status, reason = False, "failed", refused or "no run started"
        elif old_passed is None or new_passed is None:
            gate, status, reason = None, "pending", None
        elif old_passed and new_passed:
            gate, status = False, "failed"
            reason = "case does not reproduce - the old text already passes"
        elif not old_passed and new_passed:
            gate, status, reason = True, "passed", None
        else:
            gate, status = False, "failed"
            reason = refused
        return EvalTryCaseRead(
            eval_id=eval_id,
            name=name,
            expectation=expectation,
            old_run_ids=[UUID(run_id) for run_id in entry.get("old_run_ids") or []],
            new_run_ids=[UUID(run_id) for run_id in entry.get("new_run_ids") or []],
            old_passed=old_passed,
            new_passed=new_passed,
            gate_passed=gate,
            status=status,
            reason=reason,
        )

    async def _judge_side(
        self, run_ids: list[str], expectation: EvalExpectation, organization_id: UUID
    ) -> bool | None:
        """Whether one side passed, on a majority of its samples.

        A side with no run started fails. A run that is not completed - still
        going, parked, cancelled, failed, over budget - fails the side, so a
        case whose expectation is `not_contains` can never pass by crashing.
        A side passes when a majority of its samples pass, and fails when
        half or more fail; anything else is still going.
        """
        if not run_ids:
            return False
        passes = fails = pending = 0
        for run_id in run_ids:
            run = await agent_run_repo.get_run(
                self.db, UUID(run_id), organization_id=organization_id
            )
            if run is None:
                # A run that was removed cannot pass: there is no answer to judge.
                fails += 1
                continue
            if run.status in NON_TERMINAL_STATUSES:
                pending += 1
                continue
            if run.status != RunStatus.COMPLETED.value:
                fails += 1
                continue
            answer = await conversation_repo.last_answer_of_run(self.db, run.id)
            if answer is None:
                fails += 1
                continue
            passed, _ = judge(expectation, {"text": answer, "status": run.status})
            if passed:
                passes += 1
            else:
                fails += 1
        total = len(run_ids)
        if passes * 2 > total:
            return True
        if fails * 2 >= total:
            return False
        return None

    async def _agent(
        self, ctx: AuthContext, agent_id: UUID, perm: Perm, *, lock: bool = False
    ) -> Agent:
        return await self.registry.get(ctx, agent_id, perm=perm, for_update=lock)
