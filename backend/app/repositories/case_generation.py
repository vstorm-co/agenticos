"""Case generation repository (PostgreSQL async).

Generations and the proposals they drafted. A proposal is only ever read while
it waits: a decision takes it out of the table (:func:`take_proposals`), and the
generation it came from counts what happened to it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.case_generation import CaseGeneration, CaseProposal


async def create_generation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    dataset_id: UUID,
    agent_id: UUID,
    requested_by_user_id: UUID | None,
    sources: list[str],
    requested_count: int,
    auto_accept: bool = False,
    created_by_api_key_id: UUID | None = None,
    generator_agent_id: UUID | None = None,
) -> CaseGeneration:
    generation = CaseGeneration(
        organization_id=organization_id,
        dataset_id=dataset_id,
        agent_id=agent_id,
        generator_agent_id=generator_agent_id,
        requested_by_user_id=requested_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        sources=sources,
        requested_count=requested_count,
        auto_accept=auto_accept,
    )
    db.add(generation)
    await db.flush()
    await db.refresh(generation)
    return generation


async def get_generation(
    db: AsyncSession, generation_id: UUID, *, organization_id: UUID
) -> CaseGeneration | None:
    result = await db.execute(
        select(CaseGeneration).where(
            CaseGeneration.id == generation_id,
            CaseGeneration.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_generations(
    db: AsyncSession, dataset_id: UUID, *, organization_id: UUID, limit: int
) -> list[CaseGeneration]:
    """The dataset's newest generations first."""
    result = await db.execute(
        select(CaseGeneration)
        .where(
            CaseGeneration.dataset_id == dataset_id,
            CaseGeneration.organization_id == organization_id,
        )
        .order_by(CaseGeneration.created_at.desc(), CaseGeneration.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def finish_generation(
    db: AsyncSession,
    generation: CaseGeneration,
    *,
    status: str,
    finished_at: datetime,
    error: str | None = None,
    run_id: UUID | None = None,
    proposed_count: int = 0,
    unreadable_count: int = 0,
    rejected_count: int = 0,
) -> CaseGeneration:
    generation.status = status
    generation.finished_at = finished_at
    generation.error = error
    generation.run_id = run_id
    generation.proposed_count = proposed_count
    generation.unreadable_count = unreadable_count
    generation.rejected_count = rejected_count
    await db.flush()
    await db.refresh(generation)
    return generation


async def add_proposals(db: AsyncSession, proposals: Sequence[CaseProposal]) -> None:
    db.add_all(proposals)
    await db.flush()


async def list_proposals(
    db: AsyncSession,
    dataset_id: UUID,
    *,
    organization_id: UUID,
    generation_id: UUID | None = None,
    without_origin: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CaseProposal], int]:
    """A page of the proposals waiting on one dataset, with the total.

    Oldest generation first, and within one in the order the generator drafted them.
    `without_origin` leaves out the proposals drafted from that source.
    """
    where = [
        CaseProposal.dataset_id == dataset_id,
        CaseProposal.organization_id == organization_id,
    ]
    if without_origin is not None:
        where.append(CaseProposal.origin != without_origin)
    if generation_id is not None:
        where.append(CaseProposal.generation_id == generation_id)
    total = await db.scalar(select(func.count(CaseProposal.id)).where(*where))
    result = await db.execute(
        select(CaseProposal)
        .where(*where)
        .order_by(
            CaseProposal.created_at,
            CaseProposal.generation_id,
            CaseProposal.position,
            CaseProposal.id,
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total or 0


async def count_pending(
    db: AsyncSession,
    dataset_ids: Sequence[UUID],
    *,
    organization_id: UUID,
    without_origin: str | None = None,
    only_origin: str | None = None,
    generation_id: UUID | None = None,
) -> dict[UUID, int]:
    """How many proposals wait on each dataset; a dataset with none is absent.

    `without_origin` leaves out the proposals drafted from that source, and
    `only_origin` counts only those. `generation_id` counts only what that
    generation drafted.
    """
    if not dataset_ids:
        return {}
    where = [
        CaseProposal.dataset_id.in_(dataset_ids),
        CaseProposal.organization_id == organization_id,
    ]
    if without_origin is not None:
        where.append(CaseProposal.origin != without_origin)
    if only_origin is not None:
        where.append(CaseProposal.origin == only_origin)
    if generation_id is not None:
        where.append(CaseProposal.generation_id == generation_id)
    result = await db.execute(
        select(CaseProposal.dataset_id, func.count(CaseProposal.id))
        .where(*where)
        .group_by(CaseProposal.dataset_id)
    )
    return dict(result.all())


async def take_proposals(
    db: AsyncSession,
    dataset_id: UUID,
    ids: Sequence[UUID],
    *,
    organization_id: UUID,
    without_origin: str | None = None,
) -> list[CaseProposal]:
    """Remove these proposals from the queue and return what they held.

    A `DELETE ... RETURNING`, so of two reviewers deciding the same proposal at
    once exactly one gets it back: the other's delete finds the row gone and
    returns nothing for it. Returned in the order the ids were given, each once;
    an id that is not waiting on this dataset, or was drafted from
    `without_origin`, is simply absent and stays waiting.
    """
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    where = [
        CaseProposal.id.in_(ids),
        CaseProposal.dataset_id == dataset_id,
        CaseProposal.organization_id == organization_id,
    ]
    if without_origin is not None:
        where.append(CaseProposal.origin != without_origin)
    result = await db.execute(delete(CaseProposal).where(*where).returning(CaseProposal))
    taken = {proposal.id: proposal for proposal in result.scalars().all()}
    await db.flush()
    return [taken[proposal_id] for proposal_id in ids if proposal_id in taken]


async def count_decisions(
    db: AsyncSession,
    decided: dict[UUID, int],
    *,
    organization_id: UUID,
    accepted: bool,
) -> None:
    """Add decided proposals to the counts of the generations that drafted them."""
    column = CaseGeneration.accepted_count if accepted else CaseGeneration.dismissed_count
    for generation_id, count in decided.items():
        values: dict[str, Any] = {column.key: column + count}
        await db.execute(
            update(CaseGeneration)
            .where(
                CaseGeneration.id == generation_id,
                CaseGeneration.organization_id == organization_id,
            )
            .values(**values)
        )
    await db.flush()
