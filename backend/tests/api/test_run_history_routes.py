"""What `GET /runs` accepts, and what it refuses.

The filters themselves are proven against a real database in
`tests/integration/test_run_history_filters.py` - which rows a `WHERE` returns is
not a question this layer can answer. What belongs here is the wiring: that each
query parameter reaches the service as the filter it names, that a repeated
`status` arrives as several rather than as the last one, and that a value outside
the enum is refused instead of quietly matching nothing.

That last one matters more than it looks. `status` and `surface` are string
columns, so an unvalidated `?status=complete` would return an empty page - and an
empty page is what "nothing went wrong this week" looks like.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid4()


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER.value
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _service() -> MagicMock:
    service = MagicMock()
    service.list_runs = AsyncMock(return_value=([], 0))
    return service


async def _filters_for(query: str) -> Any:
    """The `RunFilters` the route built from this query string."""
    service = _service()
    async with _client(service) as client:
        response = await client.get(f"/api/v1/runs{query}")
    assert response.status_code == 200, response.text
    return service.list_runs.await_args.kwargs["filters"]


class TestTheFiltersReachTheService:
    async def test_a_comma_separated_status_arrives_as_all_of_them(self):
        """`?status=failed,budget_exceeded` is the show-me-the-problems query.
        Taking one value would silently answer half of it. The set travels inside
        `RunFilters`, so the page query and the count query cannot come to apply a
        different status clause."""
        filters = await _filters_for("?status=failed,budget_exceeded")

        assert filters.statuses == ["failed", "budget_exceeded"]

    async def test_an_unknown_status_is_refused_rather_than_matching_nothing(self):
        """A status the vocabulary does not hold is a 422 naming it, not a filter
        that silently returns an empty page - which reads as an organization with
        nothing wrong."""
        async with _client(_service()) as client:
            response = await client.get("/api/v1/runs?status=exploded")

        assert response.status_code == 422
        assert "exploded" in response.text

    async def test_a_request_with_no_filters_narrows_nothing(self):
        filters = await _filters_for("")

        assert filters.statuses is None
        assert filters.surface is None
        assert (filters.started_from, filters.started_to) == (None, None)

    async def test_every_column_a_filter_names_is_passed_through(self):
        user_id, environment_id, exposure_id, version_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        filters = await _filters_for(
            f"?surface=slack&user_id={user_id}&environment_id={environment_id}"
            f"&exposure_id={exposure_id}&agent_version_id={version_id}"
            "&started_from=2026-08-01T00:00:00Z&started_to=2026-08-06T23:59:59Z"
        )

        assert filters.surface == "slack"
        assert filters.user_id == user_id
        assert filters.environment_id == environment_id
        assert filters.exposure_id == exposure_id
        assert filters.agent_version_id == version_id
        assert filters.started_from.isoformat() == "2026-08-01T00:00:00+00:00"
        assert filters.started_to.isoformat() == "2026-08-06T23:59:59+00:00"


class TestSortingIsChosenFromTwoOrdersAndNotFromAColumnName:
    """An `order_by` built from a query string is an injection surface, and these
    are the two orders the page has a reason to offer."""

    async def test_the_slowest_first(self):
        service = _service()
        async with _client(service) as client:
            response = await client.get("/api/v1/runs?order_by=duration&descending=true")

        assert response.status_code == 200
        assert service.list_runs.await_args.kwargs["order_by"].value == "duration"
        assert service.list_runs.await_args.kwargs["descending"] is True

    async def test_a_column_name_is_not_an_order(self):
        async with _client(_service()) as client:
            response = await client.get("/api/v1/runs?order_by=cost_usd")

        assert response.status_code == 422

    async def test_the_default_is_the_feed(self):
        service = _service()
        async with _client(service) as client:
            await client.get("/api/v1/runs")

        assert service.list_runs.await_args.kwargs["order_by"].value == "started_at"
        assert service.list_runs.await_args.kwargs["descending"] is True

    async def test_a_duration_threshold_reaches_the_filters(self):
        filters = await _filters_for("?took_over_ms=30000")

        assert filters.took_over_ms == 30_000

    async def test_a_negative_threshold_is_refused(self):
        async with _client(_service()) as client:
            response = await client.get("/api/v1/runs?took_over_ms=-1")

        assert response.status_code == 422


class TestAskingWhatPeopleThoughtOfIt:
    async def test_the_runs_somebody_said_were_wrong(self):
        filters = await _filters_for("?rated=down")

        assert filters.rated.value == "down"

    async def test_a_third_verdict_is_refused(self):
        """There are two, and a run either has one or does not. `?rated=meh` must
        not answer with an empty page - the queue this filter exists for is the one
        an operator is reading to find real complaints."""
        async with _client(_service()) as client:
            response = await client.get("/api/v1/runs?rated=meh")

        assert response.status_code == 422


class TestWhatIsRefusedRatherThanMatchedAgainstNothing:
    @pytest.mark.parametrize(
        "query",
        [
            "?status=complete",
            "?surface=carrier-pigeon",
            "?started_from=last-tuesday",
            "?user_id=not-a-uuid",
            # Both were `RunSurface` members nothing ever assigned, so a filter
            # offering either answered with nothing on every deployment for ever
            # (#207). Refusing them is the shape of the fix: the vocabulary is
            # now exactly the surfaces that exist, and this fails if one comes
            # back without a writer.
            "?surface=schedule",
            "?surface=playground",
        ],
    )
    async def test_a_value_outside_its_type_is_a_422(self, query):
        """`status` and `surface` are string columns, so an unvalidated value
        would return an empty page - and an empty page reads as "nothing went
        wrong", which is the opposite of what was asked."""
        async with _client(_service()) as client:
            response = await client.get(f"/api/v1/runs{query}")

        assert response.status_code == 422
