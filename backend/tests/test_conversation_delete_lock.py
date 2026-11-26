"""Deletion takes the authorized tenant's refreshed parent before child cleanup."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.conversation import Conversation
from app.repositories import conversation_repo, conversation_share_repo
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("outcome", ["owned", "foreign-tenant", "missing", "reassigned"])
async def test_deletion_rechecks_current_authority_after_locking(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    user_id, org_id, conversation_id = uuid4(), uuid4(), uuid4()
    row = Conversation(id=conversation_id, organization_id=org_id, user_id=user_id, origin="chat")
    if outcome == "foreign-tenant":
        row.organization_id = uuid4()
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_share_repo, "get_share", AsyncMock(return_value=None))

    async def acquire(_db: AsyncSession, **_kwargs: object) -> Conversation | None:
        if outcome == "missing":
            return None
        if outcome == "reassigned":
            row.user_id = uuid4()
        return row

    lock = AsyncMock(side_effect=acquire)
    monkeypatch.setattr(conversation_repo, "lock_for_deletion", lock)
    service = ConversationService(AsyncMock(spec=AsyncSession))
    ctx = AuthContext(user_id=user_id, organization_id=org_id, role=OrgRoleName.OWNER)
    if outcome == "owned":
        assert (
            await service.lock_for_deletion(
                conversation_id, organization_id=org_id, user_id=user_id, ctx=ctx
            )
            is row
        )
    else:
        with pytest.raises(NotFoundError):
            await service.lock_for_deletion(
                conversation_id, organization_id=org_id, user_id=user_id, ctx=ctx
            )
    if outcome == "foreign-tenant":
        lock.assert_not_awaited()
    else:
        assert lock.await_args.kwargs == {
            "conversation_id": conversation_id,
            "organization_id": org_id,
        }
