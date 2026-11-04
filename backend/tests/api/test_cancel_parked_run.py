"""Stopping a parked chat run is a session operation authorized by its service."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.public_api import is_public_route
from app.api.routes.v1.runs import router
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus
from app.main import app
from app.services.agent_runner import AgentRunnerService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("status", [200, 400, 403, 404])
async def test_the_service_decides_whether_the_session_can_stop_the_run(status: int) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    run_id = uuid4()
    refused = {
        400: BadRequestError(message="Already running"),
        403: AuthorizationError(message="Not yours"),
        404: NotFoundError(message="Run not found"),
    }
    cancel = AsyncMock(
        return_value="Not performed: the run was stopped.", side_effect=refused.get(status)
    )
    service = MagicMock(cancel_parked=cancel)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/runs/{run_id}/cancel")
        assert response.status_code == status, response.text
        cancel.assert_awaited_once_with(ctx, run_id)
        if status == 200:
            assert response.json() == "Not performed: the run was stopped."
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["cancel", "can-stop"])
def test_the_console_operation_is_not_exposed_to_organization_keys(path: str) -> None:
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path.endswith("/runs/{run_id}/" + path)
    )
    assert not is_public_route(route)


@pytest.mark.parametrize("allowed", [False, True])
async def test_the_owner_can_discover_stop_without_decision_permissions(allowed: bool) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    run = uuid4()
    service = MagicMock(can_stop_parked=AsyncMock(return_value=allowed))
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_agent_runner_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/runs/{run}/can-stop")
        assert response.status_code == 200
        assert response.json() is allowed
        service.can_stop_parked.assert_awaited_once_with(ctx, run)
    finally:
        app.dependency_overrides.clear()


def _parked(status: str) -> MagicMock:
    run = MagicMock(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        status=status,
        paused_state=None,
        conversation_id=None,
    )
    return run


async def test_a_workflow_stop_of_a_parked_run_needs_no_person() -> None:
    run = _parked(RunStatus.AWAITING_APPROVAL.value)
    service = AgentRunnerService(MagicMock())
    with (
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ) as claim,
        patch("app.services.agent_runner.agent_run_repo.expire_pending_approvals", AsyncMock()),
        patch("app.services.agent_runner.agent_run_repo.finish_run", AsyncMock()) as finish,
        patch.object(service.transcript, "record", AsyncMock()),
        patch("app.services.agent_runner.record_audit", AsyncMock()) as audit,
    ):
        stops = await service.stop_parked_for_workflow(
            [run.id, run.id], organization_id=run.organization_id
        )
        audit.assert_not_awaited()
        await service.record_parked_stops(stops)

    claim.assert_awaited_once_with(service.db, run.id, organization_id=run.organization_id)
    assert finish.await_args.kwargs["status"] == RunStatus.CANCELLED.value
    assert audit.await_args.kwargs["actor_user_id"] is None
    assert audit.await_args.kwargs["organization_id"] == run.organization_id
    assert audit.await_args.kwargs["details"] == {
        "previous_status": RunStatus.AWAITING_APPROVAL.value,
        "by": "workflow_run",
    }


@pytest.mark.parametrize("status", [None, RunStatus.RUNNING, RunStatus.CANCELLED])
async def test_a_workflow_stop_of_a_run_already_resumed_does_nothing(
    status: RunStatus | None,
) -> None:
    run = None if status is None else _parked(status.value)
    service = AgentRunnerService(MagicMock())
    with (
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch("app.services.agent_runner.agent_run_repo.finish_run", AsyncMock()) as finish,
        patch("app.services.agent_runner.record_audit", AsyncMock()) as audit,
    ):
        assert await service.stop_parked_for_workflow([uuid4()], organization_id=uuid4()) == []

    finish.assert_not_awaited()
    audit.assert_not_awaited()
