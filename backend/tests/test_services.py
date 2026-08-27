"""Tests for service layer."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
)
from app.schemas.user import UserCreate, UserUpdate
from app.services.user import _DUMMY_HASH, UserService


class MockUser:
    """Mock user for testing."""

    def __init__(
        self,
        id=None,
        email="test@example.com",
        full_name="Test User",
        hashed_password="$2b$12$hashedpassword",
        is_active=True,
        role="user",
    ):
        self.id = id or uuid4()
        self.email = email
        self.full_name = full_name
        self.hashed_password = hashed_password
        self.is_active = is_active
        self.role = role


class TestUserServicePostgresql:
    """Tests for UserService with PostgreSQL."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def user_service(self, mock_db: AsyncMock) -> UserService:
        """Create UserService instance with mock db."""
        return UserService(mock_db)

    @pytest.fixture
    def mock_user(self) -> MockUser:
        """Create a mock user."""
        return MockUser()

    @pytest.mark.anyio
    async def test_get_by_id_success(self, user_service: UserService, mock_user: MockUser):
        """Test getting user by ID successfully."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)

            result = await user_service.get_by_id(mock_user.id)

            assert result == mock_user
            mock_repo.get_by_id.assert_called_once()

    @pytest.mark.anyio
    async def test_get_by_id_not_found(self, user_service: UserService):
        """Test getting non-existent user raises NotFoundError."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await user_service.get_by_id(uuid4())

    @pytest.mark.anyio
    async def test_get_by_email(self, user_service: UserService, mock_user: MockUser):
        """Test getting user by email."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_email = AsyncMock(return_value=mock_user)

            result = await user_service.get_by_email("test@example.com")

            assert result == mock_user

    @pytest.mark.anyio
    async def test_get_multi(self, user_service: UserService, mock_user: MockUser):
        """Test getting multiple users."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_multi = AsyncMock(return_value=[mock_user])

            result = await user_service.get_multi(skip=0, limit=10)

            assert len(result) == 1
            assert result[0] == mock_user

    @pytest.mark.anyio
    async def test_register_success(self, user_service: UserService, mock_user: MockUser):
        """Test registering a new user."""
        # Stub the count-of-users SELECT used by the first-user → app-admin
        # promotion. Side effects we don't care about (welcome email, personal
        # org creation, count query) are mocked out so the test stays focused
        # on user_repo.create being invoked.
        scalar_one_result = MagicMock()
        scalar_one_result.scalar_one.return_value = 1
        # And the deployment settings row the sign-up policy reads: no row means
        # every default, which is `open`. Left as a bare MagicMock it is a truthy
        # row whose `allowed_email_domains` is also truthy, so the policy refuses
        # for a rule nobody configured.
        scalar_one_result.scalar_one_or_none.return_value = None
        user_service.db.execute = AsyncMock(return_value=scalar_one_result)

        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.OrganizationService") as mock_org_svc,
            patch("app.services.user.get_email_service") as mock_email,
        ):
            mock_repo.get_by_email = AsyncMock(return_value=None)
            mock_repo.create = AsyncMock(return_value=mock_user)
            mock_org_svc.return_value.create_personal_org = AsyncMock()
            mock_email.return_value.send_welcome = AsyncMock()

            user_in = UserCreate(
                email="new@example.com",
                password="password123",
                full_name="New User",
            )
            result = await user_service.register(user_in)

            assert result == mock_user
            mock_repo.create.assert_called_once()

    @pytest.mark.anyio
    async def test_register_duplicate_email(self, user_service: UserService, mock_user: MockUser):
        """Test registering with existing email raises AlreadyExistsError."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_email = AsyncMock(return_value=mock_user)

            user_in = UserCreate(
                email="existing@example.com",
                password="password123",
                full_name="Test",
            )

            with pytest.raises(AlreadyExistsError):
                await user_service.register(user_in)

    @pytest.mark.anyio
    async def test_authenticate_success(self, user_service: UserService, mock_user: MockUser):
        """Test successful authentication."""
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.verify_password", return_value=True),
        ):
            mock_repo.get_by_email = AsyncMock(return_value=mock_user)

            result = await user_service.authenticate("test@example.com", "password123")

            assert result == mock_user

    @pytest.mark.anyio
    async def test_authenticate_invalid_password(
        self, user_service: UserService, mock_user: MockUser
    ):
        """Test authentication with wrong password."""
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.verify_password", return_value=False),
        ):
            mock_repo.get_by_email = AsyncMock(return_value=mock_user)

            with pytest.raises(AuthenticationError):
                await user_service.authenticate("test@example.com", "wrongpassword")

    @pytest.mark.anyio
    async def test_authenticate_user_not_found(self, user_service: UserService):
        """Test authentication with non-existent user."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_email = AsyncMock(return_value=None)

            with pytest.raises(AuthenticationError):
                await user_service.authenticate("unknown@example.com", "password")

    @pytest.mark.anyio
    async def test_authenticate_inactive_user(self, user_service: UserService):
        """Test authentication with inactive user."""
        inactive_user = MockUser(is_active=False)
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.verify_password", return_value=True),
        ):
            mock_repo.get_by_email = AsyncMock(return_value=inactive_user)

            with pytest.raises(AuthenticationError):
                await user_service.authenticate("test@example.com", "password")

    @pytest.mark.anyio
    async def test_authenticate_runs_bcrypt_off_the_event_loop(
        self, user_service: UserService, mock_user: MockUser
    ):
        """bcrypt is ~170ms with no suspension point, so an unmetered /login flood
        saturates a worker's event loop (#947). It runs in a thread now: while it
        blocks in there, the loop keeps turning. If it ran on the loop, the poll
        below could never observe `in_bcrypt` and the test would hang.
        """
        gate = threading.Event()
        in_bcrypt = threading.Event()

        def blocking_verify(_password: str, _hash: str) -> bool:
            in_bcrypt.set()
            gate.wait(timeout=5)
            return True

        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.verify_password", blocking_verify),
        ):
            mock_repo.get_by_email = AsyncMock(return_value=mock_user)
            login = asyncio.create_task(user_service.authenticate("test@example.com", "password"))
            try:
                # Waiting off the loop, so the loop stays free to run `login` up to
                # its own bcrypt. If bcrypt ran on the loop, `login` would block it
                # here and this would only resume once bcrypt finished - by which
                # point `login` is done and the assertion below fails.
                assert await asyncio.to_thread(in_bcrypt.wait, 5) is True
                assert not login.done()
            finally:
                gate.set()
            assert await login is mock_user

    @pytest.mark.anyio
    async def test_authenticate_runs_bcrypt_even_for_an_unknown_address(
        self, user_service: UserService
    ):
        """The timing oracle: an address with no account used to skip bcrypt and be
        refused in milliseconds, where a known one took ~170ms - two orders of
        magnitude, measurable over the internet (#947). An unknown address is now
        verified against `_DUMMY_HASH`, so both refuse in the same time.
        """
        checked: list[str] = []

        def recording_verify(_password: str, stored_hash: str) -> bool:
            checked.append(stored_hash)
            return False

        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch("app.services.user.verify_password", recording_verify),
        ):
            mock_repo.get_by_email = AsyncMock(return_value=None)

            with pytest.raises(AuthenticationError):
                await user_service.authenticate("nobody@example.com", "password")

        assert checked == [_DUMMY_HASH]

    @pytest.mark.anyio
    async def test_update_success(self, user_service: UserService, mock_user: MockUser):
        """Test updating user."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)
            mock_repo.update = AsyncMock(return_value=mock_user)

            user_update = UserUpdate(full_name="Updated Name")
            result = await user_service.update(mock_user.id, user_update)

            assert result == mock_user

    @pytest.mark.anyio
    async def test_update_with_password(self, user_service: UserService, mock_user: MockUser):
        """Test updating user with password change."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)
            mock_repo.update = AsyncMock(return_value=mock_user)

            user_update = UserUpdate(password="newpassword123")
            result = await user_service.update(mock_user.id, user_update)

            assert result == mock_user
            # Verify hashed_password was passed to update
            call_args = mock_repo.update.call_args
            assert "hashed_password" in call_args[1]["update_data"]

    @pytest.mark.anyio
    async def test_delete_success(self, user_service: UserService, mock_user: MockUser):
        """Test deleting user."""
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch.object(user_service, "_release_owned_rows", new=AsyncMock()),
        ):
            mock_repo.get_by_id_for_update = AsyncMock(return_value=mock_user)
            mock_repo.delete = AsyncMock(return_value=mock_user)

            result = await user_service.delete(mock_user.id)

            assert result == mock_user

    @pytest.mark.anyio
    async def test_delete_not_found(self, user_service: UserService):
        """A missing user is refused up front, before any teardown is attempted."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id_for_update = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await user_service.delete(uuid4())

    @pytest.mark.anyio
    async def test_an_admin_cannot_suspend_their_own_account(self, user_service: UserService):
        """is_active is enforced on the next request, so this signs the admin out
        of a deployment they administer - refused before the repo is touched (#941)."""
        me = uuid4()
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.update = AsyncMock()

            with pytest.raises(AuthorizationError):
                await user_service.admin_update(me, UserUpdate(is_active=False), acting_admin_id=me)

            mock_repo.update.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_app_admin_cannot_suspend_themselves_through_the_self_route(
        self, user_service: UserService
    ):
        """`/users/me` reaches the same `is_active` column as the admin route, so
        without the same guard it is the way around #941 - an app admin suspends
        themselves and the next request signs them out."""
        me = MagicMock(id=uuid4(), is_app_admin=True)
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.update = AsyncMock()

            with pytest.raises(AuthorizationError):
                await user_service.update_current(me, UserUpdate(is_active=False))

            mock_repo.update.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_non_admin_may_deactivate_their_own_account_through_the_self_route(
        self, user_service: UserService, mock_user: MockUser
    ):
        """The guard is the app admin's alone - a member deactivating their own
        row only affects themselves, and an admin can restore it."""
        mock_user.is_app_admin = False
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)
            mock_repo.update = AsyncMock(return_value=mock_user)

            await user_service.update_current(mock_user, UserUpdate(is_active=False))

            mock_repo.update.assert_awaited_once()

    @pytest.mark.anyio
    async def test_an_admin_may_suspend_another_user(
        self, user_service: UserService, mock_user: MockUser
    ):
        """The refusal is about your own row, not about suspension."""
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)
            mock_repo.update = AsyncMock(return_value=mock_user)

            await user_service.admin_update(
                mock_user.id, UserUpdate(is_active=False), acting_admin_id=uuid4()
            )

            mock_repo.update.assert_awaited_once()

    @pytest.mark.anyio
    async def test_an_admin_cannot_delete_their_own_account(self, user_service: UserService):
        """Deleting your own row takes administration with it on a single-admin
        install; because is_app_admin cannot be cleared over the API, refusing this
        is what keeps the last admin from being removed (#941)."""
        me = uuid4()
        with patch("app.services.user.user_repo") as mock_repo:
            mock_repo.delete = AsyncMock()

            with pytest.raises(AuthorizationError):
                await user_service.admin_delete(me, acting_admin_id=me)

            mock_repo.delete.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_admin_may_delete_another_user(
        self, user_service: UserService, mock_user: MockUser
    ):
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch.object(user_service, "_release_owned_rows", new=AsyncMock()),
        ):
            mock_repo.get_by_id_for_update = AsyncMock(return_value=mock_user)
            mock_repo.app_admin_ids_for_update = AsyncMock(return_value=[uuid4(), uuid4()])
            mock_repo.delete = AsyncMock(return_value=mock_user)

            await user_service.admin_delete(mock_user.id, acting_admin_id=uuid4())

            mock_repo.delete.assert_awaited_once()

    @pytest.mark.anyio
    async def test_the_last_app_admin_cannot_be_deleted_by_another_one(
        self, user_service: UserService, mock_user: MockUser
    ):
        """The not-self check states a lockout invariant and only held for one
        request at a time: A and B deleting each other both passed it, locked
        different rows and both committed (#1208). The check is on the set now, so
        whichever request re-reads it after the other commits is refused."""
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch.object(user_service, "_release_owned_rows", new=AsyncMock()),
        ):
            mock_repo.app_admin_ids_for_update = AsyncMock(return_value=[mock_user.id])
            mock_repo.delete = AsyncMock()

            with pytest.raises(AuthorizationError):
                await user_service.admin_delete(mock_user.id, acting_admin_id=uuid4())

            mock_repo.delete.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_ordinary_user_is_deletable_when_one_admin_is_left(
        self, user_service: UserService, mock_user: MockUser
    ):
        """The refusal is about the *set*, not about how small it is: a lone
        administrator deleting somebody else is the ordinary case."""
        lone_admin = uuid4()
        with (
            patch("app.services.user.user_repo") as mock_repo,
            patch.object(user_service, "_release_owned_rows", new=AsyncMock()),
        ):
            mock_repo.get_by_id_for_update = AsyncMock(return_value=mock_user)
            mock_repo.app_admin_ids_for_update = AsyncMock(return_value=[lone_admin])
            mock_repo.delete = AsyncMock(return_value=mock_user)

            await user_service.admin_delete(mock_user.id, acting_admin_id=lone_admin)

            mock_repo.delete.assert_awaited_once()
