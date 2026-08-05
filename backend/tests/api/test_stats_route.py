"""The group_by dispatch on GET /stats/usage.

The gate (org vs own scope) is proven through the real service in
tests/api/test_platform_routes.py; here the service is stubbed and what is
under test is the route's own contract: which question each parameter shape
dispatches to, and that a version comparison without an agent is refused
rather than answered for some agent the caller never named.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.stats import UsageStats

pytestmark = pytest.mark.anyio


def _service() -> MagicMock:
    envelope = UsageStats(from_date=date(2026, 7, 1), to_date=date(2026, 7, 31), scope="org")
    service = MagicMock()
    service.usage = AsyncMock(return_value=envelope)
    service.usage_by_version = AsyncMock(return_value=envelope)
    service.usage_by_user = AsyncMock(return_value=envelope)
    return service


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_stats_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_no_group_by_asks_the_composed_question():
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"from": "2026-07-01"})

    assert resp.status_code == 200
    assert service.usage.call_args.kwargs["from_date"] == date(2026, 7, 1)
    service.usage_by_version.assert_not_called()


async def test_group_by_version_asks_the_version_question_for_that_agent():
    service = _service()
    agent_id = uuid4()

    async with _client(service) as client:
        resp = await client.get(
            "/api/v1/stats/usage",
            params={"group_by": "version", "agent_id": str(agent_id), "scope": "own"},
        )

    assert resp.status_code == 200
    call = service.usage_by_version.call_args
    assert call.kwargs["agent_id"] == agent_id
    assert call.kwargs["scope"] == "own"
    service.usage.assert_not_called()


async def test_group_by_version_without_an_agent_is_refused():
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"group_by": "version"})

    assert resp.status_code == 422
    service.usage_by_version.assert_not_called()


async def test_group_by_user_asks_the_person_question_without_an_agent():
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"group_by": "user", "limit": 6})

    assert resp.status_code == 200
    assert service.usage_by_user.call_args.kwargs["limit"] == 6
    service.usage.assert_not_called()
    service.usage_by_version.assert_not_called()


async def test_the_person_table_defaults_to_ten_rows():
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"group_by": "user"})

    assert resp.status_code == 200
    assert service.usage_by_user.call_args.kwargs["limit"] == 10


async def test_an_unbounded_person_table_is_refused():
    """A card cannot render five hundred names; an unbounded limit would try."""
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"group_by": "user", "limit": 500})

    assert resp.status_code == 422
    service.usage_by_user.assert_not_called()


async def test_a_dimension_outside_the_contract_is_a_422_not_an_empty_answer():
    """The vocabulary is fixed; an unimplemented word must refuse loudly."""
    service = _service()

    async with _client(service) as client:
        resp = await client.get("/api/v1/stats/usage", params={"group_by": "exposure"})

    assert resp.status_code == 422
    service.usage.assert_not_called()
