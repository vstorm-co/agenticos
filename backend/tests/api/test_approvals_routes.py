"""What `GET /approvals` accepts, and what it refuses.

Which rows come back is proven against a real database in
`tests/integration/test_approvals_queue.py` - the three names on a queue row are
joins, and a mocked session will happily pretend to have performed one. What
belongs here is the wiring, plus the one default that is load-bearing: pending
only, oldest first. Nothing expires a parked call, so the oldest row can be from
months ago, and a queue that opened newest-first would bury exactly it.
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


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_approval_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _service() -> MagicMock:
    service = MagicMock()
    service.list_approvals = AsyncMock(return_value=([], 0))
    return service


async def _called_with(query: str) -> dict[str, Any]:
    service = _service()
    async with _client(service) as client:
        response = await client.get(f"/api/v1/approvals{query}")
    assert response.status_code == 200, response.text
    return service.list_approvals.await_args.kwargs


class TestTheQueueByDefault:
    async def test_pending_only_and_oldest_first(self):
        """The queue drains from the top, and `statuses=None` is what the
        repository reads as pending."""
        called = await _called_with("")

        assert called["filters"].statuses is None
        assert called["oldest_first"] is True

    async def test_the_record_of_decisions_is_the_same_route(self):
        called = await _called_with("?status=approved&status=rejected")

        assert called["filters"].statuses == ["approved", "rejected"]

    async def test_newest_first_when_asked(self):
        called = await _called_with("?oldest_first=false")

        assert called["oldest_first"] is False


class TestNarrowing:
    async def test_whose_runs_parked_the_call(self):
        asker = uuid4()
        called = await _called_with(f"?triggered_by_user_id={asker}")

        assert called["filters"].triggered_by_user_id == asker

    async def test_a_window_over_when_the_call_was_parked(self):
        called = await _called_with(
            "?created_from=2026-08-01T00:00:00Z&created_to=2026-08-06T23:59:59Z"
        )

        assert called["filters"].created_from.isoformat() == "2026-08-01T00:00:00+00:00"
        assert called["filters"].created_to.isoformat() == "2026-08-06T23:59:59+00:00"


class TestWhatIsRefused:
    @pytest.mark.parametrize("query", ["?status=maybe", "?created_from=whenever"])
    async def test_a_value_outside_its_type_is_a_422(self, query):
        """`status` is a string column. Unvalidated, `?status=maybe` would answer
        with an empty page - and an empty approvals queue reads as "nothing is
        waiting on anybody", which is the opposite of what was asked."""
        async with _client(_service()) as client:
            response = await client.get(f"/api/v1/approvals{query}")

        assert response.status_code == 422

    async def test_expired_is_a_status_the_queue_can_be_filtered_to(self):
        """`expire_stale` assigns it (#457), so it is a real outcome a reader can
        ask for - "what lapsed undecided" is a question the accountability trail
        answers. #178's plan to delete the value was reversed once expiry had its
        settlement semantics."""
        called = await _called_with("?status=expired")

        assert called["filters"].statuses == ["expired"]
