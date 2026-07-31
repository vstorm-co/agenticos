"""Tests for the environment routes.

The handlers are thin by design - the decision is the service's - so what is
worth asserting is the part that is not delegation: a write answers with the
row the section renders (version number included), and with the *right* row
when an agent has several environments.

That the routes are authorized at all, and by the right mechanism, is asserted
through the real app in `tests/api/test_platform_routes.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1.agent_environments import (
    create_environment,
    delete_environment,
    list_environments,
    update_environment,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_environment import (
    EnvironmentCreate,
    EnvironmentRead,
    EnvironmentUpdate,
)

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value)


def _read(
    *, environment_id: uuid.UUID | None = None, name: str = "production", version: int = 1
) -> EnvironmentRead:
    return EnvironmentRead(
        id=environment_id or uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name=name,
        version_id=uuid.uuid4(),
        version=version,
        is_default=name == "production",
        created_at=datetime.now(UTC),
    )


class TestReading:
    async def test_a_listing_reports_its_own_total(self):
        service = MagicMock(list_for_agent=AsyncMock(return_value=[_read(), _read(name="dev")]))

        result = await list_environments(uuid.uuid4(), _CTX, service)

        assert result.total == 2


class TestWriting:
    async def test_a_create_answers_with_the_row_it_made_not_the_first_row(self):
        """The response is re-read through the listing so it carries the version
        number - and it has to be the created environment's row, not the
        default that happens to sort first."""
        service = MagicMock(
            create=AsyncMock(),
            list_for_agent=AsyncMock(return_value=[_read(), _read(name="dev", version=4)]),
        )

        result = await create_environment(
            uuid.uuid4(), EnvironmentCreate(name="dev"), _CTX, service
        )

        assert (result.name, result.version) == ("dev", 4)

    async def test_an_update_answers_with_the_updated_row(self):
        environment_id = uuid.uuid4()
        service = MagicMock(
            update=AsyncMock(),
            list_for_agent=AsyncMock(
                return_value=[
                    _read(),
                    _read(environment_id=environment_id, name="dev", version=12),
                ]
            ),
        )

        result = await update_environment(
            uuid.uuid4(),
            environment_id,
            EnvironmentUpdate(version_id=uuid.uuid4()),
            _CTX,
            service,
        )

        assert (result.id, result.version) == (environment_id, 12)

    async def test_a_delete_answers_with_nothing(self):
        service = MagicMock(delete=AsyncMock())

        assert await delete_environment(uuid.uuid4(), uuid.uuid4(), _CTX, service) is None
        service.delete.assert_awaited_once()
