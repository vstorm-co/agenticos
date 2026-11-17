"""Browser teaching routes (#113): the permission gate and the disabled-by-default flag.

The service's own refusals are covered against a real database in
`tests/integration/test_browser_teaching_capture.py`. Here: starting needs
`skills:edit`, the feature answers `teaching_disabled` until the deployment
turns it on, and no route accepts recorder events.
"""

import uuid
from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

BODY = {
    "run_id": str(uuid.uuid4()),
    "call_id": "call-1",
    "title": "Download invoice",
    "allowed_origins": ["https://portal.example.test"],
}


@pytest.fixture
def as_role(
    mock_redis: MagicMock, mock_db_session: AsyncMock
) -> Iterator[Callable[[OrgRoleName], None]]:
    def use(role: OrgRoleName) -> None:
        context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
        app.dependency_overrides[deps.get_auth_context] = lambda: context

    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    yield use
    app.dependency_overrides.clear()


async def _post(path: str, body: object) -> tuple[int, dict]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(f"/api/v1/browser-teachings{path}", json=body)
    return response.status_code, response.json()


@pytest.mark.security
async def test_starting_without_skills_edit_is_refused(as_role) -> None:
    as_role(OrgRoleName.VIEWER)
    status, _ = await _post("", BODY)
    assert status == 403


@pytest.mark.security
async def test_teaching_is_disabled_by_default(as_role) -> None:
    as_role(OrgRoleName.BUILDER)
    status, body = await _post("", BODY)
    assert status == 400
    assert body["error"]["details"]["reason_code"] == "teaching_disabled"


@pytest.mark.security
async def test_no_route_accepts_recorder_events(as_role) -> None:
    as_role(OrgRoleName.BUILDER)
    paths = {path for path in app.openapi()["paths"] if "browser-teachings" in path}
    assert paths == {
        "/api/v1/browser-teachings",
        "/api/v1/browser-teachings/{session_id}",
        "/api/v1/browser-teachings/{session_id}/stop",
    }
    status, _ = await _post(f"/{uuid.uuid4()}/events", {"action": "click"})
    assert status in (404, 405)
