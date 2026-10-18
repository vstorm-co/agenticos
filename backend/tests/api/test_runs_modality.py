"""Run history tells calls from typed runs (#54)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.main import app
from app.repositories.voice_call import VoiceChain

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: AsyncMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _run(modality: str) -> AgentRun:
    return AgentRun(
        id=uuid4(),
        agent_id=uuid4(),
        organization_id=uuid4(),
        surface="web",
        status="completed",
        modality=modality,
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0.30"),
        cost_is_partial=False,
        is_test=False,
        tool_args_repaired=0,
        started_at=datetime.now(UTC),
    )


@pytest.fixture
def no_ratings(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_runner.agent_run_repo.down_rated_run_ids", AsyncMock(return_value=set())
    )


@pytest.mark.usefixtures("no_ratings")
async def test_calls_are_listed_on_their_own_and_once_per_call(monkeypatch):
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"modality": "voice"})

    assert resp.status_code == 200
    filters = list_runs.call_args.kwargs["filters"]
    assert filters.modality == "voice" and filters.one_row_per_call is True


async def test_a_modality_that_does_not_exist_is_refused():
    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"modality": "video"})
    assert resp.status_code == 422


@pytest.mark.usefixtures("no_ratings")
async def test_a_listed_call_carries_every_connection_summed(monkeypatch):
    call, typed = _run("voice"), _run("text")
    monkeypatch.setattr(
        "app.services.agent_runner.agent_run_repo.list_runs",
        AsyncMock(return_value=([call, typed], 2)),
    )
    chains = AsyncMock(
        return_value={call.id: VoiceChain(connections=2, seconds=150, cost_usd=Decimal("0.06"))}
    )
    monkeypatch.setattr("app.services.agent_runner.voice_call_repo.chains_for_runs", chains)

    async with _client() as client:
        resp = await client.get("/api/v1/runs")

    items = {item["id"]: item for item in resp.json()["items"]}
    assert items[str(call.id)]["modality"] == "voice"
    assert items[str(call.id)]["voice_chain"]["connections"] == 2
    assert items[str(typed.id)]["voice_chain"] is None
    assert chains.await_args.args[1] == [call.id]


@pytest.mark.usefixtures("no_ratings")
async def test_a_page_with_no_calls_asks_for_no_chains(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_runner.agent_run_repo.list_runs",
        AsyncMock(return_value=([_run("text")], 1)),
    )
    chains = AsyncMock(return_value={})
    monkeypatch.setattr("app.services.agent_runner.voice_call_repo.chains_for_runs", chains)

    async with _client() as client:
        resp = await client.get("/api/v1/runs")

    assert resp.status_code == 200
    chains.assert_not_awaited()
