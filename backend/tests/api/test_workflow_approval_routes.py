"""The workflow approvals routes, through the app: the wire contract.

What the service decides is proved against a real database in
`tests/integration/test_workflow_human_approval.py`; what is left is the
handlers - the gate, the status codes and the query they hand on.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.main import app
from app.schemas.workflow_approval import WorkflowApprovalList, WorkflowApprovalRead
from app.schemas.workflow_stats import EditRatioBucket, WorkflowApprovalsSummary

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
        editable=False,
        proposal=None,
        proposal_format="text",
        proposal_label=None,
        final=None,
        edited=False,
    )


def _summary() -> WorkflowApprovalsSummary:
    return WorkflowApprovalsSummary(
        requests=0,
        pending=0,
        approved_unchanged=0,
        approved_edited=0,
        rejected=0,
        expired=0,
        cancelled=0,
        edit_ratios=[EditRatioBucket(upto=upto, count=0) for upto in (0.0, 0.1, 0.25, 0.5, 1.0)],
        workflows=[],
    )


@pytest.fixture
def service() -> MagicMock:
    fake = MagicMock()
    fake.queue = AsyncMock(return_value=WorkflowApprovalList(items=[_read()], total=1))
    fake.decide = AsyncMock(return_value=_read())
    fake.approvals_summary = AsyncMock(return_value=_summary())
    return fake


def _client_for(role: str, service: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_approval_service] = lambda: service
    app.dependency_overrides[deps.get_workflow_stats_service] = lambda: service

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


async def test_the_record_is_read_newest_first_within_a_window(service: MagicMock):
    for open_client in _client_for(OrgRoleName.OPERATOR, service):
        async with open_client() as http:
            response = await http.get(
                _url(),
                params={
                    "status": ["approved", "rejected"],
                    "created_from": "2026-10-01T00:00:00Z",
                    "created_to": "2026-10-31T00:00:00Z",
                    "oldest_first": "false",
                },
            )
    assert response.status_code == 200
    kwargs = service.queue.await_args.kwargs
    assert kwargs["oldest_first"] is False
    assert kwargs["created_from"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert kwargs["created_to"] == datetime(2026, 10, 31, tzinfo=UTC)


async def test_a_decision_is_handed_to_the_service(service: MagicMock):
    approval_id = uuid.uuid4()
    for open_client in _client_for(OrgRoleName.OWNER, service):
        async with open_client() as http:
            response = await http.post(
                _url(f"/{approval_id}"), json={"approved": True, "note": "ok"}
            )
    assert response.status_code == 200
    assert service.decide.await_args.args[1] == approval_id
    assert service.decide.await_args.kwargs == {"approved": True, "note": "ok", "final": None}


async def test_an_edited_version_is_handed_to_the_service(service: MagicMock):
    for open_client in _client_for(OrgRoleName.OWNER, service):
        async with open_client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}"), json={"approved": True, "final": "Dear Ann"}
            )
    assert response.status_code == 200
    assert service.decide.await_args.kwargs["final"] == "Dear Ann"


@pytest.mark.parametrize("final", ["", "   ", "x" * 100_001])
async def test_an_empty_or_oversized_edit_is_refused(service: MagicMock, final: str):
    for open_client in _client_for(OrgRoleName.OWNER, service):
        async with open_client() as http:
            response = await http.post(
                _url(f"/{uuid.uuid4()}"), json={"approved": True, "final": final}
            )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == "final"
    service.decide.assert_not_awaited()


async def test_a_member_who_does_not_decide_approvals_is_refused(service: MagicMock):
    for open_client in _client_for(OrgRoleName.VIEWER, service):
        async with open_client() as http:
            listed = await http.get(_url())
            decided = await http.post(
                _url(f"/{uuid.uuid4()}"), json={"approved": True, "final": "x"}
            )
    assert (listed.status_code, decided.status_code) == (403, 403)
    service.queue.assert_not_awaited()
    service.decide.assert_not_awaited()


async def test_the_query_names_are_from_and_to(service: MagicMock):
    for open_client in _client_for(OrgRoleName.VIEWER, service):
        async with open_client() as http:
            answered = await http.get(
                _url("/stats"), params={"from": "2026-10-01", "to": "2026-10-07"}
            )
            unnamed = await http.get(
                _url("/stats"), params={"first": "2026-10-01", "last": "2026-10-07"}
            )
    assert answered.status_code == 200
    assert answered.json()["workflows"] == []
    assert [bucket["upto"] for bucket in answered.json()["edit_ratios"]] == [
        0.0,
        0.1,
        0.25,
        0.5,
        1.0,
    ]
    assert service.approvals_summary.await_args.kwargs == {
        "first": date(2026, 10, 1),
        "last": date(2026, 10, 7),
    }
    assert unnamed.status_code == 422


@pytest.mark.parametrize(
    ("first", "last"), [("2026-10-07", "2026-10-01"), ("2024-01-01", "2026-10-01")]
)
async def test_a_window_over_a_year_or_backwards_is_refused(
    service: MagicMock, first: str, last: str
):
    for open_client in _client_for(OrgRoleName.VIEWER, service):
        async with open_client() as http:
            response = await http.get(_url("/stats"), params={"from": first, "to": last})
    assert response.status_code == 400
    service.approvals_summary.assert_not_awaited()


async def test_the_summary_needs_workflows_view(service: MagicMock):
    # A role string no table knows holds no permission at all, `workflows:view` included.
    for open_client in _client_for("unknown-role", service):
        async with open_client() as http:
            response = await http.get(
                _url("/stats"), params={"from": "2026-10-01", "to": "2026-10-07"}
            )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required"] == ["workflows:view"]
    service.approvals_summary.assert_not_awaited()


async def test_the_window_may_span_366_days_but_not_367(service: MagicMock):
    # The route counts the span as `(to - from).days`, so these are 366 and 367 days apart.
    for open_client in _client_for(OrgRoleName.VIEWER, service):
        async with open_client() as http:
            longest = await http.get(
                _url("/stats"), params={"from": "2025-10-01", "to": "2026-10-02"}
            )
            one_more = await http.get(
                _url("/stats"), params={"from": "2025-10-01", "to": "2026-10-03"}
            )
    assert longest.status_code == 200
    assert service.approvals_summary.await_args.kwargs == {
        "first": date(2025, 10, 1),
        "last": date(2026, 10, 2),
    }
    assert one_more.status_code == 400
    assert service.approvals_summary.await_count == 1
