"""The app-admin announcement composer (#1598, Decision 5).

`CurrentAppAdmin` alone, never a `Perm` - every entry in the permission
catalog is resolved against one organization, and none of them can express
"every organization". An organization admin gets nothing new here.
"""

from typing import Any

from fastapi import APIRouter, status

from app.api.deps import AnnouncementSvc, CurrentAppAdmin
from app.schemas.announcement import AnnouncementCreate, AnnouncementRead

router = APIRouter()


@router.post("", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
async def send_announcement(
    data: AnnouncementCreate, service: AnnouncementSvc, admin: CurrentAppAdmin
) -> Any:
    """Resolve the audience, write it, fan it out and audit it - one send."""
    result = await service.send(
        actor_user_id=admin.id,
        body=data.body,
        organizations=data.organizations,
        role=data.role.value if data.role else None,
        channels=data.channels,
    )
    return AnnouncementRead.from_row(result.announcement, recipient_count=result.recipient_count)
