"""What needs the caller's attention, and settling it once (#2575)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, OutcomeSvc, key_needs
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.outcome import OutcomeList, OutcomeRead, OutcomeSettle

router = APIRouter(dependencies=[PUBLIC, Depends(key_needs(Perm.AGENTS_RUN))])


@router.get("", response_model=OutcomeList)
async def list_outcomes(
    service: OutcomeSvc,
    ctx: Auth,
    open_only: bool = Query(default=True),
    conversation_id: UUID | None = Query(default=None),
    include_source: bool = Query(
        default=False,
        description="Include source item/revision addresses for continuing a routine draft.",
    ),
) -> Any:
    """The caller's own outcomes, open ones by default, optionally those from one chat.

    No role gate: an outcome is addressed to one person and never listed to anybody else.
    """
    items = await service.list_mine(ctx, open_only=open_only, conversation_id=conversation_id)
    sources = await service.finding_sources(ctx, items) if include_source else {}
    return OutcomeList(
        items=[
            OutcomeRead.model_validate(item).model_copy(update={"source": sources.get(item.id)})
            for item in items
        ]
    )


@router.post("/{outcome_id}/settle", response_model=OutcomeRead)
async def settle_outcome(
    outcome_id: UUID, data: OutcomeSettle, service: OutcomeSvc, ctx: Auth
) -> Any:
    """Acknowledge, resolve or mute one outcome; every place it was shown follows."""
    return await service.settle(ctx, outcome_id, data.action, via=data.via)
