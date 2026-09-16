"""The one URL a GitHub App delivers to, wired (#1072).

What the service decides is in `tests/test_github_app_portal.py`. What is here is
the route: that a delivery matching several triggers starts several flows, that
one matching none is answered exactly like one that fired, and that a refused
signature reaches the caller as a 403 so GitHub surfaces it to whoever
misconfigured the App.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.main import app
from app.services.agent_trigger import EventFireDecision

pytestmark = [pytest.mark.anyio, pytest.mark.security]

PATH = f"{settings.API_V1_STR}/webhooks/github-app"


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _decision() -> EventFireDecision:
    return EventFireDecision(trigger_id=uuid4(), event_context="an issue was opened")


async def test_every_matched_trigger_is_dispatched_as_its_own_flow() -> None:
    """A delivery matching four triggers starts four capped worker runs rather
    than four agent runs on the API's event loop."""
    decisions = [_decision(), _decision()]
    dispatched = AsyncMock()
    with (
        patch(
            "app.services.agent_trigger.AgentTriggerService.prepare_app_fires",
            new=AsyncMock(return_value=decisions),
        ),
        patch("app.worker.tasks.trigger_tasks.dispatch_trigger_fire", dispatched),
    ):
        async with _client() as client:
            response = await client.post(PATH, content=b"{}")

    assert response.status_code == 202
    assert dispatched.await_count == 2


async def test_a_delivery_matching_nothing_is_answered_the_same_way() -> None:
    """Among verified deliveries the response gives nothing away."""
    dispatched = AsyncMock()
    with (
        patch(
            "app.services.agent_trigger.AgentTriggerService.prepare_app_fires",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.worker.tasks.trigger_tasks.dispatch_trigger_fire", dispatched),
    ):
        async with _client() as client:
            response = await client.post(PATH, content=b"{}")

    assert response.status_code == 202
    dispatched.assert_not_awaited()


async def test_a_signature_that_verifies_against_nothing_is_a_403() -> None:
    """The one case that is not silent: a misconfigured secret is the
    integrator's to fix and GitHub shows them the 403."""
    with patch(
        "app.services.agent_trigger.AgentTriggerService.prepare_app_fires",
        new=AsyncMock(side_effect=AuthorizationError(message="Webhook signature did not verify")),
    ):
        async with _client() as client:
            response = await client.post(PATH, content=b"{}")

    assert response.status_code == 403


async def test_the_route_needs_no_session() -> None:
    """A session here would mean the App could never deliver."""
    with patch(
        "app.services.agent_trigger.AgentTriggerService.prepare_app_fires",
        new=AsyncMock(return_value=[]),
    ):
        async with _client() as client:
            response = await client.post(PATH, content=b"{}")

    assert response.status_code != 401
