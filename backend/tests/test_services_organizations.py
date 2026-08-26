"""Tests for OrganizationService."""

import uuid
from datetime import UTC, datetime
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
from app.db.models.organization import Organization, OrgRole
from app.schemas.deployment_settings import DeploymentLimits
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.schemas.user import UserCreate
from app.services.organization import OrganizationService
from app.services.user import UserService


def _org_row(*, name: str) -> Organization:
    """A real ORM row, because this one goes through the response schema.

    A `MagicMock` answers every attribute, including `member_count` and `role`
    - which are not on the row at all - so the assertions below would hold
    against a response that never carried them.
    """
    return Organization(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower(),
        is_personal=False,
        avatar_url=None,
        monthly_budget_usd=None,
        created_at=datetime(2026, 7, 31, tzinfo=UTC),
        updated_at=None,
    )


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

    @pytest.fixture(autouse=True)
    def _uncapped(self):
        """No deployment ceiling, which is what an installation that never set
        one has. Creating an organization reads it now, and a mocked session
        answers a `MagicMock` rather than a row."""
        with patch(
            "app.services.organization.DeploymentSettingsService.limits",
            new=AsyncMock(return_value=DeploymentLimits()),
        ):
            yield

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
            patch("app.services.organization.skill_library.library", return_value=()),
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
            patch("app.services.organization.skill_library.library", return_value=()),
        ):
            result = await service.create_personal_org(uuid.uuid4(), "alice@example.com")

        assert result == mock_org

    @pytest.mark.anyio
    async def test_a_new_team_org_starts_with_the_default_monthly_budget(self, service, mock_db):
        """A fresh org is not one runaway agent away from a surprise bill (#785)."""
        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="acme"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
            patch("app.services.organization.skill_library.library", return_value=()),
        ):
            await service.create(OrganizationCreate(name="Acme"), owner_id=uuid.uuid4())

        assert create.await_args.kwargs["monthly_budget_usd"] == Decimal("100")

    @pytest.mark.anyio
    async def test_a_personal_org_starts_with_the_default_monthly_budget(self, service, mock_db):
        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="alice"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
            patch("app.services.organization.skill_library.library", return_value=()),
        ):
            await service.create_personal_org(uuid.uuid4(), "alice@example.com")

        assert create.await_args.kwargs["monthly_budget_usd"] == Decimal("100")

    @pytest.mark.anyio
    async def test_the_default_budget_can_be_disabled(self, service, mock_db, monkeypatch):
        """`None` restores the older opt-in posture: a new org starts uncapped."""
        monkeypatch.setattr(
            "app.services.organization.settings.DEFAULT_ORG_MONTHLY_BUDGET_USD", None
        )
        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="acme"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
            patch("app.services.organization.skill_library.library", return_value=()),
        ):
            await service.create(OrganizationCreate(name="Acme"), owner_id=uuid.uuid4())

        assert create.await_args.kwargs["monthly_budget_usd"] is None

    @pytest.mark.anyio
    async def test_a_new_organization_starts_with_the_bundled_skills(self, service, mock_db):
        """Seeded at creation, not installed by hand (#281).

        A spec binds a skill by row id, so a bundled skill has to be a row
        before the Builder can offer it - and the row is written as the owner,
        with organization visibility, exactly as `seed-skills` writes it.
        """
        mock_org = MagicMock()
        mock_org.id = uuid.uuid4()
        owner_id = uuid.uuid4()
        bundled = MagicMock()
        bundled.key = "code-review"

        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="my-org"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=mock_org),
            ),
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
            patch("app.services.organization.skill_library.library", return_value=(bundled,)),
            patch("app.services.organization.SkillService") as skill_service,
        ):
            install = skill_service.return_value.install_from_library = AsyncMock()
            await service.create(OrganizationCreate(name="My Org"), owner_id=owner_id)

        install.assert_awaited_once()
        ctx, key = install.await_args.args
        assert key == "code-review"
        assert ctx.organization_id == mock_org.id
        assert ctx.user_id == owner_id

    @pytest.mark.anyio
    async def test_a_bundled_name_collision_skips_the_twin_rather_than_refusing_the_org(
        self, service, mock_db
    ):
        """Nothing validates the shipped library's own name uniqueness, and a
        packaging mistake there must not refuse every registration."""
        mock_org = MagicMock()
        mock_org.id = uuid.uuid4()
        first, twin = MagicMock(), MagicMock()
        first.key, twin.key = "refund-policy", "refund-policy-copy"

        with (
            patch(
                "app.services.organization.organization_repo.generate_unique_slug",
                new=AsyncMock(return_value="my-org"),
            ),
            patch(
                "app.services.organization.organization_repo.create",
                new=AsyncMock(return_value=mock_org),
            ),
            patch("app.services.organization.member_repo.create", new=AsyncMock()),
            patch("app.services.organization.skill_library.library", return_value=(first, twin)),
            patch("app.services.organization.SkillService") as skill_service,
        ):
            install = skill_service.return_value.install_from_library = AsyncMock(
                side_effect=[MagicMock(), AlreadyExistsError(message="taken")]
            )
            result = await service.create(OrganizationCreate(name="My Org"), owner_id=uuid.uuid4())

        assert result == mock_org
        assert install.await_count == 2

    @pytest.mark.anyio
    async def test_a_personal_organization_is_seeded_the_same_way(self, service, mock_db):
        mock_org = MagicMock()
        mock_org.id = uuid.uuid4()
        bundled = MagicMock()
        bundled.key = "refund-policy"

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
            patch("app.services.organization.skill_library.library", return_value=(bundled,)),
            patch("app.services.organization.SkillService") as skill_service,
        ):
            install = skill_service.return_value.install_from_library = AsyncMock()
            await service.create_personal_org(uuid.uuid4(), "alice@example.com")

        install.assert_awaited_once()
        assert install.await_args.args[1] == "refund-policy"

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
            patch(
                "app.services.organization.organization_repo.get_by_id_for_update",
                new=AsyncMock(),
            ),
            patch(
                "app.services.organization.knowledge_base_repo.list_org_scoped",
                new=AsyncMock(return_value=[]),
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
    @pytest.mark.parametrize("slot", [5, None])
    async def test_naming_the_colour_writes_exactly_what_was_named(self, service, mock_db, slot):
        """Including an explicit `null`, which is how the colour resets to auto."""
        membership = MagicMock(role="owner")
        org = MagicMock()

        with (
            patch.object(service, "get_for_user", new=AsyncMock(return_value=(org, membership))),
            patch(
                "app.services.organization.organization_repo.set_avatar_color",
                new=AsyncMock(return_value=org),
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate.model_validate({"avatar_color": slot}),
                requester_id=uuid.uuid4(),
            )

        assert write.await_args.kwargs["color"] == slot

    @pytest.mark.anyio
    async def test_an_update_that_does_not_name_the_colour_leaves_it_alone(self, service, mock_db):
        """A rename must not reset the colour to auto, so the write only fires when
        the client named the field - `null` is a value here, not an absence."""
        membership = MagicMock(role="owner")

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(MagicMock(), membership))
            ),
            patch(
                "app.services.organization.organization_repo.set_avatar_color", new=AsyncMock()
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(), OrganizationUpdate(name="Renamed"), requester_id=uuid.uuid4()
            )

        write.assert_not_awaited()

    @pytest.mark.anyio
    async def test_choosing_a_colour_is_metadata_and_needs_org_settings(self, service, mock_db):
        """A colour is org metadata, so a plain member cannot set it."""
        membership = MagicMock(role="member")

        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(MagicMock(), membership))
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate.model_validate({"avatar_color": 5}),
                requester_id=uuid.uuid4(),
            )

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


class TestOrganizationResponses:
    """What a route answers with: the row, the caller's role, the org's size.

    Two of the three come from queries rather than from the row, so a response
    that drops them is a response that still validates.
    """

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_db):
        return OrganizationService(mock_db)

    @pytest.mark.anyio
    async def test_a_single_organization_carries_the_callers_own_role(self, service):
        """Not the row's role - there is none - but the membership row's.

        A response naming the wrong role is a UI showing an Owner the controls
        of a Viewer, or the reverse.
        """
        org = _org_row(name="Vstorm")
        membership = MagicMock()
        membership.role = OrgRole.ADMIN.value

        with (
            patch(
                "app.services.organization.member_repo.get",
                new=AsyncMock(return_value=membership),
            ),
            patch(
                "app.services.organization.organization_repo.get_by_id",
                new=AsyncMock(return_value=org),
            ),
            patch(
                "app.services.organization.organization_repo.count_members",
                new=AsyncMock(return_value=7),
            ),
        ):
            read = await service.read_for_user(org.id, uuid.uuid4())

        assert read.name == "Vstorm"
        assert read.role == OrgRole.ADMIN.value
        assert read.member_count == 7

    @pytest.mark.anyio
    async def test_reading_an_organization_the_caller_is_not_in_is_refused(self, service):
        """`read_for_user` is the whole answer for the single-org routes, so the
        membership check has to be inside it rather than beside it."""
        with (
            patch("app.services.organization.member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.read_for_user(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.anyio
    async def test_the_listing_gives_each_organization_its_own_role_and_size(self, service):
        """Both are per-row, and both come from a separate query per row."""
        first, second = _org_row(name="Vstorm"), _org_row(name="Personal")
        rows = [
            {"org": first, "role": OrgRole.MEMBER.value, "member_count": 12},
            {"org": second, "role": OrgRole.OWNER.value, "member_count": 1},
        ]

        with patch.object(OrganizationService, "list_for_user", new=AsyncMock(return_value=rows)):
            listing = await service.list_readable_for_user(uuid.uuid4())

        assert listing.total == 2
        assert [item.name for item in listing.items] == ["Vstorm", "Personal"]
        assert [item.role for item in listing.items] == [OrgRole.MEMBER.value, OrgRole.OWNER.value]
        assert [item.member_count for item in listing.items] == [12, 1]

    @pytest.mark.anyio
    async def test_belonging_to_nothing_is_an_empty_listing_not_an_error(self, service):
        with patch.object(OrganizationService, "list_for_user", new=AsyncMock(return_value=[])):
            listing = await service.list_readable_for_user(uuid.uuid4())

        assert listing.items == []
        assert listing.total == 0


class TestUserServiceRegistrationWithOrg:
    """Tests that UserService.register creates a Personal Org."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        # No deployment settings row, which is "every default" and so `open`
        # sign-up. Left to answer with a bare mock the policy reads a truthy row
        # whose `allowed_email_domains` is also truthy, and refuses registration for
        # a rule nobody configured.
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
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


class TestTeardownWiring:
    """The delete route is the only place a vector store reaches org deletion."""

    @pytest.mark.anyio
    async def test_the_delete_route_wires_the_store_so_vector_tables_are_dropped(self):
        """A revert to the plain service would delete the org rows and orphan every
        `rag_<collection>` table with no test noticing - this is that test (#9)."""
        from app.api.deps import get_organization_teardown_service
        from app.api.routes.v1 import organizations as org_routes

        store = MagicMock()
        service = get_organization_teardown_service(db=MagicMock(), vector_store=store)
        assert service._vector_store is store

        annotation = org_routes.delete_organization.__annotations__["service"]
        wired = [
            meta.dependency
            for meta in getattr(annotation, "__metadata__", ())
            if hasattr(meta, "dependency")
        ]
        assert get_organization_teardown_service in wired
