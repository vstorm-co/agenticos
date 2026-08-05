"""What agents proposed changing about this organization's skills.

Gated on `skills:edit` throughout, including the listing. That is deliberate and
it is not a permission being cautious: a proposal carries the full body an agent
wrote, so reading one is reading a candidate version of the organization's own
instructions - and whoever may read it is exactly whoever may accept it.

These are collection routes and per-resource routes in the same file, and both
carry the gate, which is the one place this repository's rule bends. A proposal
has no sharing model of its own - there are no grants on one, and
`resolve_access` has nothing to widen - so the gate cannot refuse somebody a
grant would have admitted.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, SkillProposalSvc, require
from app.core.permissions import Perm
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
    items = await service.list_proposals(ctx, status=status)
    return SkillProposalList(items=items, total=len(items))


@router.get(
    "/{proposal_id}",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def read_proposal(proposal_id: UUID, service: SkillProposalSvc, ctx: Auth) -> Any:
    return await service.get(ctx, proposal_id)


@router.post(
    "/{proposal_id}/apply",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def apply_proposal(proposal_id: UUID, service: SkillProposalSvc, ctx: Auth) -> Any:
    """Accept it: the skill is rewritten and its version moves.

    This reaches every agent bound to that skill on its next run, which is the
    point of skills and the reason this is a decision rather than a default.
    """
    return await service.apply(ctx, proposal_id)


@router.post(
    "/{proposal_id}/discard",
    response_model=SkillProposalRead,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def discard_proposal(proposal_id: UUID, service: SkillProposalSvc, ctx: Auth) -> Any:
    """Refuse it, keeping the record.

    Kept rather than deleted: an agent proposing the same edit repeatedly is
    saying something about the skill, and a deleted row makes that invisible.
    """
    return await service.discard(ctx, proposal_id)
