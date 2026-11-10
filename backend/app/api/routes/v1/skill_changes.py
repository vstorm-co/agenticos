"""What agents proposed changing about this organization's skills.

Gated on `skills:edit` throughout, including the listing. That is deliberate and
it is not a permission being cautious: a proposal carries the full body an agent
wrote, so reading one is reading a candidate version of the organization's own
instructions - and whoever may read it is exactly whoever may accept it.

The gate is only the first half. Below it, `SkillProposalService` lists and reads
a proposal only for a caller who may edit the skill it targets, as
`resolve_access` decides with grants, and reports any other as missing (#2422).
A proposal for a new skill has no skill to ask and is decided by whoever holds
`skills:edit` at all.

These are collection routes and per-resource routes in the same file, and both
carry the gate, which is the one place this repository's rule bends: a proposal
has no sharing model of its own - there are no grants on one - so the gate
admits the kind of caller and the service narrows to the rows.
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
