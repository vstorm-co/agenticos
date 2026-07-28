from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, SessionSvc
from app.schemas.session import LogoutAllResponse, SessionListResponse

router = APIRouter()


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: CurrentUser,
    session_service: SessionSvc,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
) -> Any:
    """One page of the caller's signed-in devices.

    Paged because nothing bounds how many sessions a user accumulates: every
    sign-in from every browser adds a row, and they live for the refresh token's
    lifetime. The default page is small because this renders as a list of cards
    in a settings section, not a table.
    """
    return await session_service.list_sessions(current_user.id, skip=skip, limit=limit)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout_session(
    session_id: UUID,
    current_user: CurrentUser,
    session_service: SessionSvc,
) -> None:
    await session_service.logout_session(session_id, current_user.id)


@router.delete("", response_model=LogoutAllResponse)
async def logout_all_sessions(
    current_user: CurrentUser,
    session_service: SessionSvc,
) -> Any:
    count = await session_service.logout_all_sessions(current_user.id)
    return LogoutAllResponse(
        message="Successfully logged out from all sessions",
        sessions_logged_out=count,
    )
