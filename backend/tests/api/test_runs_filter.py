"""The status filter on GET /runs.

Asserted on what the repository is *asked for*, not on rendered rows: the
filter's failure mode is silent - an ignored or half-applied predicate still
answers 200 with plausible rows - so the test pins the predicate itself, and
separately that an unknown status is refused instead of matching nothing.

The patch point is the repository as `AgentRunnerService` sees it, because the
route reaches run history through the service rather than the repository - the
layering the rest of this codebase follows.

The status set travels *inside* `RunFilters`, not as a kwarg beside it, so the
assertions read `filters.statuses`. That is deliberate: `RunFilters.conditions()`
is the single place the page query and the count query both take their clauses
from, which is the one arrangement in which a status predicate cannot end up
applied to one and not the other.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    """A caller holding runs:view, with the database stubbed out."""
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    # The lambda is load-bearing: FastAPI reads an override's signature, and
    # `AsyncMock`'s is (*args, **kwargs), which it turns into two required
    # query parameters. Passing the class directly answers 422.
    app.dependency_overrides[deps.get_db_session] = lambda: AsyncMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_status_list_reaches_the_repository_as_a_list(monkeypatch):
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"status": "failed,budget_exceeded"})

    assert resp.status_code == 200
    assert list_runs.call_args.kwargs["filters"].statuses == ["failed", "budget_exceeded"]


async def test_no_status_param_means_no_status_predicate(monkeypatch):
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs")

    assert resp.status_code == 200
    assert list_runs.call_args.kwargs["filters"].statuses is None


async def test_an_unknown_status_is_refused_not_matched_against_nothing(monkeypatch):
    """`?status=falied` answering an empty 200 would read as "no failures"."""
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"status": "failed,falied"})

    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["unknown"] == ["falied"]
    list_runs.assert_not_called()


async def test_stray_commas_and_spaces_do_not_change_the_question(monkeypatch):
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"status": " failed , ,budget_exceeded,"})

    assert resp.status_code == 200
    assert list_runs.call_args.kwargs["filters"].statuses == ["failed", "budget_exceeded"]


async def test_the_status_filter_composes_with_the_delegation_default(monkeypatch):
    """Two narrowings, not one replacing the other.

    `?status=` and the top-level-only default answer different questions, and a
    resolution that dropped either would look right: the failures page would
    quietly include delegated rows whose parent is already listed as failed, or
    the delegation default would swallow the status filter and show everything.
    """
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get("/api/v1/runs", params={"status": "failed"})

    assert resp.status_code == 200
    kwargs = list_runs.call_args.kwargs
    assert kwargs["filters"].statuses == ["failed"]
    assert kwargs["include_delegations"] is False


async def test_a_delegation_listing_can_still_be_narrowed_by_status(monkeypatch):
    list_runs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("app.services.agent_runner.agent_run_repo.list_runs", list_runs)

    async with _client() as client:
        resp = await client.get(
            "/api/v1/runs", params={"status": "failed", "include_delegations": "true"}
        )

    assert resp.status_code == 200
    kwargs = list_runs.call_args.kwargs
    assert kwargs["filters"].statuses == ["failed"]
    assert kwargs["include_delegations"] is True
