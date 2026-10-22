"""Context file changes the authoring assistant proposed, waiting for a person to decide.

Every route needs `context:edit`; which files a caller reaches inside that is
decided per file by the service, so a grant on one file is enough for it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, ContextProposalSvc, require
from app.core.permissions import Perm
from app.schemas.context_proposal import ContextProposalList, ContextProposalRead

router = APIRouter()


@router.get(
    "", response_model=ContextProposalList, dependencies=[Depends(require(Perm.CONTEXT_EDIT))]
)
async def list_context_changes(
    service: ContextProposalSvc,
    ctx: Auth,
    status: str | None = Query(None, description="`pending`, `applied` or `discarded`"),
) -> Any:
    """The proposed changes to the files the caller may see, newest first."""
    return await service.list_read(ctx, status=status)


@router.get(
    "/{proposal_id}",
    response_model=ContextProposalRead,
    dependencies=[Depends(require(Perm.CONTEXT_EDIT))],
)
async def read_context_change(proposal_id: UUID, service: ContextProposalSvc, ctx: Auth) -> Any:
    """One proposed change, beside the file as it stands now."""
    return await service.read(ctx, proposal_id)


@router.post(
    "/{proposal_id}/apply",
    response_model=ContextProposalRead,
    dependencies=[Depends(require(Perm.CONTEXT_EDIT))],
)
async def apply_context_change(proposal_id: UUID, service: ContextProposalSvc, ctx: Auth) -> Any:
    """Write the proposed body to the file. Live for every agent bound to it."""
    return await service.apply(ctx, proposal_id)


@router.post(
    "/{proposal_id}/discard",
    response_model=ContextProposalRead,
    dependencies=[Depends(require(Perm.CONTEXT_EDIT))],
)
async def discard_context_change(proposal_id: UUID, service: ContextProposalSvc, ctx: Auth) -> Any:
    """Refuse the change, keeping the record of what was proposed."""
    return await service.discard(ctx, proposal_id)
