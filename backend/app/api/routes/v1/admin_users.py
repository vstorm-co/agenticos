from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import CurrentAppAdmin, DBSession, UserSvc
from app.core.audit import record_audit
from app.core.security import create_access_token
from app.schemas.user import AdminUserList, ImpersonateResponse, UserRead, UserUpdate

router = APIRouter()


@router.get("", response_model=AdminUserList)
async def list_users(
    _: CurrentAppAdmin,
    service: UserSvc,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = Query(None),
    sort_by: Literal["email", "full_name", "conversations", "created_at"] = Query(
        "created_at", description="Sort column"
    ),
    sort_dir: Literal["asc", "desc"] = Query("desc", description="Sort direction"),
) -> Any:
    return await service.admin_list_with_counts(
        skip=skip, limit=limit, search=search, sort_by=sort_by, sort_dir=sort_dir
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: UUID,
    _: CurrentAppAdmin,
    service: UserSvc,
) -> Any:
    return await service.get_by_id(user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    user_in: UserUpdate,
    request: Request,
    admin: CurrentAppAdmin,
    db: DBSession,
    service: UserSvc,
) -> Any:
    user = await service.update(user_id, user_in)
    # Which fields were set, never what they were set to. `UserUpdate` carries
    # `password`, so dumping the submitted body wrote the plaintext an
    # administrator typed into `app_admin_audit_logs.details`, where it sat in a
    # JSONB column for as long as the trail is kept (agenticos#412). The names
    # are what the trail is for; the values are on the row. `model_fields_set`
    # rather than `model_dump`, so the plaintext is not even built to be thrown
    # away.
    await record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.update",
        target_type="user",
        target_id=str(user_id),
        details={"fields": sorted(user_in.model_fields_set)},
        ip_address=request.client.host if request.client else None,
    )
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user(
    user_id: UUID,
    request: Request,
    admin: CurrentAppAdmin,
    db: DBSession,
    service: UserSvc,
) -> None:
    target = await service.get_by_id(user_id)
    await service.delete(user_id)
    await record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.delete",
        target_type="user",
        target_id=str(user_id),
        details={"email": target.email},
        ip_address=request.client.host if request.client else None,
    )


@router.post("/{user_id}/impersonate", response_model=ImpersonateResponse)
async def impersonate_user(
    request: Request,
    user_id: UUID,
    admin: CurrentAppAdmin,
    db: DBSession,
    service: UserSvc,
) -> Any:
    """Issue a short-lived (1h) access token to act as the target user.

    The token carries the administrator as an `act` claim, so every action taken
    with it is attributable to who was really acting and not only to the account
    they were acting as (#943).
    """
    target = await service.get_by_id(user_id)
    token = create_access_token(
        subject=str(target.id),
        expires_delta=timedelta(hours=1),
        act=str(admin.id),
    )
    await record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.impersonate",
        target_type="user",
        target_id=str(target.id),
        details={"target_email": target.email, "expires_in": 3600},
        ip_address=request.client.host if request.client else None,
    )
    return ImpersonateResponse(
        access_token=token,
        token_type="bearer",
        impersonated_user_id=str(target.id),
        impersonated_by=str(admin.id),
        expires_in=3600,
    )
