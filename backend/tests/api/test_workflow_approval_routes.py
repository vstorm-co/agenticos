"""The workflow approvals routes, through the app: the wire contract.

What the service decides is proved against a real database in
`tests/integration/test_workflow_human_approval.py`; what is left is the
handlers - the gate, the status codes and the query they hand on.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.main import app
from app.schemas.workflow_approval import WorkflowApprovalList, WorkflowApprovalRead

# Who may decide what a run waits on is a governance control, so every test here
# is a security test.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _read() -> WorkflowApprovalRead:
    return WorkflowApprovalRead(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        workflow_name="Refunds",
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        title="Send the refund?",
        details=None,
        approver_user_ids=[],
        status=WorkflowApprovalStatus.APPROVED,
        expires_at=None,
        decided_by_user_id=None,
        decided_at=None,
        note=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    fake = MagicMock()
    fake.queue = AsyncMock(return_value=WorkflowApprovalList(items=[_read()], total=1))
    fake.decide = AsyncMock(return_value=_read())
    return fake


def _client_for(role: str, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_approval_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str = "") -> str:
    return f"{settings.API_V1_STR}/workflow-approvals{tail}"


async def test_the_queue_lists_what_the_statuses_ask_for(service: MagicMock):
    for open_client in _client_for(OrgRoleName.OPERATOR, service):
        async with open_client() as http:
            response = await http.get(_url(), params={"status": ["pending", "expired"]})
    assert response.status_code == 200
    assert response.json()["items"][0]["workflow_name"] == "Refunds"
    assert service.queue.await_args.kwargs["statuses"] == [
        WorkflowApprovalStatus.PENDING,
        WorkflowApprovalStatus.EXPIRED,
    ]


async def test_a_decision_is_handed_to_the_service(service: MagicMock):
    approval_id = uuid.uuid4()
    for open_client in _client_for(OrgRoleName.OWNER, service):
        async with open_client() as http:
            response = await http.post(
                _url(f"/{approval_id}"), json={"approved": True, "note": "ok"}
            )
    assert response.status_code == 200
    assert service.decide.await_args.args[1] == approval_id
    assert service.decide.await_args.kwargs == {"approved": True, "note": "ok"}


async def test_a_member_who_does_not_decide_approvals_is_refused(service: MagicMock):
    for open_client in _client_for(OrgRoleName.VIEWER, service):
        async with open_client() as http:
            listed = await http.get(_url())
            decided = await http.post(_url(f"/{uuid.uuid4()}"), json={"approved": True})
    assert (listed.status_code, decided.status_code) == (403, 403)
    service.queue.assert_not_awaited()
    service.decide.assert_not_awaited()
