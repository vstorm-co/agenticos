"""`POST /admin/announcements` - the route layer over `AnnouncementService`.

`tests/integration/test_announcement_composer.py` proves the service against
a real database - audience resolution, dedup, the audit entry. What is left
is the route itself: the app-admin gate, request validation, and that a
refusal the service raises reaches the caller as the right status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_announcement_service, get_current_user
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.db.models.announcement import Announcement
from app.main import app
from app.services.announcement import AnnouncementSendResult

pytestmark = pytest.mark.anyio

ENDPOINT = f"{settings.API_V1_STR}/admin/announcements"
NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


class _Caller:
    def __init__(self, *, is_app_admin: bool) -> None:
        self.id = uuid4()
        self.email = "admin@example.com"
        self.is_app_admin = is_app_admin
        self.is_active = True
        self.created_at = NOW


def _result(**overrides) -> AnnouncementSendResult:
    fields = {
        "id": uuid.uuid4(),
        "actor_user_id": uuid.uuid4(),
        "body": "Hello",
        "audience_spec": {"organizations": "all", "role": None},
        "audience_description": "All organizations",
        "created_at": NOW,
    }
    fields.update(overrides)
    announcement = Announcement(**fields)
    return AnnouncementSendResult(announcement=announcement, recipient_count=3)


def _client(*, is_app_admin: bool = True, service: AsyncMock | None = None) -> AsyncClient:
    app.dependency_overrides[get_current_user] = lambda: _Caller(is_app_admin=is_app_admin)
    app.dependency_overrides[get_announcement_service] = lambda: (
        service or MagicMock(send=AsyncMock(return_value=_result()))
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestSending:
    async def test_an_app_admin_can_send(self):
        service = MagicMock(send=AsyncMock(return_value=_result(body="Maintenance tonight")))
        async with _client(service=service) as client:
            response = await client.post(
                ENDPOINT, json={"body": "Maintenance tonight", "organizations": "all"}
            )

        assert response.status_code == 201
        body = response.json()
        assert body["body"] == "Maintenance tonight"
        assert body["audience_description"] == "All organizations"
        assert body["recipient_count"] == 3

    async def test_an_ordinary_member_is_refused(self):
        async with _client(is_app_admin=False) as client:
            response = await client.post(ENDPOINT, json={"body": "Hello", "organizations": "all"})

        assert response.status_code == 403

    async def test_passes_the_resolved_role_through_as_a_plain_string(self):
        service = MagicMock(send=AsyncMock(return_value=_result()))
        async with _client(service=service) as client:
            await client.post(
                ENDPOINT,
                json={"body": "Owners", "organizations": "all", "role": "owner"},
            )

        assert service.send.call_args.kwargs["role"] == "owner"

    async def test_an_empty_body_is_rejected(self):
        async with _client() as client:
            response = await client.post(ENDPOINT, json={"body": "", "organizations": "all"})

        assert response.status_code == 422

    async def test_an_empty_organization_list_is_rejected(self):
        async with _client() as client:
            response = await client.post(ENDPOINT, json={"body": "Hello", "organizations": []})

        assert response.status_code == 422

    async def test_channels_default_to_both_when_omitted(self):
        service = MagicMock(send=AsyncMock(return_value=_result()))
        async with _client(service=service) as client:
            await client.post(ENDPOINT, json={"body": "Hello", "organizations": "all"})

        assert {c.value for c in service.send.call_args.kwargs["channels"]} == {"in_app", "email"}

    async def test_an_explicit_channel_selection_is_passed_through(self):
        service = MagicMock(send=AsyncMock(return_value=_result()))
        async with _client(service=service) as client:
            await client.post(
                ENDPOINT,
                json={"body": "Hello", "organizations": "all", "channels": ["email"]},
            )

        assert {c.value for c in service.send.call_args.kwargs["channels"]} == {"email"}

    async def test_an_empty_channel_list_is_rejected(self):
        async with _client() as client:
            response = await client.post(
                ENDPOINT, json={"body": "Hello", "organizations": "all", "channels": []}
            )

        assert response.status_code == 422

    async def test_an_invalid_role_is_rejected(self):
        async with _client() as client:
            response = await client.post(
                ENDPOINT,
                json={"body": "Hello", "organizations": "all", "role": "not_a_real_role"},
            )

        assert response.status_code == 422

    async def test_an_audience_with_nobody_in_it_is_a_400(self):
        service = MagicMock(
            send=AsyncMock(
                side_effect=BadRequestError(
                    message="This audience currently has no members to reach", details={}
                )
            )
        )
        async with _client(service=service) as client:
            response = await client.post(
                ENDPOINT, json={"body": "Hello", "organizations": "all", "role": "owner"}
            )

        assert response.status_code == 400
