"""Data access for the authoring assistant's requests, proposals and evidence."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.authoring import (
    AuthoringRequest,
    AuthoringStatus,
    BatchStatus,
    HunkStatus,
    SpecProposalBatch,
    SpecProposalHunk,
)
from app.db.models.conversation import Message, ToolCall
from app.db.models.message_rating import MessageRating
from app.db.models.skill_proposal import ProposalStatus, SkillProposal


async def create_request(
    db: AsyncSession,
    *,
    organization_id: UUID,
    kind: str,
    target: str,
    agent_id: UUID | None,
    skill_id: UUID | None,
    context_id: UUID | None = None,
    created_by_user_id: UUID | None,
    created_by_api_key_id: UUID | None = None,
    estimate_usd: Decimal,
    window_days: int,
) -> AuthoringRequest:
    request = AuthoringRequest(
        organization_id=organization_id,
        kind=kind,
        target=target,
        agent_id=agent_id,
        skill_id=skill_id,
        context_id=context_id,
        created_by_user_id=created_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        status=AuthoringStatus.QUEUED.value,
        estimate_usd=estimate_usd,
        window_days=window_days,
        evidence={},
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def get_request(
    db: AsyncSession, request_id: UUID, *, organization_id: UUID
) -> AuthoringRequest | None:
    result = await db.execute(
        select(AuthoringRequest).where(
            AuthoringRequest.id == request_id,
            AuthoringRequest.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_requests(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    skill_id: UUID | None = None,
    context_id: UUID | None = None,
    limit: int = 10,
) -> list[AuthoringRequest]:
    """The latest requests on one agent, skill or context file, newest first."""
    statement = select(AuthoringRequest).where(AuthoringRequest.organization_id == organization_id)
    if agent_id is not None:
        statement = statement.where(AuthoringRequest.agent_id == agent_id)
    if skill_id is not None:
        statement = statement.where(AuthoringRequest.skill_id == skill_id)
    if context_id is not None:
        statement = statement.where(AuthoringRequest.context_id == context_id)
    result = await db.execute(statement.order_by(AuthoringRequest.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def update_request(
    db: AsyncSession, *, request: AuthoringRequest, values: dict[str, Any]
) -> AuthoringRequest:
    for field, value in values.items():
        setattr(request, field, value)
    await db.flush()
    await db.refresh(request)
    return request


async def fail_unfinished(
    db: AsyncSession, request_id: UUID, *, organization_id: UUID, error: str, now: datetime
) -> bool:
    """Fail a request still queued or running. `False` when it had already ended, which keeps its outcome.

    Raises:
        DBAPIError: Another transaction holds the request - a worker still at
            it keeps its row locked for the whole request. Refused at once
            rather than waited on, so the caller can try again later instead
            of stalling behind a run that may last an hour.
    """
    await db.execute(
        select(AuthoringRequest.id)
        .where(
            AuthoringRequest.id == request_id,
            AuthoringRequest.organization_id == organization_id,
        )
        .with_for_update(nowait=True)
    )
    result = await db.execute(
        update(AuthoringRequest)
        .where(
            AuthoringRequest.id == request_id,
            AuthoringRequest.organization_id == organization_id,
            AuthoringRequest.status.in_(
                (AuthoringStatus.QUEUED.value, AuthoringStatus.RUNNING.value)
            ),
        )
        .values(status=AuthoringStatus.FAILED.value, error=error, finished_at=now)
        .returning(AuthoringRequest.id)
    )
    return result.scalar_one_or_none() is not None


async def get_batch(
    db: AsyncSession, batch_id: UUID, *, organization_id: UUID, lock: bool = False
) -> SpecProposalBatch | None:
    """One batch. `lock` holds its row until the transaction ends.

    A decision locks the batch before it touches a hunk, and supersession updates
    the same row, so the two serialize: an Accept in flight either commits
    before a newer request closes the batch, or sees it closed and refuses.
    """
    statement = select(SpecProposalBatch).where(
        SpecProposalBatch.id == batch_id,
        SpecProposalBatch.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def get_open_batch(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, lock: bool = False
) -> SpecProposalBatch | None:
    statement = select(SpecProposalBatch).where(
        SpecProposalBatch.organization_id == organization_id,
        SpecProposalBatch.agent_id == agent_id,
        SpecProposalBatch.status == BatchStatus.OPEN.value,
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def latest_batch(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> SpecProposalBatch | None:
    """The agent's newest batch a person has been shown.

    An improvement session's candidate stays out until the session makes it the
    open batch: until then its hunks are still being checked.
    """
    result = await db.execute(
        select(SpecProposalBatch)
        .where(
            SpecProposalBatch.organization_id == organization_id,
            SpecProposalBatch.agent_id == agent_id,
            SpecProposalBatch.status != BatchStatus.CANDIDATE.value,
        )
        .order_by(SpecProposalBatch.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_batch(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    request_id: UUID | None,
    source_started_at: datetime,
    expected_effect: str,
    evidence_conversation_ids: Sequence[UUID],
) -> SpecProposalBatch:
    batch = SpecProposalBatch(
        organization_id=organization_id,
        agent_id=agent_id,
        request_id=request_id,
        source_started_at=source_started_at,
        status=BatchStatus.OPEN.value,
        expected_effect=expected_effect,
        evidence_conversation_ids=list(evidence_conversation_ids),
    )
    db.add(batch)
    await db.flush()
    await db.refresh(batch)
    return batch


async def update_batch(
    db: AsyncSession, *, batch: SpecProposalBatch, values: dict[str, Any]
) -> SpecProposalBatch:
    for field, value in values.items():
        setattr(batch, field, value)
    await db.flush()
    await db.refresh(batch)
    return batch


async def close_batch(
    db: AsyncSession, *, batch: SpecProposalBatch, status: BatchStatus
) -> SpecProposalBatch:
    return await update_batch(
        db, batch=batch, values={"status": status.value, "closed_at": datetime.now(UTC)}
    )


async def add_hunks(
    db: AsyncSession, *, organization_id: UUID, batch_id: UUID, hunks: Sequence[dict[str, Any]]
) -> list[SpecProposalHunk]:
    """Append hunks to a batch, after any it already holds."""
    result = await db.execute(
        select(func.coalesce(func.max(SpecProposalHunk.position), -1)).where(
            SpecProposalHunk.batch_id == batch_id,
            SpecProposalHunk.organization_id == organization_id,
        )
    )
    start = int(result.scalar_one()) + 1
    rows = [
        SpecProposalHunk(
            organization_id=organization_id,
            batch_id=batch_id,
            position=start + index,
            status=HunkStatus.PENDING.value,
            **values,
        )
        for index, values in enumerate(hunks)
    ]
    db.add_all(rows)
    await db.flush()
    for row in rows:
        await db.refresh(row)
    return rows


async def list_hunks(
    db: AsyncSession, *, organization_id: UUID, batch_id: UUID
) -> list[SpecProposalHunk]:
    result = await db.execute(
        select(SpecProposalHunk)
        .where(
            SpecProposalHunk.batch_id == batch_id,
            SpecProposalHunk.organization_id == organization_id,
        )
        .order_by(SpecProposalHunk.position)
    )
    return list(result.scalars().all())


async def get_hunk(
    db: AsyncSession, hunk_id: UUID, *, organization_id: UUID
) -> SpecProposalHunk | None:
    result = await db.execute(
        select(SpecProposalHunk)
        .where(
            SpecProposalHunk.id == hunk_id,
            SpecProposalHunk.organization_id == organization_id,
        )
        # A decision is a bulk UPDATE, which leaves an already loaded row stale.
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def decide_hunk(
    db: AsyncSession,
    *,
    organization_id: UUID,
    hunk_id: UUID,
    expected: HunkStatus,
    status: HunkStatus,
    decided_by: UUID | None,
    values: dict[str, Any] | None = None,
) -> SpecProposalHunk | None:
    """Move a hunk from `expected` to `status`, or nothing when it is no longer `expected`.

    A compare-and-set: of two reviewers accepting and dismissing one hunk at the
    same moment, exactly one finds it pending. The other gets `None`.
    """
    decided_at = None if status is HunkStatus.PENDING else datetime.now(UTC)
    result = await db.execute(
        update(SpecProposalHunk)
        .where(
            SpecProposalHunk.id == hunk_id,
            SpecProposalHunk.organization_id == organization_id,
            SpecProposalHunk.status == expected.value,
        )
        .values(
            status=status.value,
            decided_by_user_id=None if status is HunkStatus.PENDING else decided_by,
            decided_at=decided_at,
            **(values or {}),
        )
        .returning(SpecProposalHunk.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await get_hunk(db, hunk_id, organization_id=organization_id)


async def pending_counts(
    db: AsyncSession, *, organization_id: UUID, agent_ids: Sequence[UUID]
) -> dict[UUID, dict[str, int]]:
    """Pending hunks in each agent's open batch, by kind."""
    if not agent_ids:
        return {}
    result = await db.execute(
        select(SpecProposalBatch.agent_id, SpecProposalHunk.kind, func.count())
        .join(SpecProposalHunk, SpecProposalHunk.batch_id == SpecProposalBatch.id)
        .where(
            SpecProposalBatch.organization_id == organization_id,
            SpecProposalBatch.agent_id.in_(agent_ids),
            SpecProposalBatch.status == BatchStatus.OPEN.value,
            SpecProposalHunk.status == HunkStatus.PENDING.value,
        )
        .group_by(SpecProposalBatch.agent_id, SpecProposalHunk.kind)
    )
    counts: dict[UUID, dict[str, int]] = {}
    for agent_id, kind, count in result.all():
        counts.setdefault(agent_id, {})[kind] = int(count)
    return counts


async def agents_with_pending(
    db: AsyncSession, *, organization_id: UUID
) -> list[tuple[Agent, dict[str, int]]]:
    """Every agent whose open batch still has pending hunks, with the count by kind."""
    result = await db.execute(
        select(Agent, SpecProposalHunk.kind, func.count())
        .join(SpecProposalBatch, SpecProposalBatch.agent_id == Agent.id)
        .join(SpecProposalHunk, SpecProposalHunk.batch_id == SpecProposalBatch.id)
        .where(
            SpecProposalBatch.organization_id == organization_id,
            SpecProposalBatch.status == BatchStatus.OPEN.value,
            SpecProposalHunk.status == HunkStatus.PENDING.value,
        )
        .group_by(Agent.id, SpecProposalHunk.kind)
        .order_by(Agent.name)
    )
    rows: dict[UUID, tuple[Agent, dict[str, int]]] = {}
    for agent, kind, count in result.all():
        rows.setdefault(agent.id, (agent, {}))[1][kind] = int(count)
    return list(rows.values())


async def count_pending_skill_proposals(db: AsyncSession, *, organization_id: UUID) -> int:
    """Skill changes the assistant proposed that nobody has decided yet."""
    result = await db.execute(
        select(func.count())
        .select_from(SkillProposal)
        .where(
            SkillProposal.organization_id == organization_id,
            SkillProposal.status == ProposalStatus.PENDING.value,
            SkillProposal.authoring_request_id.is_not(None),
        )
    )
    return int(result.scalar_one())


@dataclass(frozen=True)
class EvidenceRun:
    """One run the assistant may read, and what its readers said about it.

    Attributes:
        run: The run.
        rating: -1 when any answer of the run was rated down, 1 when rated up
            and never down, 0 when nobody rated it.
        comments: The comments left with its down-ratings.
    """

    run: AgentRun
    rating: int
    comments: list[str]


def _readable_runs(*, organization_id: UUID, since: datetime) -> list[Any]:
    """What makes a run evidence at all.

    Never an eval run: the assistant is checked by evals, so the runs those
    produce - the cases, their reruns, the judge and the assistant's own - stay
    out of what it reads. Never a Builder test run, which is the author trying
    things rather than a reader being served, and never a delegate's run, whose
    prompt is its parent's wording rather than a person's.
    """
    return [
        AgentRun.organization_id == organization_id,
        AgentRun.surface != RunSurface.EVAL.value,
        AgentRun.is_test.is_(False),
        AgentRun.parent_run_id.is_(None),
        AgentRun.started_at >= since,
    ]


async def evidence_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    agent_ids: Sequence[UUID] | None = None,
    skill_name: str | None = None,
    since: datetime,
    limit: int,
) -> list[EvidenceRun]:
    """The runs most worth reading, rated-down first.

    Down-rated runs with a comment, then other down-rated runs, then failures,
    then up-rated runs as the contrast, newest first within each; unrated runs
    that succeeded are not evidence of anything. `agent_id` narrows the runs to
    one agent's, `agent_ids` to several agents' - those binding a context file -
    and `skill_name` to those whose model opened that skill.

    A skill reaches a run as a deferred capability the model loads with
    `load_capability`, a framework tool no binding can rename, so the call's
    name and its `id` argument identify the skill on every run.
    """
    rating = (
        select(
            Message.run_id.label("run_id"),
            func.min(MessageRating.rating).label("worst"),
            func.max(MessageRating.rating).label("best"),
            func.array_remove(
                func.array_agg(
                    case(
                        (MessageRating.rating < 0, func.nullif(MessageRating.comment, "")),
                        else_=None,
                    )
                ),
                None,
            ).label("comments"),
        )
        .join(MessageRating, MessageRating.message_id == Message.id)
        .where(Message.run_id.is_not(None))
        .group_by(Message.run_id)
        .subquery()
    )
    worst = func.coalesce(rating.c.worst, 0)
    failed = AgentRun.status.in_(
        (RunStatus.FAILED.value, RunStatus.BUDGET_EXCEEDED.value, RunStatus.GUARDRAIL_BLOCKED.value)
    )
    rank = case(
        (and_(worst < 0, func.cardinality(rating.c.comments) > 0), 0),
        (worst < 0, 1),
        (failed, 2),
        (rating.c.best > 0, 3),
        else_=4,
    )
    statement = (
        select(AgentRun, rating.c.worst, rating.c.best, rating.c.comments)
        .outerjoin(rating, rating.c.run_id == AgentRun.id)
        .where(*_readable_runs(organization_id=organization_id, since=since))
        .where(or_(worst < 0, failed, rating.c.best > 0))
    )
    if agent_id is not None:
        statement = statement.where(AgentRun.agent_id == agent_id)
    if agent_ids is not None:
        statement = statement.where(AgentRun.agent_id.in_(list(agent_ids)))
    if skill_name is not None:
        loaded = (
            select(ToolCall.id)
            .join(Message, Message.id == ToolCall.message_id)
            .where(
                Message.run_id == AgentRun.id,
                ToolCall.tool_name == "load_capability",
                ToolCall.args["id"].astext == skill_name,
            )
        )
        statement = statement.where(loaded.exists())
    result = await db.execute(statement.order_by(rank, AgentRun.started_at.desc()).limit(limit))
    rows: list[EvidenceRun] = []
    for run, worst_value, best_value, comments in result.all():
        value = -1 if (worst_value or 0) < 0 else (1 if (best_value or 0) > 0 else 0)
        rows.append(EvidenceRun(run=run, rating=value, comments=list(comments or [])))
    return rows
