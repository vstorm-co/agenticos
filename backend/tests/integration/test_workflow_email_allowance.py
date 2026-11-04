"""Workflow delivery reservations share real Redis counters across independent clients."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.permissions import AuthContext
from app.workflows.nodes.email_send import _handler as email_node
from app.workflows.nodes.email_send._handler import _reserve_deliveries

pytestmark = pytest.mark.anyio


@pytest.fixture
async def counters(monkeypatch) -> AsyncGenerator[RedisClient]:
    prefix = f"test:workflow-email:{uuid4()}"
    monkeypatch.setattr(email_node, "_ALLOWANCE_KEY_PREFIX", prefix)
    client = RedisClient()
    await client.connect()
    try:
        if not await client.ping():
            pytest.skip("No Redis reachable")
        keys = await client.raw.keys(f"{prefix}:*")
        if keys:
            await client.raw.delete(*keys)
        yield client
    finally:
        keys = await client.raw.keys(f"{prefix}:*") if await client.ping() else []
        if keys:
            await client.raw.delete(*keys)
        await client.close()


def _member() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


@pytest.mark.security
async def test_parallel_clients_cannot_exceed_one_principals_deliveries(counters, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_EMAIL_MAX_PER_PRINCIPAL_PER_HOUR", 3)
    ctx = _member()
    results = await asyncio.gather(*(_reserve_deliveries(ctx, 1) for _ in range(20)))
    assert sum(result is None for result in results) == 3
    assert all(result is None or result.code == "EMAIL_DELIVERY_LIMIT" for result in results)
    assert (
        0
        < await counters.raw.ttl(f"{email_node._ALLOWANCE_KEY_PREFIX}:principal:{ctx.subject_id}")
        <= 3600
    )


@pytest.mark.security
async def test_deployment_allowance_spans_distinct_users_and_organizations(counters, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_EMAIL_MAX_PER_DEPLOYMENT_PER_HOUR", 2)
    results = [await _reserve_deliveries(_member(), 1) for _ in range(3)]
    assert results[:2] == [None, None]
    assert results[2] is not None and results[2].details["scope"] == "deployment"
