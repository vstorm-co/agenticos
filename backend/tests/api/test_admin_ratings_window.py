"""`GET /admin/ratings/summary` - who may read it, and over which window.

The route is the deployment-wide half of answer quality, so it is app-admin
only; its organization-scoped sibling lives at `GET /stats/ratings/summary`
behind a permission instead. The window is worth a test through the app
because the dashboard's filter has to survive three hops - the browser, the
Next proxy, this route - and it used to be dropped at every one of them.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db_session, get_rating_service
from app.core.config import settings
from app.main import app
from app.schemas.message_rating import RatingSummary

pytestmark = pytest.mark.anyio

_SUMMARY = RatingSummary(
    total_ratings=3,
    like_count=2,
    dislike_count=1,
    average_rating=0.33,
    with_comments=0,
    ratings_by_day=[{"date": "2026-07-04", "likes": 2, "dislikes": 1}],
)


class _User:
    def __init__(self, *, is_app_admin: bool) -> None:
        self.id = uuid4()
        self.email = "kacper@example.com"
        self.is_app_admin = is_app_admin
        self.is_active = True
        self.created_at = datetime.now(UTC)


def _client(*, is_app_admin: bool, service: Any) -> AsyncClient:
    app.dependency_overrides[get_current_user] = lambda: _User(is_app_admin=is_app_admin)
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_rating_service] = lambda: service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock(get_summary=AsyncMock(return_value=_SUMMARY))
    app.dependency_overrides.clear()


async def test_the_window_asked_for_reaches_the_service(service: AsyncMock) -> None:
    async with _client(is_app_admin=True, service=service) as client:
        response = await client.get(
            f"{settings.API_V1_STR}/admin/ratings/summary",
            params={"from": "2026-07-01", "to": "2026-07-31"},
        )

    assert response.status_code == 200
    assert response.json()["total_ratings"] == 3
    assert service.get_summary.await_args.kwargs == {
        "from_date": date(2026, 7, 1),
        "to_date": date(2026, 7, 31),
    }


async def test_no_window_leaves_the_default_to_the_service(service: AsyncMock) -> None:
    async with _client(is_app_admin=True, service=service) as client:
        response = await client.get(f"{settings.API_V1_STR}/admin/ratings/summary")

    assert response.status_code == 200
    assert service.get_summary.await_args.kwargs == {"from_date": None, "to_date": None}


async def test_a_caller_who_is_not_an_app_admin_is_refused(service: AsyncMock) -> None:
    async with _client(is_app_admin=False, service=service) as client:
        response = await client.get(f"{settings.API_V1_STR}/admin/ratings/summary")

    assert response.status_code == 403
    service.get_summary.assert_not_awaited()
