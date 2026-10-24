"""Expected eval refusals cross the HTTP boundary without becoming server errors."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.main import app
from app.repositories import eval_suite_repo
from app.services.eval_suite import EvalSuiteService
from tests.integration.test_eval_suites import _agent, _dataset, _environment, _owner, _suite_data

pytestmark = pytest.mark.anyio

__all__ = ["_environment"]


async def test_missing_environment_is_404_and_concurrent_duplicate_creates_are_201_or_409(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    data = _suite_data(dataset)
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def service() -> AsyncIterator[EvalSuiteService]:
        async with sessions() as session, session.begin():
            yield EvalSuiteService(session)

    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_eval_suite_service] = service
    path = f"{settings.API_V1_STR}/agents/{agent.id}/eval-suites"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post(
                f"{path}/estimate",
                json={"dataset_id": str(dataset.id), "environment_id": str(uuid.uuid4())},
            )
            assert missing.status_code == 404
            assert missing.json()["error"]["message"] == "Environment not found"
            original = eval_suite_repo.get_by_name
            arrived = 0
            ready = anyio.Event()

            async def same_name(*args, **kwargs):
                nonlocal arrived
                result = await original(*args, **kwargs)
                arrived += 1
                if arrived == 3:
                    ready.set()
                await ready.wait()
                return result

            monkeypatch.setattr(eval_suite_repo, "get_by_name", same_name)
            with anyio.fail_after(20):
                responses = await asyncio.gather(
                    *(client.post(path, json=data.model_dump(mode="json")) for _ in range(3))
                )
            assert sorted(r.status_code for r in responses) == [201, 409, 409]
            assert all(
                r.json()["error"]["message"] == "A suite with this name already exists"
                for r in responses
                if r.status_code == 409
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


@pytest.mark.security
async def test_a_visible_dataset_refuses_with_its_permission_but_another_tenant_gets_no_details(
    db,
) -> None:
    from app.core.permissions import OrgRoleName
    from app.services.dataset import DatasetService
    from tests.integration.test_eval_suites import _member

    owner = await _owner(db)
    dataset = await _dataset(db, owner)
    viewer = await _member(db, owner, OrgRoleName.VIEWER)
    outsider = await _owner(db)
    ctx = viewer
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_dataset_service] = lambda: DatasetService(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            path = f"{settings.API_V1_STR}/datasets/{dataset.id}"
            visible = await client.patch(path, json={"description": "changed"})
            assert visible.status_code == 403
            assert visible.json()["error"]["details"] == {"permission": "datasets:edit"}
            ctx = outsider
            hidden = await client.patch(path, json={"description": "changed"})
            assert hidden.status_code == 404
            assert hidden.json()["error"].get("details") is None
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
