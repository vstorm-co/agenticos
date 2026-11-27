"""Durable environment lookup boundaries use the actual owner and tenant rows."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import conversation_environment as environments
from tests.integration.test_conversation_environments import environment, identities

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_socket_identity_and_maintenance_only_return_live_owned_rows(db: AsyncSession):
    user, org, conversation, agent = await identities(db)
    row = await environments.add(db, environment(user, org, conversation, agent))
    assert await environments.for_worker(db, row.id) is row
    row.state = "ready"
    await db.flush()
    assert (
        await environments.for_socket(db, row.id, user_id=user.id, conversation_id=conversation.id)
        is row
    )
    assert (
        await environments.for_socket(db, row.id, user_id=uuid4(), conversation_id=conversation.id)
        is None
    )
    assert (
        await environments.for_socket(db, row.id, user_id=user.id, conversation_id=uuid4()) is None
    )
    assert await environments.active_for_maintenance(db, datetime.now(UTC)) == [row]
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    assert await environments.active_for_maintenance(db, datetime.now(UTC)) == []
