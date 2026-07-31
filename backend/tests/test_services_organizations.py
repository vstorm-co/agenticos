"""Tests for OrganizationService."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.schemas.user import UserCreate
from app.services.organization import OrganizationService
from app.services.user import UserService


class TestOrganizationService:
    """Tests for OrganizationService (PostgreSQL async)."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return OrganizationService(mock_db)

    @pytest.mark.anyio
    async def test_create_generates_slug_when_absent(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.id = uuid.uuid4()
        mock_member = MagicMock()

        with (
            patch(
                "app.services.organization.organization_repo.slug_exists",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="my-org"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=mock_org),
            ),
            patch(
                "app.services.organization.member_repo.create",
                new=AsyncMock(return_value=mock_member),
            ),
        ):
            result = await service.create(
                OrganizationCreate(name="My Org"),
                owner_id=uuid.uuid4(),
            )

        assert result == mock_org

    @pytest.mark.anyio
    async def test_create_raises_if_slug_taken(self, service, mock_db):
        with (
            patch(
                "app.services.organization.organization_repo.slug_exists",
                new=AsyncMock(return_value=True),
            ),
            pytest.raises(AlreadyExistsError) as refused,
        ):
            await service.create(
                OrganizationCreate(name="Taken", slug="taken-slug"),
                owner_id=uuid.uuid4(),
            )

        # A slug is optional - leaving it blank derives a unique one - so the
        # refusal is only useful if it says so. "Slug already taken" left the
        # reader guessing at a field they never had to fill in.
        assert "taken-slug" in refused.value.message
        assert "leave it blank" in refused.value.message

    @pytest.mark.anyio
    async def test_create_personal_org(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.id = uuid.uuid4()

        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="alice"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=mock_org),
            ),
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
        ):
            result = await service.create_personal_org(uuid.uuid4(), "alice@example.com")

        assert result == mock_org

    @pytest.mark.anyio
    async def test_delete_blocks_personal_org(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.is_personal = True
        mock_membership = MagicMock()
        mock_membership.role = "owner"

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(mock_org, mock_membership))
            ),
            pytest.raises(BadRequestError),
        ):
            await service.delete(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_delete_blocks_non_owner(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.is_personal = False
        mock_membership = MagicMock()
        mock_membership.role = "admin"

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(mock_org, mock_membership))
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.delete(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_delete_succeeds_for_owner(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.is_personal = False
        mock_membership = MagicMock()
        mock_membership.role = "owner"

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(mock_org, mock_membership))
            ),
            patch("app.services.organization.organization_repo.delete", new=AsyncMock()),
        ):
            await service.delete(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_update_requires_admin_or_owner(self, service, mock_db):
        mock_org = MagicMock()
        mock_membership = MagicMock()
        mock_membership.role = "member"

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(mock_org, mock_membership))
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(), OrganizationUpdate(name="New"), requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    @pytest.mark.parametrize("role", ["member", "builder", "operator", "viewer"])
    async def test_setting_the_monthly_cap_needs_the_budgets_manage_permission(
        self, service, mock_db, role
    ):
        """The spending ceiling is gated on `budgets:manage`, held by Owner and Admin.

        A role that cannot configure the organization must not be able to
        raise what it may spend.
        """
        membership = MagicMock(role=role)

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(MagicMock(), membership))
            ),
            patch(
                "app.services.organization.organization_repo.set_monthly_budget", new=AsyncMock()
            ) as write,
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(monthly_budget_usd=Decimal("500")),
                requester_id=uuid.uuid4(),
            )

        write.assert_not_awaited()

    @pytest.mark.anyio
    async def test_the_cap_and_the_metadata_are_separate_entitlements(
        self, service, mock_db, monkeypatch
    ):
        """`budgets:manage` moves the ceiling; `org:settings` renames. Not each other.

        The built-in Owner and Admin hold both, so only a synthetic role can
        prove the check reads the right permission for the right field - which
        is what makes the `budgets:manage` row in the catalog mean something.
        """
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:budgets-only", {Perm.BUDGETS_MANAGE: Scope.ALL})
        membership = MagicMock(role="test:budgets-only")
        org = MagicMock()

        with (
            patch.object(service, "get_for_user", new=AsyncMock(return_value=(org, membership))),
            patch(
                "app.services.organization.organization_repo.set_monthly_budget",
                new=AsyncMock(return_value=org),
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(monthly_budget_usd=Decimal("500")),
                requester_id=uuid.uuid4(),
            )
        write.assert_awaited_once()

        with (
            patch.object(service, "get_for_user", new=AsyncMock(return_value=(org, membership))),
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(), OrganizationUpdate(name="Renamed"), requester_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_an_update_that_does_not_name_the_cap_leaves_it_alone(self, service, mock_db):
        """Renaming an organization must not uncap it.

        `None` is a legal value for this field - it is how the ceiling is
        removed - so a service keying on the value rather than on whether the
        client named it would lift the limit on every rename.
        """
        membership = MagicMock(role="owner")

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(MagicMock(), membership))
            ),
            patch(
                "app.services.organization.organization_repo.set_monthly_budget", new=AsyncMock()
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(), OrganizationUpdate(name="Renamed"), requester_id=uuid.uuid4()
            )

        write.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("limit", [Decimal("500"), None])
    async def test_naming_the_cap_writes_exactly_what_was_named(self, service, mock_db, limit):
        """Including an explicit `null`, which is how the ceiling is lifted."""
        membership = MagicMock(role="owner")
        org = MagicMock()

        with (
            patch.object(service, "get_for_user", new=AsyncMock(return_value=(org, membership))),
            patch(
                "app.services.organization.organization_repo.set_monthly_budget",
                new=AsyncMock(return_value=org),
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate.model_validate({"monthly_budget_usd": limit}),
                requester_id=uuid.uuid4(),
            )

        assert write.await_args.kwargs["limit_usd"] == limit

    @pytest.mark.anyio
    async def test_a_cap_of_zero_is_refused_before_it_reaches_the_database(self):
        """Zero is an organization whose agents can never answer.

        The column refuses it too; refusing it here is what turns a 500 into a
        422 that names the field.
        """
        with pytest.raises(ValidationError):
            OrganizationUpdate(monthly_budget_usd=Decimal("0"))

    @pytest.mark.anyio
    async def test_get_for_user_raises_if_not_member(self, service, mock_db):
        with (
            patch("app.services.organization.member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.get_for_user(uuid.uuid4(), uuid.uuid4())


class TestUserServiceRegistrationWithOrg:
    """Tests that UserService.register creates a Personal Org."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.anyio
    async def test_register_creates_personal_org(self, mock_db):
        mock_user = MagicMock()
        mock_user.id = MagicMock()

        with (
            patch("app.services.user.user_repo.get_by_email", new=AsyncMock(return_value=None)),
            patch("app.services.user.user_repo.create", new=AsyncMock(return_value=mock_user)),
            patch(
                "app.services.user.OrganizationService.create_personal_org", new=AsyncMock()
            ) as mock_create_org,
        ):
            svc = UserService(mock_db)
            await svc.register(UserCreate(email="new@example.com", password="password123"))

        mock_create_org.assert_called_once()
