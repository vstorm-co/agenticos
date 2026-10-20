"""The member a run acts for, read again when a tool acts for them.

A capability that does something in the organization on a member's behalf - a
table write, a workflow started - acts as who they are *now*: their membership
and role as the organization holds them at the moment of the call, not as they
were when the run began. Someone removed mid-conversation stops being able to
act through it at once.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.services.access import member_context


async def acting_member(
    db: AsyncSession, organization_id: UUID | None, user_id: str | None
) -> AuthContext | None:
    """The member this run acts for, with the role they hold now - or `None` when the
    run acts for no member, or they are no longer an active one."""
    if organization_id is None or user_id is None:
        return None
    try:
        member_id = UUID(user_id)
    except ValueError:
        return None
    return await member_context(db, organization_id=organization_id, user_id=member_id)
