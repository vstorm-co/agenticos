"""What the platform proposed to the signed-in person, and their answers (#2301).

Under `/me` because a suggestion is always one person's: there is no view of
anybody else's. Console only - a card in the chat is the one place they are read.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Auth, SuggestionSvc
from app.schemas.suggestion import SuggestionList, SuggestionRead

router = APIRouter()


@router.get("", response_model=SuggestionList)
async def list_my_suggestions(service: SuggestionSvc, ctx: Auth) -> Any:
    """The person's open suggestions in this organization, newest first."""
    items = await service.list_mine(ctx)
    return SuggestionList(
        items=[SuggestionRead.model_validate(item) for item in items], total=len(items)
    )


@router.post("/{suggestion_id}/accept", response_model=SuggestionRead)
async def accept_suggestion(suggestion_id: UUID, service: SuggestionSvc, ctx: Auth) -> Any:
    """Take a suggestion: a profile update is saved, a role pack starts installing."""
    return await service.accept(ctx, suggestion_id)


@router.post("/{suggestion_id}/dismiss", response_model=SuggestionRead)
async def dismiss_suggestion(suggestion_id: UUID, service: SuggestionSvc, ctx: Auth) -> Any:
    """Decline a suggestion; the same one is not proposed again."""
    return await service.dismiss(ctx, suggestion_id)
