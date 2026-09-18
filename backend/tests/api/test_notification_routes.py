"""The four inbox routes, through the app (#1598).

`tests/integration/test_notification_center.py` proves the service's write
path and its gate-aware reads against a real database; what is left is the
route layer itself - status codes, response shapes, and that each handler
delegates to the right service method. The service runs for real here, with
`notification_repo` stubbed at the database edge, so an ungated event type
(`run_completed`) is used throughout to keep the gate check itself out of
scope for these tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.user import User
from app.main import app
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService

pytestmark = pytest.mark.anyio

_USER_ID = uuid.uuid4()
_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

NOTIFICATION_PATH = "app.services.notification_center"


def _row(**overrides) -> Notification:
    fields = {
        "id": uuid.uuid4(),
        "organization_id": _ORGANIZATION_ID,
        "recipient_user_id": _USER_ID,
        "event_type": NotificationEventType.RUN_COMPLETED.value,
        "occurrence_id": str(uuid.uuid4()),
        "summary": "A run finished.",
        "context_url": None,
        "render_context": None,
        "in_app_visible": True,
        "announcement_id": None,
        "read_at": None,
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return Notification(**fields)


@pytest.fixture
def client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=_USER_ID, organization_id=_ORGANIZATION_ID, role=OrgRoleName.MEMBER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_notification_center_service] = lambda: (
        NotificationCenterService(MagicMock())
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/notifications{suffix}"


def _admin_url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/admin/notifications/deliveries{suffix}"


def _delivery_row(**overrides) -> NotificationDelivery:
    fields = {
        "id": uuid.uuid4(),
        "notification_id": uuid.uuid4(),
        "channel": "email",
        "status": "failed",
        "attempts": 5,
        "last_error": "provider rejected the message",
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return NotificationDelivery(**fields)


@pytest.fixture
def admin_client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    user = User(id=_USER_ID, email="root@example.com", hashed_password="x", is_app_admin=True)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_notification_delivery_service] = lambda: (
        NotificationDeliveryService(MagicMock())
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture
def non_admin_client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    user = User(id=_USER_ID, email="member@example.com", hashed_password="x", is_app_admin=False)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


class TestListing:
    async def test_a_full_page_carries_a_next_cursor(self, client: OpenClient):
        rows = [_row(), _row()]
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.list_inbox_page",
            new=AsyncMock(return_value=rows),
        ):
            async with client() as http:
                response = await http.get(_url(), params={"limit": 2})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is not None

    async def test_a_short_page_carries_no_next_cursor(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.list_inbox_page",
            new=AsyncMock(return_value=[_row()]),
        ):
            async with client() as http:
                response = await http.get(_url(), params={"limit": 50})
        assert response.status_code == 200
        assert response.json()["next_cursor"] is None

    async def test_a_malformed_cursor_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.get(_url(), params={"cursor": "not-a-cursor"})
        assert response.status_code == 400

    async def test_an_empty_inbox_returns_an_empty_list(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.list_inbox_page",
            new=AsyncMock(return_value=[]),
        ):
            async with client() as http:
                response = await http.get(_url())
        assert response.status_code == 200
        assert response.json() == {"items": [], "next_cursor": None}


class TestUnreadCount:
    async def test_counts_only_gate_visible_rows(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.list_unread",
            new=AsyncMock(return_value=[_row(), _row()]),
        ):
            async with client() as http:
                response = await http.get(_url("/unread-count"))
        assert response.status_code == 200
        assert response.json() == {"count": 2}


class TestMarkOneRead:
    async def test_marking_a_row_read_returns_it(self, client: OpenClient):
        row = _row()
        with (
            patch(
                f"{NOTIFICATION_PATH}.notification_repo.get_own", new=AsyncMock(return_value=row)
            ),
            patch(
                f"{NOTIFICATION_PATH}.notification_repo.mark_read",
                new=AsyncMock(side_effect=lambda _db, n, *, read_at: _mark(n, read_at)),
            ),
        ):
            async with client() as http:
                response = await http.patch(_url(f"/{row.id}"))
        assert response.status_code == 200
        assert response.json()["read_at"] is not None

    async def test_a_missing_row_is_404(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.get_own", new=AsyncMock(return_value=None)
        ):
            async with client() as http:
                response = await http.patch(_url(f"/{uuid.uuid4()}"))
        assert response.status_code == 404


def _mark(notification: Notification, read_at: datetime) -> Notification:
    notification.read_at = read_at
    return notification


class TestMarkAllRead:
    async def test_returns_the_number_marked(self, client: OpenClient):
        with (
            patch(
                f"{NOTIFICATION_PATH}.notification_repo.list_unread",
                new=AsyncMock(return_value=[_row(), _row(), _row()]),
            ),
            patch(
                f"{NOTIFICATION_PATH}.notification_repo.mark_ids_read",
                new=AsyncMock(return_value=3),
            ),
        ):
            async with client() as http:
                response = await http.post(_url("/mark-all-read"))
        assert response.status_code == 200
        assert response.json() == {"marked": 3}


def _stored_preference(**overrides) -> NotificationChannelPreference:
    fields = {
        "id": uuid.uuid4(),
        "user_id": _USER_ID,
        "event_type": NotificationEventType.RUN_FAILED.value,
        "channel": "email",
        "enabled": False,
    }
    fields.update(overrides)
    return NotificationChannelPreference(**fields)


class TestPreferences:
    async def test_lists_every_togglable_pair_with_defaults_applied(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.list_channel_preferences",
            new=AsyncMock(return_value=[_stored_preference()]),
        ):
            async with client() as http:
                response = await http.get(_url("/preferences"))
        assert response.status_code == 200
        items = response.json()["items"]

        # Mandatory event types have no preference at all.
        assert not any(item["event_type"] == "security_event" for item in items)
        assert not any(item["event_type"] == "configuration_changed" for item in items)
        # The four legacy-column pairs stay `PATCH /users/me`'s.
        assert not any(
            item["event_type"] == "budget_exceeded" and item["channel"] == "email" for item in items
        )
        assert any(
            item["event_type"] == "budget_exceeded" and item["channel"] == "in_app"
            for item in items
        )
        # An untouched pair defaults enabled; the stored one reflects its row.
        run_completed = next(
            item
            for item in items
            if item["event_type"] == "run_completed" and item["channel"] == "in_app"
        )
        assert run_completed["enabled"] is True
        run_failed_email = next(
            item
            for item in items
            if item["event_type"] == "run_failed" and item["channel"] == "email"
        )
        assert run_failed_email["enabled"] is False

    async def test_updating_a_pair_returns_the_new_value(self, client: OpenClient):
        with patch(
            f"{NOTIFICATION_PATH}.notification_repo.upsert_channel_preference",
            new=AsyncMock(
                return_value=_stored_preference(
                    event_type=NotificationEventType.RUN_COMPLETED.value,
                    channel="in_app",
                    enabled=False,
                )
            ),
        ) as upsert:
            async with client() as http:
                response = await http.patch(
                    _url("/preferences"),
                    json={"event_type": "run_completed", "channel": "in_app", "enabled": False},
                )
        assert response.status_code == 200
        assert response.json() == {
            "event_type": "run_completed",
            "channel": "in_app",
            "enabled": False,
        }
        assert upsert.call_args.kwargs["user_id"] == _USER_ID
        assert upsert.call_args.kwargs["enabled"] is False

    async def test_a_mandatory_event_type_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.patch(
                _url("/preferences"),
                json={"event_type": "security_event", "channel": "in_app", "enabled": False},
            )
        assert response.status_code == 400

    async def test_a_legacy_email_pair_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.patch(
                _url("/preferences"),
                json={"event_type": "budget_exceeded", "channel": "email", "enabled": False},
            )
        assert response.status_code == 400

    async def test_an_unknown_event_type_is_rejected(self, client: OpenClient):
        async with client() as http:
            response = await http.patch(
                _url("/preferences"),
                json={"event_type": "not_a_real_event", "channel": "in_app", "enabled": False},
            )
        assert response.status_code == 422


DELIVERY_PATH = "app.services.notification_delivery"


class TestFailedDeliveries:
    async def test_an_app_admin_sees_the_failed_deliveries(self, admin_client: OpenClient):
        notification = _row(event_type=NotificationEventType.BUDGET_EXCEEDED.value)
        delivery = _delivery_row(notification_id=notification.id)
        with patch(
            f"{DELIVERY_PATH}.notification_repo.list_failed_deliveries",
            new=AsyncMock(return_value=([(delivery, notification)], 1)),
        ):
            async with admin_client() as http:
                response = await http.get(_admin_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(delivery.id)
        assert body["items"][0]["notification_id"] == str(notification.id)
        assert body["items"][0]["event_type"] == NotificationEventType.BUDGET_EXCEEDED.value
        assert body["items"][0]["attempts"] == 5
        assert body["items"][0]["last_error"] == "provider rejected the message"

    async def test_an_ordinary_member_is_refused(self, non_admin_client: OpenClient):
        async with non_admin_client() as http:
            response = await http.get(_admin_url())
        assert response.status_code == 403

    async def test_an_unrecognised_status_is_rejected(self, admin_client: OpenClient):
        async with admin_client() as http:
            response = await http.get(_admin_url(), params={"status": "sent"})
        assert response.status_code == 422
