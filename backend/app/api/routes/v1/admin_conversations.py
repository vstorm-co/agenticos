from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ConversationSvc, CurrentAppAdmin
from app.schemas.conversation import (
    ConversationReadWithMessages,
)
from app.schemas.conversation_share import AdminConversationList
from app.services.conversation import UNSCOPED

router = APIRouter()


@router.get("", response_model=AdminConversationList)
async def admin_list_conversations(
    service: ConversationSvc,
    _: CurrentAppAdmin,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
    search: str | None = Query(default=None, description="Search by title"),
    user_id: UUID | None = Query(default=None, description="Filter by user ID"),
    agent_id: UUID | None = Query(default=None, description="Only threads this agent answered in"),
    status: Literal["active", "archived", "all"] = Query(
        "active", description="Filter by archival status"
    ),
    sort_by: Literal["title", "owner", "messages", "created_at", "updated_at"] = Query(
        "updated_at", description="Sort column"
    ),
    sort_dir: Literal["asc", "desc"] = Query("desc", description="Sort direction"),
) -> Any:
    """List all conversations across all users (admin only)."""
    return await service.admin_list_with_users(
        skip=skip,
        limit=limit,
        search=search,
        user_id=user_id,
        agent_id=agent_id,
        include_archived=status == "all",
        archived_only=status == "archived",
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/{conversation_id}", response_model=ConversationReadWithMessages)
async def admin_get_conversation(
    conversation_id: UUID,
    service: ConversationSvc,
    _: CurrentAppAdmin,
) -> Any:
    """Get any conversation with messages (admin read-only access).

    The one deliberate cross-tenant read: reading across organizations is what
    this route is for, and `CurrentAppAdmin` is what makes that acceptable.
    """
    return await service.get_conversation_with_messages(conversation_id, organization_id=UNSCOPED)
