"""What agents proposed changing about this organization's skills.

A proposal carries the full body an agent wrote, so reading one is reading a
candidate version of the organization's own instructions - and whoever may read
it is exactly whoever may accept it. The routes take `skills:edit`; the service
then lists and opens only the proposals for skills the caller may edit, with
grants, as applying one requires, and a proposal for a skill nobody has written
yet for anybody who may create skills - which is that same `skills:edit`. Any
other proposal answers 404, like any per-resource read.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, SkillProposalSvc, require
from app.core.permissions import Perm
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_proposal import SkillProposalList, SkillProposalRead

router = APIRouter()


@router.get("", response_model=SkillProposalList, dependencies=[Depends(require(Perm.SKILLS_EDIT))])
async def list_proposals(
    service: SkillProposalSvc,
    ctx: Auth,
    status: str | None = Query(
        None,
        description="Filter by state: pending, applied or discarded. Unset returns every one.",
    ),
) -> Any:
    """Every skill change an agent has proposed, newest first."""
    items = await service.list_read(ctx, status=status)
    return SkillProposalList(items=items, total=len(items))


@router.get(
    "/{proposal_id}",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def read_proposal(proposal_id: UUID, service: SkillProposalSvc, ctx: Auth) -> Any:
    return await service.read(ctx, proposal_id)


@router.post(
    "/{proposal_id}/apply",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def apply_proposal(
    proposal_id: UUID, decision: ProposalDecision, service: SkillProposalSvc, ctx: Auth
) -> Any:
    """Accept it: the skill is rewritten and its version moves.

    This reaches every agent bound to that skill on its next run, which is the
    point of skills and the reason this is a decision rather than a default.
    """
    return await service.apply(ctx, proposal_id, decision)


@router.post(
    "/{proposal_id}/discard",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def discard_proposal(
    proposal_id: UUID, decision: ProposalDecision, service: SkillProposalSvc, ctx: Auth
) -> Any:
    """Refuse it, keeping the record.

    Kept rather than deleted: an agent proposing the same edit repeatedly is
    saying something about the skill, and a deleted row makes that invisible.
    """
    return await service.discard(ctx, proposal_id, decision)
