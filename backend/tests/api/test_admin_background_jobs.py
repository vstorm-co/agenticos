"""The Background jobs routes are the deployment owner's alone (#2219).

The service is real-database tested in `tests/integration/test_background_job_panel.py`;
what is pinned here is the gate in front of it and how the routes hand their
arguments over: the queue is the deployment's, so an organization's own owner -
let alone a member - is refused every verb.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_background_job_service, get_current_user
from app.core.config import settings
from app.main import app
from app.schemas.background_job import (
    BackgroundJobList,
    BackgroundJobRead,
    BackgroundJobsActivity,
    BackgroundJobsOverview,
    BackgroundKindRead,
)

pytestmark = pytest.mark.anyio

BASE = f"{settings.API_V1_STR}/admin/background-jobs"
# Fixed, not `uuid4()`: a parametrize id has to be the same in every xdist worker.
_SOME_JOB = UUID("00000000-0000-4000-8000-000000000001")


def _user(*, app_admin: bool) -> MagicMock:
    return MagicMock(id=uuid4(), is_app_admin=app_admin, is_active=True)


@pytest.fixture
def service() -> MagicMock:
    service = MagicMock()
    service.list_jobs = AsyncMock(return_value=BackgroundJobList(items=[]))
    return service


async def _client(user: MagicMock, service: MagicMock) -> AsyncGenerator[AsyncClient]:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_background_job_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.security
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("GET", "/activity", None),
        ("GET", "/jobs", None),
        ("POST", f"/jobs/{_SOME_JOB}/retry", None),
        ("POST", f"/jobs/{_SOME_JOB}/cancel", None),
        ("POST", "/kinds/ingest-document/pause", {"reason": "x"}),
        ("POST", "/kinds/ingest-document/resume", None),
    ],
)
async def test_someone_who_is_not_the_deployments_owner_is_refused(
    service: MagicMock, method: str, path: str, body: dict[str, str] | None
) -> None:
    async for client in _client(_user(app_admin=False), service):
        response = await client.request(method, f"{BASE}{path}", json=body)
    assert response.status_code == 403
    assert service.mock_calls == []


async def test_the_owner_pages_with_both_halves_of_the_cursor(service: MagicMock) -> None:
    before, before_id = datetime(2026, 10, 19, 12, tzinfo=UTC), uuid4()
    async for client in _client(_user(app_admin=True), service):
        response = await client.get(
            f"{BASE}/jobs",
            params={"status": "dead", "before": before.isoformat(), "before_id": str(before_id)},
        )
    assert response.status_code == 200
    kwargs = service.list_jobs.await_args.kwargs
    assert (kwargs["status"], kwargs["before"], kwargs["limit"]) == (
        "dead",
        (before, before_id),
        50,
    )


async def test_half_a_cursor_starts_from_the_newest(service: MagicMock) -> None:
    async for client in _client(_user(app_admin=True), service):
        await client.get(f"{BASE}/jobs", params={"before": datetime.now(UTC).isoformat()})
    assert service.list_jobs.await_args.kwargs["before"] is None


async def test_the_owner_reads_the_activity_of_the_window_asked_for(service: MagicMock) -> None:
    week = BackgroundJobsActivity(
        window="week", bucket_seconds=21600, buckets=[], kinds=[], oldest_wait_seconds=None
    )
    service.activity = AsyncMock(return_value=week)

    async for client in _client(_user(app_admin=True), service):
        response = await client.get(f"{BASE}/activity", params={"window": "week"})
        unknown = await client.get(f"{BASE}/activity", params={"window": "year"})

    assert response.status_code == 200
    assert response.json()["window"] == "week"
    service.activity.assert_awaited_once_with("week")
    assert unknown.status_code == 422


async def test_a_status_the_queue_does_not_have_is_a_422(service: MagicMock) -> None:
    async for client in _client(_user(app_admin=True), service):
        response = await client.get(f"{BASE}/jobs", params={"status": "exploded"})
    assert response.status_code == 422


async def test_the_owner_reaches_every_action_as_themselves(service: MagicMock) -> None:
    owner = _user(app_admin=True)
    now = datetime.now(UTC)
    job = BackgroundJobRead(
        id=uuid4(),
        kind="ingest-document",
        pool="ingest",
        status="queued",
        priority=0,
        attempts=0,
        max_attempts=2,
        organization_id=None,
        schedule_name=None,
        worker_id=None,
        last_error=None,
        run_after=now,
        created_at=now,
        started_at=None,
        finished_at=None,
    )
    kind = BackgroundKindRead(
        kind="ingest-document",
        organization_id=None,
        consecutive_deaths=0,
        lease_lost=0,
        paused_at=None,
        paused_reason=None,
    )
    service.overview = AsyncMock(
        return_value=BackgroundJobsOverview(counts={}, kinds=[], workers=[], schedules=[])
    )
    service.retry = AsyncMock(return_value=job)
    service.cancel = AsyncMock(return_value=job)
    service.pause_kind = AsyncMock(return_value=kind)
    service.resume_kind = AsyncMock(return_value=kind)

    async for client in _client(owner, service):
        answers = [
            await client.get(BASE),
            await client.post(f"{BASE}/jobs/{job.id}/retry"),
            await client.post(f"{BASE}/jobs/{job.id}/cancel"),
            await client.post(f"{BASE}/kinds/ingest-document/pause", json={"reason": "a bad PDF"}),
            await client.post(f"{BASE}/kinds/ingest-document/resume"),
            await client.post(
                f"{BASE}/kinds/ingest-document/resume", params={"organization_id": str(owner.id)}
            ),
        ]

    assert [answer.status_code for answer in answers] == [200] * 6
    service.retry.assert_awaited_once_with(job.id, actor_user_id=owner.id)
    service.cancel.assert_awaited_once_with(job.id, actor_user_id=owner.id)
    service.pause_kind.assert_awaited_once_with(
        "ingest-document", reason="a bad PDF", actor_user_id=owner.id
    )
    # The whole kind, then one organization's pause of it.
    assert [call.kwargs["organization_id"] for call in service.resume_kind.await_args_list] == [
        None,
        owner.id,
    ]
