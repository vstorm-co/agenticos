from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import CurrentAppAdmin, DBSession, ImpersonationSvc, UserSvc
from app.core.audit import record_audit
from app.schemas.user import (
    AdminUserDetail,
    AdminUserList,
    ImpersonateResponse,
    UserRead,
    UserUpdate,
)

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


@router.get("/{user_id}/detail", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: UUID,
    _: CurrentAppAdmin,
    service: UserSvc,
) -> Any:
    """Where this person has access, when they were last here, what is open.

    Its own route rather than fields on `GET /{user_id}`, because it is a view
    assembled from three tables and a user is read in a dozen places that need
    none of it. What it answers is what a deployment admin is about to decide
    on: an account with no membership anywhere and no session in three months
    is a different decision from one that owns two organizations (#942).
    """
    return await service.admin_detail(user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    user_in: UserUpdate,
    request: Request,
    admin: CurrentAppAdmin,
    db: DBSession,
    service: UserSvc,
) -> Any:
    user = await service.admin_update(user_id, user_in, acting_admin_id=admin.id)
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
    await service.admin_delete(user_id, acting_admin_id=admin.id)
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
    impersonation: ImpersonationSvc,
) -> Any:
    """Start acting as the target user, for an hour or until it is ended.

    The answer is a session, not a bare credential: the token names a row in
    `sessions` and is refused the moment that row is ended, so an impersonation
    stops when the administrator ends it, when the target signs out everywhere or
    resets their password, or when the hour is up - whichever is first (#1044).
    It carries the administrator as an `act` claim, so every action taken with it
    is attributable to who was really acting (#943).
    """
    return await impersonation.start(
        admin=admin,
        target_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
