"""Tests for user routes."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

# UserService methods are async for every database, so mock them with AsyncMock.
ServiceMock = AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_user_service
from app.api.deps import get_db_session
from app.api.deps import get_redis
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app


class MockUser:
    """Mock user for testing."""

    def __init__(
        self,
        id=None,
        email="test@example.com",
        full_name="Test User",
        is_active=True,
        is_app_admin=False,
    ):
        self.id = id or uuid4()
        self.email = email
        self.full_name = full_name
        self.is_active = is_active
        self.is_app_admin = is_app_admin
        self.hashed_password = "hashed"
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self.notify_budget_alerts = True
        self.notify_approval_requests = True
        self.notify_usage_reports = True


@pytest.fixture
def mock_user() -> MockUser:
    """Create a mock regular user."""
    return MockUser()


@pytest.fixture
def mock_superuser() -> MockUser:
    """Create a mock platform admin. One flag, and it is the only one there is."""
    return MockUser(email="admin@example.com", is_app_admin=True)


@pytest.fixture
def mock_user_service(mock_user: MockUser) -> MagicMock:
    """Create a mock user service."""
    service = MagicMock()
    service.get_by_id = ServiceMock(return_value=mock_user)
    service.get_multi = ServiceMock(return_value=[mock_user])
    service.update = ServiceMock(return_value=mock_user)
    service.delete = ServiceMock(return_value=mock_user)
    return service


@pytest.fixture
async def auth_client(
    mock_user: MockUser,
    mock_user_service: MagicMock,
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncClient:
    """Client with authenticated regular user."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def superuser_client(
    mock_superuser: MockUser,
    mock_user_service: MagicMock,
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncClient:
    """Client with an authenticated app admin.

    Only `get_current_user` is overridden. `_require_app_admin` reads the flag
    off whatever that returns, so there is no separate superuser dependency to
    stand in for - which is the point of there being one privilege rather than
    two spellings of it.
    """
    app.dependency_overrides[get_current_user] = lambda: mock_superuser
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_read_current_user(auth_client: AsyncClient, mock_user: MockUser):
    """Test getting current user."""
    response = await auth_client.get(f"{settings.API_V1_STR}/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == mock_user.email


@pytest.mark.anyio
async def test_update_current_user(auth_client: AsyncClient, mock_user_service: MagicMock):
    """Test updating current user."""
    response = await auth_client.patch(
        f"{settings.API_V1_STR}/users/me",
        json={"full_name": "Updated Name"},
    )
    assert response.status_code == 200
    mock_user_service.update.assert_called_once()


@pytest.mark.anyio
async def test_update_current_user_notification_preferences_reach_the_service(
    auth_client: AsyncClient, mock_user_service: MagicMock
):
    """The settings page saves through PATCH /users/me; a preference that the
    route drops on the floor is the old lying toggle with extra steps."""
    response = await auth_client.patch(
        f"{settings.API_V1_STR}/users/me",
        json={"notify_usage_reports": False, "notify_budget_alerts": False},
    )
    assert response.status_code == 200
    user_in = mock_user_service.update.call_args.args[1]
    assert user_in.notify_usage_reports is False
    assert user_in.notify_budget_alerts is False
    assert user_in.notify_approval_requests is None  # untouched, not defaulted


@pytest.mark.anyio
async def test_read_current_user_reports_notification_preferences(
    auth_client: AsyncClient,
):
    """The page renders what GET /users/me says: the stored preferences must
    survive serialization, or every switch shows the schema default instead."""
    response = await auth_client.get(f"{settings.API_V1_STR}/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["notify_budget_alerts"] is True
    assert data["notify_approval_requests"] is True
    assert data["notify_usage_reports"] is True


@pytest.mark.anyio
async def test_read_user_by_id(
    superuser_client: AsyncClient,
    mock_user: MockUser,
    mock_user_service: MagicMock,
):
    """Test getting user by ID as superuser."""
    response = await superuser_client.get(f"{settings.API_V1_STR}/users/{mock_user.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == mock_user.email


@pytest.mark.anyio
async def test_read_user_by_id_not_found(
    superuser_client: AsyncClient,
    mock_user_service: MagicMock,
):
    """Test getting non-existent user."""
    mock_user_service.get_by_id = ServiceMock(side_effect=NotFoundError(message="User not found"))

    response = await superuser_client.get(f"{settings.API_V1_STR}/users/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_update_user_by_id(
    superuser_client: AsyncClient,
    mock_user: MockUser,
    mock_user_service: MagicMock,
):
    """Test updating user by ID as superuser."""
    response = await superuser_client.patch(
        f"{settings.API_V1_STR}/users/{mock_user.id}",
        json={"full_name": "Admin Updated"},
    )
    assert response.status_code == 200
    mock_user_service.update.assert_called_once()


@pytest.mark.anyio
async def test_delete_user_by_id(
    superuser_client: AsyncClient,
    mock_user: MockUser,
    mock_user_service: MagicMock,
):
    """Test deleting user by ID as superuser."""
    response = await superuser_client.delete(f"{settings.API_V1_STR}/users/{mock_user.id}")
    assert response.status_code == 204
    mock_user_service.delete.assert_called_once()


@pytest.mark.anyio
async def test_delete_user_by_id_not_found(
    superuser_client: AsyncClient,
    mock_user_service: MagicMock,
):
    """Test deleting non-existent user."""

    mock_user_service.delete = ServiceMock(side_effect=NotFoundError(message="User not found"))

    response = await superuser_client.delete(f"{settings.API_V1_STR}/users/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_an_admin_password_change_is_audited_by_field_not_by_value(
    superuser_client: AsyncClient,
    mock_user: MockUser,
    mock_db_session,
):
    """The trail records what an administrator changed, never what they typed.

    `UserUpdate` carries `password`, and the audit entry used to be the request
    body dumped whole - so resetting a password for somebody wrote their new
    plaintext into `app_admin_audit_logs.details`, a JSONB column that outlives
    the session and is readable by anything that can read the trail (#342).
    """
    response = await superuser_client.patch(
        f"{settings.API_V1_STR}/admin/users/{mock_user.id}",
        json={"password": "correct-horse-battery", "full_name": "Renamed"},
    )

    assert response.status_code == 200
    entry = mock_db_session.add.call_args.args[0]
    assert entry.action == "admin.user.update"
    assert entry.details == {"fields": ["full_name", "password"]}
