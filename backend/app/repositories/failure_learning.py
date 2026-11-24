"""Persistence for the failure-learning loop's own rows.

Mining reads `agent_runs` and `message_ratings` live - see
`app.repositories.agent_run.failure_groups` and its siblings. This module
holds only what a human decided: ledger entries, eval cases, eval tries.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.failure_learning import (
    AgentEvalCase,
    AgentEvalRun,
    AgentFailureLedger,
    AgentInstructionProposal,
)


async def list_entries(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID | None, status: str | None = None
) -> list[AgentFailureLedger]:
    """Ledger entries for an agent - or, with `agent_id` null, model-scoped ones."""
    query = select(AgentFailureLedger).where(
        AgentFailureLedger.organization_id == organization_id,
        AgentFailureLedger.agent_id.is_(None)
        if agent_id is None
        else AgentFailureLedger.agent_id == agent_id,
    )
    if status is not None:
        query = query.where(AgentFailureLedger.status == status)
    result = await db.execute(query.order_by(AgentFailureLedger.created_at.desc()))
    return list(result.scalars())


async def open_entries(db: AsyncSession, *, organization_id: UUID) -> list[AgentFailureLedger]:
    """The org's live entries (draft or open): what mining marks already tracked."""
    result = await db.execute(
        select(AgentFailureLedger).where(
            AgentFailureLedger.organization_id == organization_id,
            AgentFailureLedger.status.in_(("draft", "open")),
        )
    )
    return list(result.scalars())


async def get_entry(
    db: AsyncSession, entry_id: UUID, *, organization_id: UUID, agent_id: UUID | None
) -> AgentFailureLedger | None:
    """One entry: the agent's own, or a model-scoped (org-wide) one.

    A model entry has no agent, so it is readable through any agent's path -
    it is a pattern record for the organization, not one agent's row.
    """
    result = await db.execute(
        select(AgentFailureLedger).where(
            AgentFailureLedger.id == entry_id,
            AgentFailureLedger.organization_id == organization_id,
            or_(
                AgentFailureLedger.agent_id == agent_id,
                AgentFailureLedger.agent_id.is_(None),
            ),
        )
    )
    return result.scalar_one_or_none()


async def create_entry(db: AsyncSession, **fields: Any) -> AgentFailureLedger:
    entry = AgentFailureLedger(**fields)
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def update_entry(
    db: AsyncSession, *, entry: AgentFailureLedger, update_data: dict[str, Any]
) -> AgentFailureLedger:
    for field, value in update_data.items():
        setattr(entry, field, value)
    await db.flush()
    await db.refresh(entry)
    return entry


async def delete_entry(db: AsyncSession, *, entry: AgentFailureLedger) -> None:
    await db.delete(entry)
    await db.flush()


async def list_cases(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> list[AgentEvalCase]:
    """One agent's cases, oldest first."""
    result = await db.execute(
        select(AgentEvalCase)
        .where(
            AgentEvalCase.organization_id == organization_id,
            AgentEvalCase.agent_id == agent_id,
        )
        .order_by(AgentEvalCase.position)
    )
    return list(result.scalars())


async def last_position(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """The position of the agent's last case, or 0 when it has none."""
    return int(
        await db.scalar(
            select(func.coalesce(func.max(AgentEvalCase.position), 0)).where(
                AgentEvalCase.organization_id == organization_id,
                AgentEvalCase.agent_id == agent_id,
            )
        )
        or 0
    )


async def count_cases(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                AgentEvalCase.organization_id == organization_id,
                AgentEvalCase.agent_id == agent_id,
            )
        )
        or 0
    )


async def count_cases_for_entry(
    db: AsyncSession, *, organization_id: UUID, ledger_entry_id: UUID
) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                AgentEvalCase.organization_id == organization_id,
                AgentEvalCase.ledger_entry_id == ledger_entry_id,
            )
        )
        or 0
    )


async def get_case(
    db: AsyncSession, case_id: UUID, *, organization_id: UUID, agent_id: UUID
) -> AgentEvalCase | None:
    result = await db.execute(
        select(AgentEvalCase).where(
            AgentEvalCase.id == case_id,
            AgentEvalCase.organization_id == organization_id,
            AgentEvalCase.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


async def get_cases_by_ids(
    db: AsyncSession, case_ids: list[UUID], *, organization_id: UUID, agent_id: UUID
) -> list[AgentEvalCase]:
    """The named cases, in the order they were named - a try tries them as given."""
    if not case_ids:
        return []
    result = await db.execute(
        select(AgentEvalCase).where(
            AgentEvalCase.id.in_(case_ids),
            AgentEvalCase.organization_id == organization_id,
            AgentEvalCase.agent_id == agent_id,
        )
    )
    by_id = {case.id: case for case in result.scalars()}
    return [by_id[case_id] for case_id in case_ids if case_id in by_id]


async def create_case(db: AsyncSession, **fields: Any) -> AgentEvalCase:
    case = AgentEvalCase(**fields)
    db.add(case)
    await db.flush()
    await db.refresh(case)
    return case


async def delete_case(db: AsyncSession, *, case: AgentEvalCase) -> None:
    await db.delete(case)
    await db.flush()


async def create_run(db: AsyncSession, **fields: Any) -> AgentEvalRun:
    run = AgentEvalRun(**fields)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID, agent_id: UUID
) -> AgentEvalRun | None:
    result = await db.execute(
        select(AgentEvalRun).where(
            AgentEvalRun.id == run_id,
            AgentEvalRun.organization_id == organization_id,
            AgentEvalRun.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


async def latest_run(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> AgentEvalRun | None:
    result = await db.execute(
        select(AgentEvalRun)
        .where(
            AgentEvalRun.organization_id == organization_id,
            AgentEvalRun.agent_id == agent_id,
        )
        .order_by(AgentEvalRun.created_at.desc(), AgentEvalRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_proposals(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, status: str | None = None
) -> list[AgentInstructionProposal]:
    """An agent's proposals, newest first, optionally one status."""
    query = select(AgentInstructionProposal).where(
        AgentInstructionProposal.organization_id == organization_id,
        AgentInstructionProposal.agent_id == agent_id,
    )
    if status is not None:
        query = query.where(AgentInstructionProposal.status == status)
    result = await db.execute(query.order_by(AgentInstructionProposal.created_at.desc()))
    return list(result.scalars())


async def get_proposal(
    db: AsyncSession, proposal_id: UUID, *, organization_id: UUID, agent_id: UUID
) -> AgentInstructionProposal | None:
    result = await db.execute(
        select(AgentInstructionProposal).where(
            AgentInstructionProposal.id == proposal_id,
            AgentInstructionProposal.organization_id == organization_id,
            AgentInstructionProposal.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


async def create_proposal(db: AsyncSession, **fields: Any) -> AgentInstructionProposal:
    proposal = AgentInstructionProposal(**fields)
    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def update_proposal(
    db: AsyncSession, *, proposal: AgentInstructionProposal, update_data: dict[str, Any]
) -> AgentInstructionProposal:
    for field, value in update_data.items():
        setattr(proposal, field, value)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def count_proposals_for_entry(
    db: AsyncSession, *, organization_id: UUID, ledger_entry_id: UUID
) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                AgentInstructionProposal.organization_id == organization_id,
                AgentInstructionProposal.ledger_entry_id == ledger_entry_id,
            )
        )
        or 0
    )
