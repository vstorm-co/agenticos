"""Who this deployment lets create an account.

The invariant this file exists for is the one that ends a deployment if it is
wrong: **the first user is always admitted.** A fresh installation has no
accounts, so its administrator does not exist yet, and a closed deployment that
also refuses the person who would open it is a deployment nobody can enter with no
console to fix it from.

Two other refusals here were found by reading rather than by a failure, and both
are the kind that passes every happy-path test:

*Closing the sign-up form does not close OAuth.* `get_or_create_oauth_user` is a
second path that mints an account, and nothing about a Google callback looks like a
registration - so a deployment with `closed` and a Google button was wide open.

*Closing registration breaks invitations.* `InvitationService.accept` requires an
existing signed-in user, so an invited person has to register first. `invite_only`
is what keeps that flow working, and `any_pending_admitting` is what it asks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.db.models.organization import Invitation, InvitationStatus
from app.repositories import invitation as invitation_repo_module
from app.services import signup_policy as module
from app.services.signup_policy import check_may_register
from tests.test_deployment_settings import a_row

pytestmark = pytest.mark.anyio


@pytest.fixture
def repos(monkeypatch) -> MagicMock:
    """The settings row and the invitation lookup, both stubbed."""
    settings_repo = MagicMock()
    settings_repo.get = AsyncMock(return_value=None)
    invitations = MagicMock()
    invitations.any_pending_admitting = AsyncMock(return_value=False)
    monkeypatch.setattr(module, "deployment_settings_repo", settings_repo)
    monkeypatch.setattr(module, "invitation_repo", invitations)
    holder = MagicMock()
    holder.settings = settings_repo
    holder.invitations = invitations
    return holder


class TestTheBootstrapInvariant:
    async def test_the_first_account_is_admitted_however_closed_the_deployment_is(
        self, mock_db_session, repos
    ):
        """Otherwise a `closed` deployment restored from a backup of its settings and
        none of its users is unreachable - and `register` is what promotes that first
        account to `is_app_admin`, so there is no other way in."""
        repos.settings.get.return_value = a_row(signup_mode="closed")

        await check_may_register(mock_db_session, email="ops@acme.com", is_first_user=True)

    async def test_it_beats_the_domain_allow_list_too(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(allowed_email_domains=["acme.com"])

        await check_may_register(mock_db_session, email="founder@gmail.com", is_first_user=True)

    async def test_nothing_is_even_read_for_the_first_account(self, mock_db_session, repos):
        await check_may_register(mock_db_session, email="ops@acme.com", is_first_user=True)

        repos.settings.get.assert_not_called()


class TestAnUnconfiguredDeployment:
    async def test_it_registers_the_way_it_did_before_this_feature(self, mock_db_session, repos):
        """No row means every default, and the default is `open`. A feature that
        closed sign-up on deployments nobody configured would be a silent breaking
        change."""
        await check_may_register(mock_db_session, email="anyone@example.com", is_first_user=False)


class TestOpen:
    async def test_anybody_may_register(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(signup_mode="open")

        await check_may_register(mock_db_session, email="anyone@example.com", is_first_user=False)

    async def test_no_invitation_is_looked_up(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(signup_mode="open")

        await check_may_register(mock_db_session, email="anyone@example.com", is_first_user=False)

        repos.invitations.any_pending_admitting.assert_not_called()


class TestClosed:
    async def test_nobody_registers(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(signup_mode="closed")

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session, email="anyone@example.com", is_first_user=False
            )

    async def test_an_invitation_does_not_reopen_it(self, mock_db_session, repos):
        """ "Closed" that lets some registrations through is not closed. An operator who
        wants invitations honoured sets `invite_only`, which is the mode for it."""
        repos.settings.get.return_value = a_row(signup_mode="closed")
        repos.invitations.any_pending_admitting.return_value = True

        with pytest.raises(AuthorizationError):
            await check_may_register(mock_db_session, email="invited@acme.com", is_first_user=False)

    async def test_the_refusal_says_what_to_do_instead(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(signup_mode="closed")

        with pytest.raises(AuthorizationError) as caught:
            await check_may_register(mock_db_session, email="a@b.com", is_first_user=False)

        assert "administrator" in str(caught.value.message)


class TestInviteOnly:
    async def test_an_invited_address_registers(self, mock_db_session, repos):
        """The whole reason this mode exists: an invited person has no account, and
        `InvitationService.accept` requires one."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.any_pending_admitting.return_value = True

        await check_may_register(mock_db_session, email="invited@acme.com", is_first_user=False)

    async def test_an_uninvited_address_is_refused(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(signup_mode="invite_only")

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session, email="stranger@example.com", is_first_user=False
            )

    async def test_the_refusal_names_no_organization(self, mock_db_session, repos):
        """The sign-up form is public, and "you were not invited" must not become a
        way to enumerate this deployment's tenants."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")

        with pytest.raises(AuthorizationError) as caught:
            await check_may_register(mock_db_session, email="s@x.com", is_first_user=False)

        assert caught.value.details in (None, {})


class TestTheDomainAllowList:
    async def test_an_empty_list_allows_every_domain(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(allowed_email_domains=[])

        await check_may_register(mock_db_session, email="anyone@example.com", is_first_user=False)

    async def test_an_address_at_an_allowed_domain_registers(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(allowed_email_domains=["acme.com", "partner.io"])

        await check_may_register(mock_db_session, email="me@partner.io", is_first_user=False)

    async def test_an_address_anywhere_else_is_refused(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(allowed_email_domains=["acme.com"])

        with pytest.raises(AuthorizationError):
            await check_may_register(mock_db_session, email="me@gmail.com", is_first_user=False)

    async def test_the_refusal_says_which_domains_are_allowed(self, mock_db_session, repos):
        """A form that refuses an address without ever saying which addresses it wants
        is a form that lies. The domains are not a secret either - the deployment is
        on the company's own host."""
        repos.settings.get.return_value = a_row(allowed_email_domains=["partner.io", "acme.com"])

        with pytest.raises(AuthorizationError) as caught:
            await check_may_register(mock_db_session, email="me@gmail.com", is_first_user=False)

        assert caught.value.details == {"allowed_domains": ["acme.com", "partner.io"]}

    async def test_the_comparison_ignores_case_and_surrounding_space(self, mock_db_session, repos):
        repos.settings.get.return_value = a_row(allowed_email_domains=["acme.com"])

        await check_may_register(mock_db_session, email="  Me@ACME.com ", is_first_user=False)

    async def test_a_subdomain_is_not_the_domain(self, mock_db_session, repos):
        """`acme.com` in the list admits `@acme.com` and not `@evil.acme.com.attacker.net`
        - which is exactly what an `endswith` would have let through."""
        repos.settings.get.return_value = a_row(allowed_email_domains=["acme.com"])

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session, email="me@evil.acme.com.attacker.net", is_first_user=False
            )

    async def test_an_invitation_overrides_it(self, mock_db_session, repos):
        """Somebody holding `members:invite` named that address on purpose. A domain
        list is deployment policy for strangers rather than a veto over a deliberate
        act."""
        repos.settings.get.return_value = a_row(
            signup_mode="invite_only", allowed_email_domains=["acme.com"]
        )
        repos.invitations.any_pending_admitting.return_value = True

        await check_may_register(mock_db_session, email="contractor@gmail.com", is_first_user=False)

    async def test_it_still_narrows_an_open_deployment(self, mock_db_session, repos):
        """`open` plus a domain list is the ordinary shape: anybody at the company, and
        nobody else. No invitation is looked up, so nothing overrides the list."""
        repos.settings.get.return_value = a_row(
            signup_mode="open", allowed_email_domains=["acme.com"]
        )

        with pytest.raises(AuthorizationError):
            await check_may_register(mock_db_session, email="me@gmail.com", is_first_user=False)


class TestWhichInvitationsAdmit:
    """`invitation_repo.any_pending_admitting`, at the query level.

    Cross-tenant by construction - registration happens before an organization is
    chosen, so there is no tenant to scope to - and what keeps that safe is the
    answer being a boolean rather than a row.
    """

    @staticmethod
    async def _predicate(email: str) -> str:
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        await invitation_repo_module.any_pending_admitting(db, email=email)
        return str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))

    async def test_it_asks_only_about_live_invitations(self):
        sql = await self._predicate("me@acme.com")

        assert InvitationStatus.PENDING.value in sql
        assert "expires_at" in sql

    async def test_it_matches_the_address_and_its_domain(self):
        sql = await self._predicate("Me@Acme.COM")

        assert "me@acme.com" in sql
        assert "'acme.com'" in sql

    async def test_a_link_with_no_domain_does_not_admit(self):
        """It admits anyone holding it once they have an account, but the register
        request carries no token - so honouring it would turn one open link anywhere
        in the deployment back into `open` for the whole internet."""
        sql = await self._predicate("me@acme.com")

        assert "email_domain IS NULL" not in sql
        assert "invitations.email_domain = 'acme.com'" in sql

    async def test_a_spent_link_does_not_admit(self):
        sql = await self._predicate("me@acme.com")

        assert "used_count" in sql
        assert "max_uses" in sql

    async def test_it_answers_a_boolean_and_never_the_row(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=(uuid4(),))))

        answer = await invitation_repo_module.any_pending_admitting(db, email="me@acme.com")

        assert answer is True
        assert str(db.execute.await_args.args[0]).strip().startswith("SELECT invitations.id")

    async def test_no_match_answers_false(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))

        assert await invitation_repo_module.any_pending_admitting(db, email="me@acme.com") is False

    def test_the_model_it_queries_still_has_the_columns_it_names(self):
        """The query is written against `Invitation`, so a rename there would be
        caught by the type checker - but a *removed* nullable column would not, and
        the shape of the rule depends on both existing."""
        columns = Invitation.__table__.columns
        assert {"email", "email_domain", "max_uses", "used_count", "expires_at"} <= set(
            columns.keys()
        )


class TestBothPathsThatMintAnAccountAreGated:
    """The policy is worth nothing if a path around it exists, and one did.

    `register` is the obvious one. `get_or_create_oauth_user` is the one found by
    reading: a deployment with `closed` and a Google button was wide open, because
    nothing about an OAuth callback looks like a registration.
    """

    @staticmethod
    def _service(monkeypatch, refuse: bool):
        from unittest.mock import patch

        from app.services.user import UserService

        checked: list[dict] = []

        async def _check(_db, **kwargs):
            checked.append(kwargs)
            if refuse:
                raise AuthorizationError(message="closed")

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=3)))
        monkeypatch.setattr("app.services.user.check_may_register", _check)
        return UserService(db), checked, patch

    async def test_registering_asks_the_policy_first(self, monkeypatch):
        from app.schemas.user import UserCreate

        service, checked, patch = self._service(monkeypatch, refuse=False)
        with (
            patch("app.services.user.user_repo") as repo,
            patch("app.services.user.OrganizationService") as orgs,
            patch("app.services.user.get_email_service"),
            patch("app.services.user.DeploymentSettingsService"),
        ):
            repo.get_by_email = AsyncMock(return_value=None)
            repo.create = AsyncMock(return_value=MagicMock(id=uuid4(), email="new@acme.com"))
            orgs.return_value.create_personal_org = AsyncMock()

            await service.register(UserCreate(email="new@acme.com", password="password123"))

        assert checked == [{"email": "new@acme.com", "is_first_user": False}]

    async def test_a_refused_registration_creates_no_account(self, monkeypatch):
        from app.schemas.user import UserCreate

        service, _checked, patch = self._service(monkeypatch, refuse=True)
        with patch("app.services.user.user_repo") as repo:
            repo.get_by_email = AsyncMock(return_value=None)
            repo.create = AsyncMock()

            with pytest.raises(AuthorizationError):
                await service.register(UserCreate(email="new@acme.com", password="password123"))

            repo.create.assert_not_called()

    async def test_an_address_that_already_has_an_account_is_told_so_first(self, monkeypatch):
        """A closed deployment is not a way to find out who is registered - so the
        duplicate-address refusal comes before the policy, not after it."""
        from app.schemas.user import UserCreate

        service, checked, patch = self._service(monkeypatch, refuse=True)
        with patch("app.services.user.user_repo") as repo:
            repo.get_by_email = AsyncMock(return_value=MagicMock())

            with pytest.raises(Exception) as caught:
                await service.register(UserCreate(email="taken@acme.com", password="password123"))

        assert "already registered" in str(caught.value.message).lower()
        assert checked == []

    async def test_signing_in_with_oauth_asks_the_policy_too(self, monkeypatch):
        service, checked, patch = self._service(monkeypatch, refuse=False)
        with (
            patch("app.services.user.user_repo") as repo,
            patch("app.services.user.OrganizationService") as orgs,
            patch("app.services.user.get_email_service"),
            patch("app.services.user.DeploymentSettingsService"),
        ):
            repo.get_by_oauth = AsyncMock(return_value=None)
            repo.get_by_email = AsyncMock(return_value=None)
            repo.create = AsyncMock(return_value=MagicMock(id=uuid4(), email="new@acme.com"))
            orgs.return_value.create_personal_org = AsyncMock()

            await service.get_or_create_oauth_user(
                provider="google", provider_id="g1", email="new@acme.com"
            )

        assert checked == [{"email": "new@acme.com", "is_first_user": False}]

    async def test_a_closed_deployment_refuses_a_new_oauth_account(self, monkeypatch):
        service, _checked, patch = self._service(monkeypatch, refuse=True)
        with patch("app.services.user.user_repo") as repo:
            repo.get_by_oauth = AsyncMock(return_value=None)
            repo.get_by_email = AsyncMock(return_value=None)
            repo.create = AsyncMock()

            with pytest.raises(AuthorizationError):
                await service.get_or_create_oauth_user(
                    provider="google", provider_id="g1", email="new@acme.com"
                )

            repo.create.assert_not_called()

    async def test_an_existing_user_signing_in_with_oauth_is_not_re_gated(self, monkeypatch):
        """Closing registration closes registration. Somebody who already has an
        account signing in is not registering, and locking them out of a deployment
        they are a member of is not what the setting says."""
        service, checked, patch = self._service(monkeypatch, refuse=True)
        with patch("app.services.user.user_repo") as repo:
            repo.get_by_oauth = AsyncMock(return_value=MagicMock(email="old@acme.com"))

            await service.get_or_create_oauth_user(
                provider="google", provider_id="g1", email="old@acme.com"
            )

        assert checked == []

    async def test_an_oauth_identity_attached_to_an_existing_address_is_not_re_gated(
        self, monkeypatch
    ):
        service, checked, patch = self._service(monkeypatch, refuse=True)
        with patch("app.services.user.user_repo") as repo:
            repo.get_by_oauth = AsyncMock(return_value=None)
            repo.get_by_email = AsyncMock(return_value=MagicMock(email="old@acme.com"))
            repo.update = AsyncMock()

            await service.get_or_create_oauth_user(
                provider="google", provider_id="g1", email="old@acme.com"
            )

        assert checked == []
