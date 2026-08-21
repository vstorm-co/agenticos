"""What the three export routes accept, refuse and hand the service.

The CSV itself and the `Scope.OWN` floor are proven against a real database in
`tests/integration/test_run_export.py`; the filters and the domain refusals at
the service layer in `tests/test_run_export.py`. What belongs here is the wiring:
that each route carries the right permission gate, that the mandatory-range and
row-cap refusals reach the client as the status their exception declares, that a
success comes back as a downloadable `text/csv`, and that the query parameters
arrive at the service as the filter they name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import ExportTooLargeError, ValidationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.run_export import ExportResult

pytestmark = pytest.mark.anyio

_ORG = uuid4()
_RANGE = "started_from=2026-08-01T00:00:00Z&started_to=2026-08-31T00:00:00Z"
_APPROVAL_RANGE = "created_from=2026-08-01T00:00:00Z&created_to=2026-08-31T00:00:00Z"
_SPEND_RANGE = "from=2026-08-01T00:00:00Z&to=2026-08-31T00:00:00Z"


def _service() -> MagicMock:
    service = MagicMock()
    ok = ExportResult(content="run_id\n", filename="runs_export_20260810_000000.csv", row_count=0)
    service.export_runs = AsyncMock(return_value=ok)
    service.export_approvals = AsyncMock(return_value=ok)
    service.export_spend = AsyncMock(return_value=ok)
    return service


@asynccontextmanager
async def _client(role: str, service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=_ORG, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_run_export_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestGating:
    async def test_runs_export_refuses_a_caller_without_runs_view(self):
        async with _client(OrgRoleName.VIEWER.value, _service()) as client:
            response = await client.get(f"/api/v1/runs/export?{_RANGE}")
        assert response.status_code == 403

    async def test_spend_export_refuses_a_caller_without_runs_view(self):
        async with _client(OrgRoleName.VIEWER.value, _service()) as client:
            response = await client.get(f"/api/v1/spend/export?{_SPEND_RANGE}")
        assert response.status_code == 403

    async def test_approvals_export_refuses_a_caller_without_approvals_decide(self):
        # Member holds neither runs:view nor approvals:decide.
        async with _client(OrgRoleName.MEMBER.value, _service()) as client:
            response = await client.get(f"/api/v1/approvals/export?{_APPROVAL_RANGE}")
        assert response.status_code == 403

    async def test_operator_may_export_the_approvals_record(self):
        service = _service()
        async with _client(OrgRoleName.OPERATOR.value, service) as client:
            response = await client.get(f"/api/v1/approvals/export?{_APPROVAL_RANGE}")
        assert response.status_code == 200
        assert service.export_approvals.await_count == 1


class TestTheResponse:
    async def test_a_run_export_is_a_downloadable_csv(self):
        async with _client(OrgRoleName.OWNER.value, _service()) as client:
            response = await client.get(f"/api/v1/runs/export?{_RANGE}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"] == (
            "attachment; filename*=UTF-8''runs_export_20260810_000000.csv"
        )


class TestTheRefusalsSurfaceAsStatus:
    async def test_a_missing_range_is_a_422(self):
        service = _service()
        service.export_runs = AsyncMock(side_effect=ValidationError(message="needs a range"))
        async with _client(OrgRoleName.OWNER.value, service) as client:
            response = await client.get("/api/v1/runs/export")
        assert response.status_code == 422

    async def test_over_the_cap_is_a_413(self):
        service = _service()
        service.export_runs = AsyncMock(
            side_effect=ExportTooLargeError(
                message="too many", details={"row_count": 99999, "max_rows": 10000}
            )
        )
        async with _client(OrgRoleName.OWNER.value, service) as client:
            response = await client.get(f"/api/v1/runs/export?{_RANGE}")
        assert response.status_code == 413
        assert response.json()["error"]["details"]["max_rows"] == 10000

    async def test_an_unknown_status_is_refused_before_the_service(self):
        service = _service()
        async with _client(OrgRoleName.OWNER.value, service) as client:
            response = await client.get(f"/api/v1/runs/export?{_RANGE}&status=exploded")
        assert response.status_code == 422
        assert service.export_runs.await_count == 0


class TestTheFiltersReachTheService:
    async def test_run_filters_arrive_as_named(self):
        service = _service()
        agent_id, version_id = uuid4(), uuid4()
        async with _client(OrgRoleName.OWNER.value, service) as client:
            response = await client.get(
                f"/api/v1/runs/export?{_RANGE}&agent_id={agent_id}"
                f"&surface=slack&include_delegations=true&agent_version_id={version_id}"
                "&status=failed,budget_exceeded"
            )
        assert response.status_code == 200
        kwargs = service.export_runs.await_args.kwargs
        assert kwargs["agent_id"] == agent_id
        assert kwargs["include_delegations"] is True
        assert kwargs["filters"].statuses == ["failed", "budget_exceeded"]
        assert kwargs["filters"].surface == "slack"
        assert kwargs["filters"].agent_version_id == version_id
        assert kwargs["filters"].started_from.isoformat() == "2026-08-01T00:00:00+00:00"

    async def test_approval_filters_arrive_as_named(self):
        service = _service()
        who = uuid4()
        async with _client(OrgRoleName.OPERATOR.value, service) as client:
            response = await client.get(
                f"/api/v1/approvals/export?{_APPROVAL_RANGE}"
                f"&status=approved&status=rejected&triggered_by_user_id={who}&oldest_first=false"
            )
        assert response.status_code == 200
        kwargs = service.export_approvals.await_args.kwargs
        assert kwargs["filters"].statuses == ["approved", "rejected"]
        assert kwargs["filters"].triggered_by_user_id == who
        assert kwargs["oldest_first"] is False

    async def test_spend_range_arrives_as_since_and_until(self):
        service = _service()
        async with _client(OrgRoleName.OWNER.value, service) as client:
            response = await client.get(f"/api/v1/spend/export?{_SPEND_RANGE}")
        assert response.status_code == 200
        kwargs = service.export_spend.await_args.kwargs
        assert kwargs["since"].isoformat() == "2026-08-01T00:00:00+00:00"
        assert kwargs["until"].isoformat() == "2026-08-31T00:00:00+00:00"
