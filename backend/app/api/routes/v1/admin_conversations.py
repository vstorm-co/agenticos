from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ConversationSvc, CurrentAppAdmin
from app.schemas.conversation_share import AdminConversationList

router = APIRouter()


@router.get("", response_model=AdminConversationList)
async def admin_list_conversations(
    service: ConversationSvc,
    _: CurrentAppAdmin,
    user_id: UUID = Query(description="Whose threads to list"),
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """What one account has been talking about, for the admin user drawer.

    All that is left of the deployment-wide conversation browser, which was
    removed in favour of Activity: run history answers "what happened" with the
    cost, the model, the trace and what the model was handed beside it, where
    this answered it with a title and a message count. What Activity cannot
    answer is *across tenants*, and this is the narrowed form of that - one named
    user's own threads, listed and never read.

    `user_id` is required for the same reason. Unfiltered, this was a listing of
    every conversation in the deployment, and nothing asks for that any more.

    The bodies are unreachable now: the route that returned one conversation with
    its messages went with the browser, and it was the one deliberate
    cross-tenant read in the product.
    """
    return await service.admin_list_with_users(skip=skip, limit=limit, user_id=user_id)
