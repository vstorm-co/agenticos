"""Tests for the trigger routes.

The handlers are thin by design - the decision is the service's - so what is
worth asserting is only the part that is not delegation: that a listing reports
its own total, that a write answers with what the service returned, and that a
delete answers no-content while delegating with the ids from the path. That the
routes are authorized at all, and by resolving `agents:run` per row rather than a
role gate, is proven through the real app in `tests/api/test_platform_routes.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1.agent_triggers import (
    create_trigger,
    delete_trigger,
    list_triggers,
    update_trigger,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_trigger import TriggerCreate, TriggerRead, TriggerUpdate

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value)


def _read() -> TriggerRead:
    return TriggerRead(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        is_active=True,
        schedule_kind="interval",
        interval_seconds=300,
        prompt="run",
        next_fire_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_a_listing_reports_its_own_total():
    service = MagicMock(list_for_agent=AsyncMock(return_value=[_read(), _read()]))
    result = await list_triggers(uuid.uuid4(), _CTX, service)
    assert result.total == 2


async def test_creating_answers_with_what_the_service_returned():
    created = _read()
    service = MagicMock(create=AsyncMock(return_value=created))
    result = await create_trigger(
        uuid.uuid4(), TriggerCreate(prompt="run", interval_seconds=300), _CTX, service
    )
    assert result is created


async def test_updating_answers_with_what_the_service_returned():
    updated = _read()
    service = MagicMock(update=AsyncMock(return_value=updated))
    result = await update_trigger(
        uuid.uuid4(), uuid.uuid4(), TriggerUpdate(is_active=False), _CTX, service
    )
    assert result is updated


async def test_removing_a_schedule_answers_with_no_content():
    agent_id, trigger_id = uuid.uuid4(), uuid.uuid4()
    service = MagicMock(delete=AsyncMock())
    response = await delete_trigger(agent_id, trigger_id, _CTX, service)
    assert response.status_code == 204
    service.delete.assert_awaited_once_with(_CTX, agent_id, trigger_id)
