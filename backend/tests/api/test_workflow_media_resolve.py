"""Resolving a media hold needs the organization's budget authority and a closed body."""

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.deps import get_auth_context, get_db_session
from app.api.routes.v1.workflows import router
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.schemas.workflow_media import WorkflowMediaCharged
from app.services.workflow_media_resolution import WorkflowMediaResolutionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _app(permissions: list[Perm]) -> tuple[FastAPI, AuthContext]:
    app = FastAPI()
    app.include_router(router, prefix="/workflows")
    ctx = AuthContext(
        user_id=uuid4(), organization_id=uuid4(), role="owner", key_scopes=frozenset(permissions)
    )
    app.dependency_overrides[get_auth_context] = lambda: ctx

    async def session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = session

    @app.exception_handler(AppException)
    async def refused(_request, error):
        return JSONResponse(status_code=error.status_code, content={"code": error.code})

    return app, ctx


@pytest.mark.parametrize(
    "permissions,allowed",
    [
        ([Perm.BUDGETS_MANAGE], True),
        ([Perm.WORKFLOWS_EDIT, Perm.WORKFLOWS_RUN], False),
        ([], False),
    ],
)
async def test_resolving_a_media_hold_requires_budget_authority(monkeypatch, permissions, allowed):
    app, ctx = _app(permissions)
    resolve = AsyncMock(
        return_value={
            "operation_id": str(uuid4()),
            "phase": "failed",
            "held_usd": "0",
            "incurred_usd": "0.7",
            "booked_usd": "0",
            "cost_source": "reported",
            "accounting_complete": True,
            "node_unresolved_usd": "0.7",
            "has_receipt": False,
            "retry_effect": "new_billable_submission",
        }
    )
    monkeypatch.setattr(WorkflowMediaResolutionService, "resolve", resolve)
    operation_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/workflows/media-operations/{operation_id}/resolve",
            json={"outcome": "charged", "charged_usd": "0.7"},
        )
    assert response.status_code == (200 if allowed else 403)
    if allowed:
        resolve.assert_awaited_once_with(
            ctx, operation_id, WorkflowMediaCharged(outcome="charged", charged_usd=Decimal("0.7"))
        )
    else:
        resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"outcome": "charged"},
        {"outcome": "charged", "charged_usd": "0"},
        {"outcome": "charged", "charged_usd": "0.0000001"},
        {"outcome": "not_charged", "charged_usd": "1"},
        {"outcome": "refunded"},
    ],
)
async def test_a_resolution_body_names_one_closed_outcome(monkeypatch, body):
    app, _ctx = _app([Perm.BUDGETS_MANAGE])
    resolve = AsyncMock()
    monkeypatch.setattr(WorkflowMediaResolutionService, "resolve", resolve)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(f"/workflows/media-operations/{uuid4()}/resolve", json=body)
    assert response.status_code == 422
    resolve.assert_not_awaited()
