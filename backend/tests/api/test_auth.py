# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""Tests for authentication routes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

ServiceMock = AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_session_id, get_current_user, get_user_service
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, AuthenticationError
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.main import app
from app.api.deps import get_redis
from app.api.deps import get_db_session
from app.api.deps import get_session_service


class MockUser:
    """Mock user for testing."""

    def __init__(
        self,
        id=None,
        email="test@example.com",
        full_name="Test User",
        is_active=True,
        role="user",
    ):
        self.id = id or uuid4()
        self.email = email
        self.full_name = full_name
        self.is_active = is_active
        self.role = role
        self.hashed_password = "hashed"
        self.credential_version = 0
        self.avatar_url = None
        self.oauth_provider = None
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)


@pytest.fixture
def mock_user() -> MockUser:
    """Create a mock user."""
    return MockUser()


@pytest.fixture
def mock_user_service(mock_user: MockUser) -> MagicMock:
    """Create a mock user service."""
    service = MagicMock()
    service.authenticate = ServiceMock(return_value=mock_user)
    service.register = ServiceMock(return_value=mock_user)
    service.get_by_id = ServiceMock(return_value=mock_user)
    service.get_by_email = ServiceMock(return_value=mock_user)
    return service


@pytest.fixture
async def client_with_mock_service(
    mock_user_service: MagicMock,
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncClient:
    """Client with mocked user service."""
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
async def test_login_success(client_with_mock_service: AsyncClient):
    """Test successful login."""
    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/login",
        data={"username": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.anyio
async def test_login_names_its_session_in_the_access_token(
    mock_user_service: MagicMock, mock_redis: MagicMock, mock_db_session
) -> None:
    """The access token carries the id of the session login opened, so a later
    password change can spare this session while revoking the account's rest (#1439)."""
    session_id = uuid4()
    session_service = MagicMock()
    session_service.create_session = AsyncMock(return_value=SimpleNamespace(id=session_id))

    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    app.dependency_overrides[get_session_service] = lambda: session_service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"{settings.API_V1_STR}/auth/login",
                data={"username": "test@example.com", "password": "password123"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = verify_token(response.json()["access_token"])
    assert payload is not None
    assert payload["sid"] == str(session_id)


@pytest.mark.anyio
async def test_magic_link_binds_the_access_token_to_its_session(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
    mock_user: MockUser,
):
    """A magic-link sign-in is a session like any other, bound to its row."""
    mock_user_service.consume_magic_link_token = ServiceMock(return_value=(mock_user, None))
    session_id = uuid4()
    session_service = MagicMock()
    session_service.create_session = ServiceMock(return_value=MagicMock(id=session_id))
    app.dependency_overrides[get_session_service] = lambda: session_service

    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/magic-link/verify",
        json={"token": "a-magic-token"},
    )

    assert response.status_code == 200
    payload = verify_token(response.json()["access_token"])
    assert payload is not None
    assert payload["sid"] == str(session_id)


@pytest.mark.anyio
async def test_refresh_keeps_the_session_and_rebinds_the_new_token(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
    mock_user: MockUser,
):
    """Refresh rotates the row in place: the new access token carries the *same*
    `sid`, and no second row is created, so a live socket is not cut off (#1501)."""
    session_id = uuid4()
    session = MagicMock(id=session_id, user_id=mock_user.id)
    session_service = MagicMock()
    session_service.validate_refresh_token = ServiceMock(return_value=session)
    session_service.rotate_session = ServiceMock(return_value=session)
    session_service.create_session = ServiceMock()
    app.dependency_overrides[get_session_service] = lambda: session_service

    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/refresh",
        json={
            "refresh_token": create_refresh_token(subject=str(mock_user.id), credential_version=0)
        },
    )

    assert response.status_code == 200
    payload = verify_token(response.json()["access_token"])
    assert payload is not None
    assert payload["sid"] == str(session_id)
    session_service.rotate_session.assert_awaited_once()
    session_service.create_session.assert_not_awaited()


@pytest.mark.anyio
async def test_get_current_session_id_reads_the_sid_claim() -> None:
    session_id = uuid4()
    token = create_access_token(subject=str(uuid4()), sid=str(session_id))
    assert await get_current_session_id(token) == session_id


@pytest.mark.anyio
async def test_get_current_session_id_is_none_without_a_token() -> None:
    assert await get_current_session_id(None) is None


@pytest.mark.anyio
async def test_get_current_session_id_is_none_for_a_token_carrying_no_session() -> None:
    token = create_access_token(subject=str(uuid4()))
    assert await get_current_session_id(token) is None


@pytest.mark.anyio
async def test_get_current_session_id_is_none_for_an_unparsable_session_claim() -> None:
    token = create_access_token(subject=str(uuid4()), sid="not-a-uuid")
    assert await get_current_session_id(token) is None


@pytest.mark.anyio
async def test_get_current_session_id_is_none_for_an_unverifiable_token() -> None:
    """A garbled or expired token is no session to spare, not a refusal - the
    route it serves already authenticated through `CurrentUser`."""
    assert await get_current_session_id("not-a-real-jwt") is None


@pytest.mark.anyio
async def test_refresh_refuses_a_token_behind_the_credential_version(
    mock_redis: MagicMock, mock_db_session
) -> None:
    """A refresh token minted before a password change carries the old credential
    version, so it cannot rotate past the change even if its session row is still
    active - the close on the revocation race (#1517)."""
    user = MockUser()
    user.credential_version = 5
    user_service = MagicMock()
    user_service.get_by_id = AsyncMock(return_value=user)
    session_service = MagicMock()
    session_service.validate_refresh_token = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), user_id=user.id)
    )
    session_service.rotate_session = AsyncMock()
    stale = create_refresh_token(subject=str(user.id), credential_version=4)

    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"{settings.API_V1_STR}/auth/refresh", json={"refresh_token": stale}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401
    session_service.rotate_session.assert_not_called()


@pytest.mark.anyio
async def test_refresh_at_the_current_version_mints_a_token_carrying_it(
    mock_redis: MagicMock, mock_db_session
) -> None:
    """A token at the account's current version rotates, and the token it mints
    carries that version so the chain stays valid until the next change (#1517)."""
    user = MockUser()
    user.credential_version = 5
    user_service = MagicMock()
    user_service.get_by_id = AsyncMock(return_value=user)
    session_service = MagicMock()
    session_service.validate_refresh_token = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), user_id=user.id)
    )
    session_service.rotate_session = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    current = create_refresh_token(subject=str(user.id), credential_version=5)

    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"{settings.API_V1_STR}/auth/refresh", json={"refresh_token": current}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    minted = verify_token(resp.json()["refresh_token"])
    assert minted is not None
    assert minted["cv"] == 5


@pytest.mark.anyio
async def test_a_password_change_needs_a_signed_in_caller(
    mock_user_service: MagicMock, mock_redis: MagicMock, mock_db_session
) -> None:
    """The endpoint is authenticated: no token, no change (#1517)."""
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"{settings.API_V1_STR}/auth/password/change",
                json={"current_password": "old", "new_password": "newpassword123"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_a_password_change_returns_a_fresh_session_at_the_new_version(
    mock_user: MockUser, mock_user_service: MagicMock, mock_redis: MagicMock, mock_db_session
) -> None:
    """The change revokes every session, the caller's own included, so the route
    opens a fresh one and hands back its tokens - keeping the one who made the
    change signed in, on a refresh token carrying the new version (#1517)."""
    mock_user.credential_version = 3
    mock_user_service.change_password = AsyncMock(return_value=mock_user)
    session_service = MagicMock()
    session_service.create_session = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"{settings.API_V1_STR}/auth/password/change",
                json={"current_password": "old-password", "new_password": "newpassword123"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    minted = verify_token(body["refresh_token"])
    assert minted is not None
    assert minted["cv"] == 3
    session_service.create_session.assert_awaited_once()
    kwargs = mock_user_service.change_password.await_args.kwargs
    assert kwargs["current_password"] == "old-password"
    assert kwargs["new_password"] == "newpassword123"
    assert "current_session_id" not in kwargs


@pytest.mark.anyio
async def test_a_wrong_current_password_is_refused_with_a_401(
    mock_user: MockUser, mock_user_service: MagicMock, mock_redis: MagicMock, mock_db_session
) -> None:
    """The service's refusal reaches the caller as a 401, not a 500, and mints no
    session (#1517)."""
    mock_user_service.change_password = AsyncMock(
        side_effect=AuthenticationError(message="Current password is incorrect")
    )
    session_service = MagicMock()
    session_service.create_session = AsyncMock()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"{settings.API_V1_STR}/auth/password/change",
                json={"current_password": "wrong", "new_password": "newpassword123"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 401
    session_service.create_session.assert_not_called()


@pytest.mark.anyio
async def test_login_invalid_credentials(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
):
    """Test login with invalid credentials."""
    mock_user_service.authenticate = ServiceMock(
        side_effect=AuthenticationError(message="Invalid credentials")
    )

    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/login",
        data={"username": "test@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_register_success(client_with_mock_service: AsyncClient):
    """Test successful registration."""
    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "email": "new@example.com",
            "password": "password123",
            "full_name": "New User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"  # From mock


@pytest.mark.anyio
async def test_register_duplicate_email(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
):
    """Test registration with duplicate email."""
    mock_user_service.register = ServiceMock(
        side_effect=AlreadyExistsError(message="Email already registered")
    )

    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "email": "existing@example.com",
            "password": "password123",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_register_through_a_staged_invitation_resolves_the_handle(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
    mock_redis: MagicMock,
):
    """A first-time invitee registers with no token in the body - it was exchanged
    for an httpOnly handle before they reached the form (#1414). The route peeks
    the handle and feeds the sign-up admission the token it resolves to, leaving
    the handle intact for the acceptance that follows sign-in."""
    mock_redis.get = AsyncMock(return_value="staged-token")

    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "new@example.com", "password": "password123"},
        headers={"X-Invitation-Handle": "an-opaque-handle"},
    )

    assert response.status_code == 201
    submitted = mock_user_service.register.call_args.args[0]
    assert submitted.invitation_token == "staged-token"


@pytest.mark.anyio
async def test_register_without_a_handle_carries_no_invitation(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
):
    """The header is optional: an open deployment's registration never sends one,
    and the token stays whatever the body carried (here, nothing)."""
    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "new@example.com", "password": "password123"},
    )

    assert response.status_code == 201
    submitted = mock_user_service.register.call_args.args[0]
    assert submitted.invitation_token is None


@pytest.mark.anyio
async def test_get_current_user(
    client_with_mock_service: AsyncClient,
    mock_user: MockUser,
    mock_user_service: MagicMock,
):
    """Test getting current user info."""
    # Override get_current_user to return mock user
    app.dependency_overrides[get_current_user] = lambda: mock_user

    response = await client_with_mock_service.get(
        f"{settings.API_V1_STR}/auth/me",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == mock_user.email
