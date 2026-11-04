"""What the platform proposed to the signed-in person, and their answers (#2301).

Under `/me` because a suggestion is always one person's: there is no view of
anybody else's. Console only - a card in the chat is the one place they are read.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Auth, SuggestionSvc
from app.schemas.suggestion import PersonalStarters, SuggestionList, SuggestionRead

router = APIRouter()


@router.get("", response_model=SuggestionList)
async def list_my_suggestions(
    service: SuggestionSvc,
    ctx: Auth,
    decided: bool = Query(
        False, description="Include the ones already accepted or dismissed, newest first."
    ),
) -> Any:
    """The person's open suggestions in this organization, newest first."""
    items = await service.list_mine(ctx, decided=decided)
    return SuggestionList(
        items=[SuggestionRead.model_validate(item) for item in items], total=len(items)
    )


@router.get("/starters", response_model=PersonalStarters)
async def my_personal_starters(service: SuggestionSvc, ctx: Auth) -> Any:
    """The first messages the nightly look wrote for the person in this organization."""
    return PersonalStarters(items=await service.starters(ctx))


@router.post("/{suggestion_id}/accept", response_model=SuggestionRead)
async def accept_suggestion(suggestion_id: UUID, service: SuggestionSvc, ctx: Auth) -> Any:
    """Take a suggestion: a profile update is saved, a role pack starts installing."""
    return await service.accept(ctx, suggestion_id)


@router.post("/{suggestion_id}/dismiss", response_model=SuggestionRead)
async def dismiss_suggestion(suggestion_id: UUID, service: SuggestionSvc, ctx: Auth) -> Any:
    """Decline a suggestion; the same one is not proposed again."""
    return await service.dismiss(ctx, suggestion_id)


@router.post("/{suggestion_id}/restore", response_model=SuggestionRead)
async def restore_suggestion(suggestion_id: UUID, service: SuggestionSvc, ctx: Auth) -> Any:
    """Bring back a dismissed suggestion, to answer again."""
    return await service.restore(ctx, suggestion_id)
