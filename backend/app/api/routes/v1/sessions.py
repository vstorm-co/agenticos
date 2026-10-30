from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentSessionId, CurrentUser, SessionSvc
from app.schemas.session import LogoutAllResponse, SessionAppUpdate, SessionListResponse

router = APIRouter()


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: CurrentUser,
    current_session_id: CurrentSessionId,
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
    return await session_service.list_sessions(
        current_user.id, current_session_id=current_session_id, skip=skip, limit=limit
    )


@router.put("/current/app", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def record_session_app(
    app: SessionAppUpdate,
    current_user: CurrentUser,
    current_session_id: CurrentSessionId,
    session_service: SessionSvc,
) -> None:
    """Say which AgenticOS app - desktop or phone - this session runs in.

    The console sends it when it loads inside one, so the sessions list can
    name the app and its version rather than the webview's browser engine. 404
    for a request made with an API key, which has no session to label.
    """
    await session_service.record_app(current_session_id, current_user.id, app)


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
