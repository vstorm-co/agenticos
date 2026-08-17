"""Tests for the trigger routes.

The handlers are thin by design - the decision is the service's - so what is
worth asserting is only the part that is not delegation: that a listing reports
its own total, that a write answers with what the service returned, and that a
delete answers no-content while delegating with the ids from the path. That the
routes are authorized at all, and by resolving `agents:run` per row rather than a
role gate, is proven through the real app in `tests/api/test_platform_routes.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.v1.agent_triggers import (
    create_trigger,
    delete_trigger,
    list_org_triggers,
    list_portal_targets,
    list_trigger_portals,
    list_triggers,
    run_trigger_now,
    update_trigger,
)
from app.api.routes.v1.trigger_webhooks import ingest_trigger_event
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_trigger import TriggerCreate, TriggerRead, TriggerUpdate
from app.services.agent_trigger import EventFireDecision

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value)


def _read() -> TriggerRead:
    return TriggerRead(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        is_active=True,
        trigger_type="schedule",
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


async def test_the_portal_catalog_maps_every_portal_and_its_presets():
    result = await list_trigger_portals()
    assert result.total == len(result.items) > 0
    github = next(portal for portal in result.items if portal.key == "github")
    assert github.delivery == "auto_webhook"
    assert github.connection_catalog_key == "github"
    assert github.target_kind == "repo"
    opened = next(preset for preset in github.presets if preset.key == "issue_opened")
    assert opened.target_required is True


async def test_the_org_listing_reports_its_own_total():
    service = MagicMock(list_for_organization=AsyncMock(return_value=([_read(), _read()], 2)))
    result = await list_org_triggers(_CTX, service, skip=0, limit=50)
    assert result.total == 2
    assert len(result.items) == 2


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


async def test_running_now_answers_with_what_the_service_returned():
    fired = _read()
    service = MagicMock(run_now=AsyncMock(return_value=fired))
    agent_id, trigger_id = uuid.uuid4(), uuid.uuid4()
    result = await run_trigger_now(agent_id, trigger_id, _CTX, service)
    assert result is fired
    service.run_now.assert_awaited_once_with(_CTX, agent_id, trigger_id)


async def test_removing_a_schedule_answers_with_no_content():
    agent_id, trigger_id = uuid.uuid4(), uuid.uuid4()
    service = MagicMock(delete=AsyncMock())
    response = await delete_trigger(agent_id, trigger_id, _CTX, service)
    assert response.status_code == 204
    service.delete.assert_awaited_once_with(_CTX, agent_id, trigger_id)


def _request(body: bytes, headers: dict[str, str]) -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = headers
    return request


async def test_a_webhook_hands_the_raw_body_and_headers_to_the_service():
    """The signature covers the exact bytes, so the route must pass the raw body
    through untouched - not a re-parsed and re-serialized copy."""
    service = MagicMock(prepare_event_fire=AsyncMock(return_value=None))
    body = b'{"action": "opened"}'
    request = _request(body, {"x-hub-signature-256": "sha256=abc"})
    await ingest_trigger_event("github", uuid.uuid4(), request, service)
    assert service.prepare_event_fire.call_args.kwargs["body"] == body
    assert service.prepare_event_fire.call_args.kwargs["headers"] == {
        "x-hub-signature-256": "sha256=abc"
    }


async def test_a_webhook_with_nothing_to_do_accepts_without_firing():
    service = MagicMock(prepare_event_fire=AsyncMock(return_value=None))
    with patch("app.api.routes.v1.trigger_webhooks.fire_trigger") as fired:
        response = await ingest_trigger_event("github", uuid.uuid4(), _request(b"{}", {}), service)
    assert response.status_code == 202
    fired.assert_not_called()


async def test_a_webhook_that_matches_dispatches_the_fire_in_the_background():
    """The fire runs after the 202 goes back, so a provider's timeout never
    catches an agent run - the same shape the channel webhooks use."""
    decision = EventFireDecision(trigger_id=uuid.uuid4(), event_context="ISSUE #7")
    service = MagicMock(prepare_event_fire=AsyncMock(return_value=decision))
    fired = AsyncMock()
    with patch("app.api.routes.v1.trigger_webhooks.fire_trigger", fired):
        response = await ingest_trigger_event(
            "github", decision.trigger_id, _request(b'{"action": "opened"}', {}), service
        )
        await asyncio.sleep(0)  # let the created task run
    assert response.status_code == 202
    fired.assert_awaited_once_with(decision.trigger_id, event_context="ISSUE #7")


async def test_portal_targets_maps_the_adapters_answer():
    from app.services.portals import PortalTarget

    service = MagicMock(
        list_portal_targets=AsyncMock(return_value=[PortalTarget(id="acme/api", label="acme/api")])
    )
    result = await list_portal_targets("github", _CTX, service, connection_id=uuid.uuid4())
    assert result.total == 1
    assert result.items[0].id == "acme/api"
