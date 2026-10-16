"""Tests for OrganizationService."""

import uuid
from contextlib import ExitStack
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
from app.services.deployment_settings import DeploymentSettingsService, NewAccountPlacement
from app.services.organization import OrganizationService
from app.services.user import UserService


def _placement(
    *, personal: bool = True, default: uuid.UUID | None = None, role: str = "member"
) -> NewAccountPlacement:
    return NewAccountPlacement(personal=personal, default_organization_id=default, role=role)


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
        # Set explicitly: a column default is applied on flush, and this row was
        # never flushed - so an unset boolean reaches the response schema as None
        # and fails it, which is the honest failure rather than one to coerce away.
        chat_may_waive_approvals=False,
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

    @pytest.mark.security
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

    @pytest.fixture(autouse=True)
    def default_organization(self):
        """No default organization unless a test sets one."""
        with patch.object(
            DeploymentSettingsService,
            "new_account_placement",
            new=AsyncMock(return_value=_placement()),
        ) as placement:
            yield placement

    @pytest.mark.anyio
    async def test_the_listing_marks_the_deployments_default_organization(
        self, service, default_organization
    ):
        """The console selects it when nothing else is selected (#2156)."""
        company, personal = _org_row(name="Acme"), _org_row(name="Personal")
        default_organization.return_value = _placement(default=company.id)
        rows = [
            {"org": personal, "role": OrgRole.OWNER.value, "member_count": 1},
            {"org": company, "role": OrgRole.MEMBER.value, "member_count": 40},
        ]

        with patch.object(OrganizationService, "list_for_user", new=AsyncMock(return_value=rows)):
            listing = await service.list_readable_for_user(uuid.uuid4())

        assert [item.is_default for item in listing.items] == [False, True]

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

    @pytest.mark.anyio
    async def test_the_listing_takes_the_role_and_the_count_in_grouped_queries(self, service):
        """#953: the role rides the membership join the listing already makes,
        and the sizes come back keyed by organization - so neither is a query
        per row. The old per-organization `member_repo.get` and `count_members`
        are gone."""
        first, second = _org_row(name="Vstorm"), _org_row(name="Personal")
        with (
            patch(
                "app.services.organization.organization_repo.list_for_user",
                new=AsyncMock(
                    return_value=[
                        (first, OrgRole.MEMBER.value),
                        (second, OrgRole.OWNER.value),
                    ]
                ),
            ),
            patch(
                "app.services.organization.organization_repo.member_counts_for",
                new=AsyncMock(return_value={first.id: 12, second.id: 1}),
            ) as counts,
            patch("app.services.organization.member_repo.get", new=AsyncMock()) as member_get,
            patch(
                "app.services.organization.organization_repo.count_members", new=AsyncMock()
            ) as count_members,
        ):
            rows = await service.list_for_user(uuid.uuid4())

        assert [row["role"] for row in rows] == [OrgRole.MEMBER.value, OrgRole.OWNER.value]
        assert [row["member_count"] for row in rows] == [12, 1]
        counts.assert_awaited_once()
        member_get.assert_not_awaited()
        count_members.assert_not_awaited()


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


class TestWhereANewAccountStarts:
    """Personal organizations on or off, and a default organization (#2156)."""

    @pytest.fixture
    def service(self):
        return OrganizationService(MagicMock())

    @pytest.fixture
    def placed(self):
        """Patch the reads `settle_new_account` makes; yields the two writes."""

        def place(
            placement: NewAccountPlacement,
            *,
            invitation: MagicMock | None = None,
            pending: MagicMock | None = None,
        ):
            stack = ExitStack()
            stack.enter_context(
                patch.object(
                    DeploymentSettingsService,
                    "new_account_placement",
                    new=AsyncMock(return_value=placement),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.organization.invitation_repo.get_by_token",
                    new=AsyncMock(return_value=invitation),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.organization.invitation_repo.get_pending_for_org_email",
                    new=AsyncMock(return_value=pending),
                )
            )
            personal = stack.enter_context(
                patch.object(OrganizationService, "create_personal_org", new=AsyncMock())
            )
            joined = stack.enter_context(
                patch("app.services.organization.member_repo.create", new=AsyncMock())
            )
            return stack, personal, joined

        return place

    @pytest.mark.anyio
    async def test_an_unconfigured_deployment_gives_an_organization_of_ones_own(
        self, service, placed
    ):
        stack, personal, joined = placed(_placement())
        with stack:
            await service.settle_new_account(uuid.uuid4(), "ada@acme.com")

        personal.assert_awaited_once()
        joined.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_company_deployment_joins_the_default_organization_only(self, service, placed):
        company = uuid.uuid4()
        user = uuid.uuid4()
        stack, personal, joined = placed(_placement(personal=False, default=company, role="viewer"))
        with stack:
            await service.settle_new_account(user, "ada@acme.com")

        personal.assert_not_awaited()
        assert joined.await_args.kwargs == {
            "organization_id": company,
            "user_id": user,
            "role": "viewer",
        }

    @pytest.mark.anyio
    async def test_personal_organizations_off_and_no_default_joins_nothing(self, service, placed):
        stack, personal, joined = placed(_placement(personal=False))
        with stack:
            await service.settle_new_account(uuid.uuid4(), "ada@acme.com")

        personal.assert_not_awaited()
        joined.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("by", ["token", "email"])
    async def test_an_invitation_to_the_default_organization_joins_it_instead(
        self, service, placed, by
    ):
        """The invitation names its own role, and accepting into an organization the
        person already joined is refused - so the default stands aside for it."""
        company = uuid.uuid4()
        invitation = MagicMock(organization_id=company)
        stack, _, joined = placed(
            _placement(default=company),
            invitation=invitation if by == "token" else None,
            pending=invitation if by == "email" else None,
        )
        with stack:
            await service.settle_new_account(
                uuid.uuid4(), "ada@acme.com", invitation_token="tok" if by == "token" else None
            )

        joined.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_invitation_elsewhere_still_joins_the_default(self, service, placed):
        company = uuid.uuid4()
        stack, _, joined = placed(
            _placement(default=company), invitation=MagicMock(organization_id=uuid.uuid4())
        )
        with stack:
            await service.settle_new_account(uuid.uuid4(), "ada@acme.com", invitation_token="tok")

        assert joined.await_args.kwargs["organization_id"] == company


@pytest.mark.security
class TestWhereARequestNamingNoOrganizationLands:
    """A session without `X-Organization-Id` acts somewhere; this is where (#2156)."""

    @pytest.fixture
    def service(self):
        return OrganizationService(MagicMock())

    def _patches(self, *, default=None, member_of_default=False, personal=None, memberships=()):
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                DeploymentSettingsService,
                "new_account_placement",
                new=AsyncMock(return_value=_placement(default=default.id if default else None)),
            )
        )
        stack.enter_context(
            patch(
                "app.services.organization.member_repo.get",
                new=AsyncMock(return_value=MagicMock() if member_of_default else None),
            )
        )
        stack.enter_context(
            patch(
                "app.services.organization.organization_repo.get_by_id",
                new=AsyncMock(return_value=default),
            )
        )
        stack.enter_context(
            patch(
                "app.services.organization.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=personal),
            )
        )
        stack.enter_context(
            patch(
                "app.services.organization.organization_repo.list_for_user",
                new=AsyncMock(return_value=[(org, "member") for org in memberships]),
            )
        )
        return stack

    @pytest.mark.anyio
    async def test_the_default_organization_comes_before_a_personal_one(self, service):
        company, personal = _org_row(name="Acme"), _org_row(name="Personal")
        with self._patches(default=company, member_of_default=True, personal=personal):
            assert await service.fallback_for(uuid.uuid4()) is company

    @pytest.mark.anyio
    async def test_a_default_the_person_is_not_in_is_passed_over(self, service):
        company, personal = _org_row(name="Acme"), _org_row(name="Personal")
        with self._patches(default=company, personal=personal):
            assert await service.fallback_for(uuid.uuid4()) is personal

    @pytest.mark.anyio
    async def test_with_no_personal_organization_the_only_one_is_used(self, service):
        only = _org_row(name="Acme")
        with self._patches(memberships=[only]):
            assert await service.fallback_for(uuid.uuid4()) is only

    @pytest.mark.anyio
    async def test_a_choice_is_never_guessed(self, service):
        """Two organizations, neither default nor personal: a script that forgot the
        header must not quietly act in one of them."""
        with self._patches(memberships=[_org_row(name="A"), _org_row(name="B")]):
            assert await service.fallback_for(uuid.uuid4()) is None
