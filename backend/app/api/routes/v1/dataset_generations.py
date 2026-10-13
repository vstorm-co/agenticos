"""Generated dataset cases - drafting them, and deciding what was drafted.

Every route acts on one dataset and delegates to `CaseGenerationService`, which
resolves the caller's `datasets:edit` on that row; no role gate sits in front,
because a role gate cannot see the grant that lets a Viewer edit one dataset.

Nothing a generator drafts reaches the dataset until a person accepts it here,
and one Accept is one new version.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Auth, CaseGenerationSvc
from app.schemas.case_generation import (
    CaseGenerationList,
    CaseProposalAccept,
    CaseProposalDismiss,
    CaseProposalList,
)
from app.schemas.dataset import DatasetVersionRead

router = APIRouter()


@router.get("/{dataset_id}/generations", response_model=CaseGenerationList)
async def list_case_generations(
    dataset_id: UUID,
    service: CaseGenerationSvc,
    ctx: Auth,
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """The dataset's newest generations: how each went, and the generator run behind it."""
    return await service.list_generations(ctx, dataset_id, limit=limit)


@router.get("/{dataset_id}/proposals", response_model=CaseProposalList)
async def list_case_proposals(
    dataset_id: UUID,
    service: CaseGenerationSvc,
    ctx: Auth,
    generation_id: UUID | None = Query(None, description="Only what one generation drafted"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Drafted cases waiting for a decision, in the order they were drafted."""
    return await service.list_proposals(
        ctx, dataset_id, generation_id=generation_id, skip=skip, limit=limit
    )


@router.post(
    "/{dataset_id}/proposals/accept",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def accept_case_proposals(
    dataset_id: UUID, data: CaseProposalAccept, service: CaseGenerationSvc, ctx: Auth
) -> Any:
    """Accept drafted cases, each as drafted or as edited, into one new version.

    A draft somebody else decided meanwhile is skipped; when none is left to
    accept, the answer is 404.
    """
    return await service.accept(ctx, dataset_id, data)


@router.post(
    "/{dataset_id}/proposals/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def dismiss_case_proposals(
    dataset_id: UUID, data: CaseProposalDismiss, service: CaseGenerationSvc, ctx: Auth
) -> None:
    """Dismiss drafted cases. Nothing of them is kept, and the dataset does not change."""
    await service.dismiss(ctx, dataset_id, data)
