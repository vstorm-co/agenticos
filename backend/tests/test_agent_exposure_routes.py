"""Tests for the exposure routes.

The handlers are thin by design - the decision is the service's - so what is
worth asserting is the part that is not delegation: that a write answers with
the row the section renders rather than the bare row the repository wrote, and
that it answers with the *right* one when an agent is available in several
places.

That the routes are authorized at all, and by the right mechanism, is asserted
through the real app in ``tests/api/test_platform_routes.py``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1.agent_exposures import (
    create_exposure,
    delete_exposure,
    list_exposure_targets,
    list_exposures,
    router,
    update_exposure,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_exposure import (
    ExposureCreate,
    ExposureRead,
    ExposureTarget,
    ExposureUpdate,
)

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value)


def _read(*, exposure_id: uuid.UUID, bot_id: uuid.UUID, name: str = "Acme") -> ExposureRead:
    return ExposureRead(
        id=exposure_id,
        agent_id=uuid.uuid4(),
        surface="slack",
        channel_bot_id=bot_id,
        channel_bot_name=name,
        is_active=True,
    )


class TestRouteShape:
    def test_targets_is_declared_before_the_exposure_id_routes(self):
        """Otherwise ``targets`` is parsed as an id and never reaches its handler.

        FastAPI matches in declaration order, so this is decided by where the
        decorator sits in the module - which nothing else would catch.
        """
        paths = [route.path for route in router.routes]
        assert paths.index("/{agent_id}/exposures/targets") < paths.index(
            "/{agent_id}/exposures/{exposure_id}"
        )


class TestReading:
    async def test_a_listing_reports_its_own_total(self):
        service = MagicMock(
            list_for_agent=AsyncMock(
                return_value=[_read(exposure_id=uuid.uuid4(), bot_id=uuid.uuid4())]
            )
        )

        result = await list_exposures(uuid.uuid4(), _CTX, service)

        assert result.total == 1

    async def test_the_picker_reports_its_own_total(self):
        service = MagicMock(
            targets=AsyncMock(
                return_value=[
                    ExposureTarget(id=uuid.uuid4(), platform="slack", name="Acme", is_active=True)
                ]
            )
        )

        result = await list_exposure_targets(uuid.uuid4(), _CTX, service)

        assert result.total == 1


class TestWriting:
    async def test_a_new_binding_answers_with_the_place_it_created(self):
        """Not the bare row: the section renders a place, which has a name.

        Returning what the repository wrote would leave the client holding two
        representations of one thing, and joining bot names itself - which needs
        a permission it does not have.
        """
        bot_id, other_bot_id = uuid.uuid4(), uuid.uuid4()
        service = MagicMock(
            create=AsyncMock(),
            list_for_agent=AsyncMock(
                return_value=[
                    _read(exposure_id=uuid.uuid4(), bot_id=other_bot_id, name="Telegram bot"),
                    _read(exposure_id=uuid.uuid4(), bot_id=bot_id, name="Acme Support"),
                ]
            ),
        )

        created = await create_exposure(
            uuid.uuid4(), ExposureCreate(channel_bot_id=bot_id), _CTX, service
        )

        assert created.channel_bot_name == "Acme Support"

    async def test_pausing_answers_with_the_binding_it_changed(self):
        """An agent on several bots makes "the first one" the wrong answer."""
        exposure_id = uuid.uuid4()
        service = MagicMock(
            update=AsyncMock(return_value=MagicMock(id=exposure_id)),
            list_for_agent=AsyncMock(
                return_value=[
                    _read(exposure_id=uuid.uuid4(), bot_id=uuid.uuid4(), name="Other"),
                    _read(exposure_id=exposure_id, bot_id=uuid.uuid4(), name="Acme Support"),
                ]
            ),
        )

        updated = await update_exposure(
            uuid.uuid4(), exposure_id, ExposureUpdate(is_active=False), _CTX, service
        )

        assert updated.id == exposure_id

    async def test_removing_a_binding_answers_with_no_content(self):
        agent_id, exposure_id = uuid.uuid4(), uuid.uuid4()
        service = MagicMock(delete=AsyncMock())

        response = await delete_exposure(agent_id, exposure_id, _CTX, service)

        assert response.status_code == 204
        service.delete.assert_awaited_once_with(_CTX, agent_id, exposure_id)
