"""Tests for OrganizationService."""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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
from app.schemas.organization import OrganizationCreate, OrganizationRead, OrganizationUpdate
from app.schemas.user import UserCreate
from app.services.deployment_settings import DeploymentSettingsService, NewAccountPlacement
from app.services.organization import OrganizationService, _org_read
from app.services.proactive import ProactiveService
from app.services.user import UserService

_SPEECH_KEY = uuid.uuid4()


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
        proactive_limit_usd=Decimal("1"),
        # Set explicitly: a column default is applied on flush, and this row was
        # never flushed - so an unset boolean reaches the response schema as None
        # and fails it, which is the honest failure rather than one to coerce away.
        chat_may_waive_approvals=False,
        proactive_enabled=False,
        proactive_days=[1, 2, 3, 4, 5],
        proactive_hour=5,
        proactive_timing="fixed",
        proactive_watches_enabled=True,
        proactive_watch_min_minutes=30,
        welcome_dm_enabled=False,
        dictation_max_seconds=300,
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

    @pytest.mark.security
    @pytest.mark.anyio
    @pytest.mark.parametrize("role", ["member", "builder", "operator", "viewer"])
    async def test_the_proactivity_limit_needs_the_budgets_manage_permission(
        self, service, mock_db, role
    ):
        """#2301: what background work may spend per person is a spending limit too."""
        with (
            patch.object(
                service,
                "get_for_user",
                new=AsyncMock(return_value=(MagicMock(), MagicMock(role=role))),
            ),
            patch(
                "app.services.organization.organization_repo.set_proactive_limit", new=AsyncMock()
            ) as write,
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(proactive_limit_usd=Decimal("2")),
                requester_id=uuid.uuid4(),
            )

        write.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_owner_sets_the_proactivity_limit_and_zero_switches_it_off(
        self, service, mock_db
    ):
        org = MagicMock()
        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(org, MagicMock(role="owner")))
            ),
            patch(
                "app.services.organization.organization_repo.set_proactive_limit",
                new=AsyncMock(return_value=org),
            ) as write,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(proactive_limit_usd=Decimal("0")),
                requester_id=uuid.uuid4(),
            )

        assert write.await_args.kwargs == {"limit_usd": Decimal("0")}

    def test_a_negative_proactivity_limit_is_refused(self):
        with pytest.raises(ValidationError):
            OrganizationUpdate(proactive_limit_usd=Decimal("-1"))

    @pytest.mark.parametrize(
        "fields",
        [
            {"proactive_days": []},
            {"proactive_days": [0]},
            {"proactive_days": [8]},
            {"proactive_hour": 24},
            {"proactive_timing": "whenever"},
            {"welcome_dm_text": "x" * 1001},
        ],
    )
    def test_a_schedule_or_greeting_that_cannot_be_kept_is_refused(self, fields):
        with pytest.raises(ValidationError):
            OrganizationUpdate.model_validate(fields)

    def test_the_days_are_kept_once_each_in_order(self):
        assert OrganizationUpdate(proactive_days=[5, 1, 5]).proactive_days == [1, 5]

    @staticmethod
    def _stored(**overrides):
        values = {
            "id": uuid.uuid4(),
            "proactive_enabled": False,
            "proactive_model_profile_id": None,
            "proactive_days": [1, 2, 3, 4, 5],
            "proactive_hour": 5,
            "proactive_timing": "fixed",
            "welcome_dm_enabled": False,
            "welcome_dm_text": None,
            "proactive_watches_enabled": False,
            "proactive_watch_min_minutes": 60,
        }
        values.update(overrides)
        return MagicMock(**values)

    async def _update(self, service, org, data, *, profile=None, role="owner"):
        with (
            patch.object(
                service, "get_for_user", new=AsyncMock(return_value=(org, MagicMock(role=role)))
            ),
            patch(
                "app.services.organization.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.organization.organization_repo.set_proactivity",
                new=AsyncMock(return_value=org),
            ) as proactivity,
            patch(
                "app.services.organization.organization_repo.set_welcome_dm",
                new=AsyncMock(return_value=org),
            ) as welcome,
            patch(
                "app.services.organization.organization_repo.set_watch_policy",
                new=AsyncMock(return_value=org),
            ) as watch_policy,
            patch("app.services.organization.organization_repo.update", new=AsyncMock()),
        ):
            await service.update(uuid.uuid4(), data, requester_id=uuid.uuid4())
        self.watch_policy = watch_policy
        return proactivity, welcome

    @pytest.mark.anyio
    async def test_watches_are_not_turned_on_without_a_model_either(self, service, mock_db):
        with pytest.raises(BadRequestError) as refused:
            await self._update(
                service, self._stored(), OrganizationUpdate(proactive_watches_enabled=True)
            )

        assert refused.value.details["fields"][0]["field"] == "proactive_model_profile_id"

    @pytest.mark.anyio
    async def test_watches_on_with_a_floor_and_the_look_untouched(self, service, mock_db):
        org = self._stored(proactive_model_profile_id=uuid.uuid4())
        proactivity, _ = await self._update(
            service,
            org,
            OrganizationUpdate(proactive_watches_enabled=True, proactive_watch_min_minutes=30),
        )

        assert proactivity.await_args.kwargs["enabled"] is False
        assert self.watch_policy.await_args.kwargs == {"enabled": True, "min_minutes": 30}

    @pytest.mark.anyio
    async def test_leaving_the_switch_out_keeps_it(self, service, mock_db):
        org = self._stored(proactive_watches_enabled=True, proactive_model_profile_id=uuid.uuid4())
        await self._update(service, org, OrganizationUpdate(proactive_watch_min_minutes=120))
        assert self.watch_policy.await_args.kwargs == {"enabled": True, "min_minutes": 120}

    @pytest.mark.anyio
    async def test_proactivity_is_not_turned_on_without_a_model_to_run_it_on(
        self, service, mock_db
    ):
        """Off by default and never on a model nobody chose: it spends money nobody
        asked for in the moment."""
        with pytest.raises(BadRequestError) as refused:
            await self._update(service, self._stored(), OrganizationUpdate(proactive_enabled=True))

        assert refused.value.details["fields"][0]["field"] == "proactive_model_profile_id"

    @pytest.mark.anyio
    async def test_the_model_it_runs_on_is_not_cleared_while_it_is_on(self, service, mock_db):
        org = self._stored(proactive_enabled=True, proactive_model_profile_id=uuid.uuid4())
        with pytest.raises(BadRequestError):
            await self._update(service, org, OrganizationUpdate(proactive_model_profile_id=None))

    @pytest.mark.anyio
    async def test_a_model_from_another_organization_is_refused(self, service, mock_db):
        with pytest.raises(BadRequestError) as refused:
            await self._update(
                service,
                self._stored(),
                OrganizationUpdate(proactive_enabled=True, proactive_model_profile_id=uuid.uuid4()),
                profile=None,
            )

        assert refused.value.details["fields"][0]["field"] == "proactive_model_profile_id"

    @pytest.mark.anyio
    async def test_turned_on_with_its_model_and_its_schedule_and_the_rest_kept(
        self, service, mock_db
    ):
        model = uuid.uuid4()
        proactivity, welcome = await self._update(
            service,
            self._stored(),
            OrganizationUpdate(
                proactive_enabled=True,
                proactive_model_profile_id=model,
                proactive_timing="before_work",
            ),
            profile=MagicMock(),
        )

        assert proactivity.await_args.kwargs == {
            "enabled": True,
            "model_profile_id": model,
            "days": [1, 2, 3, 4, 5],
            "hour": 5,
            "timing": "before_work",
        }
        welcome.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_new_hour_alone_keeps_it_as_it_was(self, service, mock_db):
        model = uuid.uuid4()
        org = self._stored(proactive_enabled=True, proactive_model_profile_id=model)
        proactivity, _ = await self._update(
            service, org, OrganizationUpdate(proactive_hour=7, proactive_days=[1])
        )

        assert proactivity.await_args.kwargs == {
            "enabled": True,
            "model_profile_id": model,
            "days": [1],
            "hour": 7,
            "timing": "fixed",
        }

    @pytest.mark.security
    @pytest.mark.anyio
    @pytest.mark.parametrize("role", ["member", "builder", "operator", "viewer"])
    async def test_turning_proactivity_on_needs_the_budgets_manage_permission(
        self, service, mock_db, role
    ):
        with pytest.raises(AuthorizationError):
            await self._update(
                service, self._stored(), OrganizationUpdate(proactive_enabled=True), role=role
            )

    @pytest.mark.anyio
    async def test_the_greeting_is_switched_and_worded_and_a_blank_one_is_the_built_in(
        self, service, mock_db
    ):
        _, welcome = await self._update(
            service,
            self._stored(),
            OrganizationUpdate(welcome_dm_enabled=True, welcome_dm_text="  Hi from {bot}  "),
        )
        assert welcome.await_args.kwargs == {"enabled": True, "text": "Hi from {bot}"}

        _, welcome = await self._update(
            service,
            self._stored(welcome_dm_enabled=True, welcome_dm_text="Old"),
            OrganizationUpdate(welcome_dm_text="   "),
        )
        assert welcome.await_args.kwargs == {"enabled": True, "text": None}

        _, welcome = await self._update(
            service,
            self._stored(welcome_dm_text="Kept"),
            OrganizationUpdate(welcome_dm_enabled=False),
        )
        assert welcome.await_args.kwargs == {"enabled": False, "text": "Kept"}

    @pytest.mark.security
    @pytest.mark.anyio
    async def test_the_greeting_needs_the_organization_settings_permission(self, service, mock_db):
        with pytest.raises(AuthorizationError):
            await self._update(
                service, self._stored(), OrganizationUpdate(welcome_dm_enabled=True), role="member"
            )

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

    @staticmethod
    def _speech_org(**fields: object) -> MagicMock:
        org = MagicMock()
        org.speech_to_text_provider = fields.get("provider")
        org.speech_to_text_model = fields.get("model")
        org.speech_to_text_secret_id = fields.get("secret_id")
        org.speech_to_text_language = fields.get("language")
        org.dictation_max_seconds = fields.get("max_seconds", 300)
        return org

    @pytest.fixture
    def key_check(self) -> Any:
        """The vault check on a named key, passing unless a test says otherwise."""
        with patch(
            "app.services.organization.SpeechToTextSettingsService.key_problem",
            new=AsyncMock(return_value=None),
        ) as checked:
            yield checked

    @staticmethod
    def _as_owner(org: MagicMock) -> AsyncMock:
        return AsyncMock(return_value=(org, MagicMock(role=OrgRole.OWNER.value)))

    @pytest.mark.anyio
    async def test_a_pair_the_catalog_does_not_offer_is_refused_on_the_model(self, service):
        with (
            patch.object(service, "get_for_user", new=self._as_owner(self._speech_org())),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_provider="openai", speech_to_text_model="nope"),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_model"

    @pytest.mark.anyio
    async def test_a_provider_without_a_model_is_refused(self, service):
        """Both or neither, as the column constraint says - refused here as a
        field rather than as a 500 from the database, and on the provider, the
        field the request sent."""
        with (
            patch.object(service, "get_for_user", new=self._as_owner(self._speech_org())),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_provider="openai"),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_provider"

    @pytest.mark.anyio
    async def test_clearing_the_pair_is_allowed(self, service):
        """Agents with their own pair keep dictating on it; the rest dictate in the browser."""
        org = self._speech_org(provider="openai", model="whisper-1")
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            patch(
                "app.services.organization.organization_repo.set_speech_settings",
                new=AsyncMock(return_value=org),
            ) as written,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_provider=None, speech_to_text_model=None),
                requester_id=uuid.uuid4(),
            )
        assert written.await_args.kwargs["model"] is None

    @pytest.mark.anyio
    async def test_an_unknown_language_is_refused(self, service):
        with (
            patch.object(service, "get_for_user", new=self._as_owner(self._speech_org())),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_language="xx"),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_language"

    @pytest.mark.anyio
    async def test_a_valid_setup_writes_all_five_settings(self, service, key_check):
        """The fields the request left out keep their stored values - here the
        language - and the ones it named replace them. The key is checked as
        the platform spends it: for everybody, so with no member's view."""
        org = self._speech_org(language="de")
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            patch(
                "app.services.organization.organization_repo.set_speech_settings",
                new=AsyncMock(return_value=org),
            ) as write,
            patch(
                "app.services.organization.organization_repo.update",
                new=AsyncMock(return_value=org),
            ),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(
                    speech_to_text_provider="openai",
                    speech_to_text_model="gpt-4o-transcribe",
                    speech_to_text_secret_id=_SPEECH_KEY,
                    dictation_max_seconds=120,
                ),
                requester_id=uuid.uuid4(),
            )
        assert write.await_args.kwargs == {
            "provider": "openai",
            "model": "gpt-4o-transcribe",
            "secret_id": _SPEECH_KEY,
            "language": "de",
            "max_seconds": 120,
        }
        assert key_check.await_args.args == (_SPEECH_KEY,)
        assert key_check.await_args.kwargs["provider"] == "openai"
        assert key_check.await_args.kwargs["ctx"] is None

    @pytest.mark.anyio
    async def test_a_pair_named_without_a_key_is_asked_for_one(self, service):
        with (
            patch.object(service, "get_for_user", new=self._as_owner(self._speech_org())),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(
                    speech_to_text_provider="openai", speech_to_text_model="whisper-1"
                ),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_model"
        assert "Choose a key" in raised.value.message

    @pytest.mark.anyio
    async def test_a_key_the_vault_check_refuses_is_refused_on_the_key(self, service, key_check):
        """A private key, another organization's, another kind or another
        provider's - whichever, the refusal marks the key field."""
        key_check.return_value = "'Mine' is not visible to the whole organization"
        org = self._speech_org(provider="openai", model="whisper-1", secret_id=_SPEECH_KEY)
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_secret_id=uuid.uuid4()),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0] == {
            "field": "speech_to_text_secret_id",
            "message": "'Mine' is not visible to the whole organization",
        }

    @pytest.mark.anyio
    async def test_a_new_provider_is_checked_against_the_key_it_would_keep(
        self, service, key_check
    ):
        """A key never carries over: the stored one is checked against the new
        provider, which refuses it for its purpose."""
        key_check.return_value = "'Team OpenAI' is a key for openai, and this transcribes on groq"
        org = self._speech_org(provider="openai", model="whisper-1", secret_id=_SPEECH_KEY)
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(
                    speech_to_text_provider="groq", speech_to_text_model="whisper-large-v3"
                ),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_model"
        assert key_check.await_args.kwargs["provider"] == "groq"

    @pytest.mark.anyio
    async def test_a_key_with_no_pair_is_refused(self, service):
        with (
            patch.object(service, "get_for_user", new=self._as_owner(self._speech_org())),
            pytest.raises(BadRequestError) as raised,
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(speech_to_text_secret_id=_SPEECH_KEY),
                requester_id=uuid.uuid4(),
            )
        assert raised.value.details["fields"][0]["field"] == "speech_to_text_secret_id"

    @pytest.mark.anyio
    async def test_clearing_the_pair_and_the_language_with_null_clears_them(self, service):
        """`null` on a named field clears it; on the length, which cannot be
        empty, it leaves the stored value alone."""
        org = self._speech_org(
            provider="openai",
            model="whisper-1",
            secret_id=_SPEECH_KEY,
            language="pl",
            max_seconds=60,
        )
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            patch(
                "app.services.organization.organization_repo.set_speech_settings",
                new=AsyncMock(return_value=org),
            ) as write,
            patch(
                "app.services.organization.organization_repo.update",
                new=AsyncMock(return_value=org),
            ),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate.model_validate(
                    {
                        "speech_to_text_provider": None,
                        "speech_to_text_model": None,
                        "speech_to_text_language": None,
                        "dictation_max_seconds": None,
                    }
                ),
                requester_id=uuid.uuid4(),
            )
        # The key goes with the pair it was chosen for.
        assert write.await_args.kwargs == {
            "provider": None,
            "model": None,
            "secret_id": None,
            "language": None,
            "max_seconds": 60,
        }

    @pytest.mark.anyio
    async def test_a_rename_does_not_revalidate_a_dictation_setup_that_went_stale(self, service):
        """A default whose model was withdrawn must not block renaming the
        organization: the speech fields are checked only when one is named."""
        org = self._speech_org(provider="openai", model="withdrawn-model")
        with (
            patch.object(service, "get_for_user", new=self._as_owner(org)),
            patch(
                "app.services.organization.organization_repo.set_speech_settings",
                new=AsyncMock(),
            ) as write,
            patch(
                "app.services.organization.organization_repo.update",
                new=AsyncMock(return_value=org),
            ) as rename,
        ):
            await service.update(
                uuid.uuid4(), OrganizationUpdate(name="Renamed"), requester_id=uuid.uuid4()
            )
        write.assert_not_awaited()
        assert rename.await_args.kwargs["name"] == "Renamed"

    @pytest.mark.anyio
    async def test_speech_settings_need_org_settings(self, service):
        member = AsyncMock(return_value=(self._speech_org(), MagicMock(role=OrgRole.MEMBER.value)))
        with (
            patch.object(service, "get_for_user", new=member),
            patch(
                "app.services.organization.organization_repo.set_speech_settings",
                new=AsyncMock(),
            ) as write,
            pytest.raises(AuthorizationError),
        ):
            await service.update(
                uuid.uuid4(),
                OrganizationUpdate(dictation_max_seconds=60),
                requester_id=uuid.uuid4(),
            )
        write.assert_not_awaited()


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
        db.scalar = AsyncMock(return_value=False)
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.anyio
    async def test_register_creates_personal_org(self, mock_db):
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        with (
            patch.object(UserService, "_queue_welcome", new=AsyncMock()),
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
            live: bool = True,
        ):
            stack = ExitStack()
            stack.enter_context(patch("app.services.organization.admits", return_value=live))
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
            self.welcomed = stack.enter_context(
                patch.object(ProactiveService, "queue_welcome", new=AsyncMock())
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
    async def test_joining_the_default_organization_queues_a_welcome_in_the_chat_apps(
        self, service, placed
    ):
        """#2301: queued with the membership, sent by the worker - never in this request."""
        company = uuid.uuid4()
        user = uuid.uuid4()
        stack, _personal, _joined = placed(_placement(personal=False, default=company))
        with stack:
            await service.settle_new_account(user, "ada@acme.com")

        self.welcomed.assert_awaited_once_with(company, user)

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
    async def test_an_invitation_that_can_no_longer_be_accepted_does_not_stand_in(
        self, service, placed
    ):
        """Expired, used up or revoked: deferring to it would leave the account in
        no organization at all."""
        company = uuid.uuid4()
        stack, _, joined = placed(
            _placement(personal=False, default=company),
            pending=MagicMock(organization_id=company),
            live=False,
        )
        with stack:
            await service.settle_new_account(uuid.uuid4(), "ada@acme.com")

        assert joined.await_args.kwargs["organization_id"] == company

    @pytest.mark.anyio
    @pytest.mark.security
    async def test_an_account_another_organization_vouched_for_is_not_joined(self, service, placed):
        """Admitted only by another organization's invitation or directory mapping:
        joining the default one would let that organization's managers add people
        to an organization they cannot manage."""
        stack, personal, joined = placed(_placement(default=uuid.uuid4()))
        with stack:
            await service.settle_new_account(uuid.uuid4(), "ada@acme.com", admitted_by_policy=False)

        personal.assert_awaited_once()
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


def test_every_setting_the_row_holds_reaches_the_response():
    """The response is built field by field, so a column added to both the row and
    the schema but not to the builder reads as its default forever - watches were
    switched on in the database and off in every console (#2301)."""
    row = _org_row(name="Acme")
    read = _org_read(row, member_count=1, role="owner", is_default=False)
    columns = set(Organization.__table__.columns.keys())
    shared = [name for name in OrganizationRead.model_fields if name in columns]

    assert shared
    assert {name: getattr(read, name) for name in shared} == {
        name: getattr(row, name) for name in shared
    }
