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
registration - so a deployment with `closed` and a Google button was wide open. The
gate cuts both ways: an invitation has to reach that path too, or `invite_only`
refuses the provider button for the very links that need a token (#914), which is
why the route carries one through the round trip in the session.

*Closing registration breaks invitations.* `InvitationService.accept` requires an
existing signed-in user, so an invited person has to register first. `invite_only`
is what keeps that flow working, and it has two ways to recognise an invitation: a
**token** the registration carries, which is the only proof that can admit a
shareable link constraining no address, and otherwise `first_pending_admitting` over
the submitted address (#916).

*And a capped link bounded joins rather than accounts.* `used_count` counts
acceptances, acceptance needs a session, and registration does not - so one
`max_uses=1` link admitted as many registrations as anybody cared to make on an
`invite_only` deployment. A use is **reserved** for the address before the account
is created, atomically, which is what makes the ceiling mean both (#914).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def a_link(**overrides) -> Invitation:
    """A live shareable link, as the lookup answers with one."""
    invite = Invitation(
        id=uuid4(),
        organization_id=uuid4(),
        email=None,
        role="member",
        max_uses=1,
        used_count=0,
        reserved_emails=[],
        email_domain=None,
        invited_by_user_id=uuid4(),
        token=uuid4().hex,
        status=InvitationStatus.PENDING.value,
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    for field, value in overrides.items():
        setattr(invite, field, value)
    return invite


@pytest.fixture
def repos(monkeypatch) -> MagicMock:
    """The settings row and both invitation lookups, stubbed."""
    settings_repo = MagicMock()
    settings_repo.get = AsyncMock(return_value=None)
    invitations = MagicMock()
    invitations.first_pending_admitting = AsyncMock(return_value=None)
    invitations.get_by_token = AsyncMock(return_value=None)
    # A link with a ceiling has a use held before the account is created, and the
    # policy admits nobody the reservation refuses. Its own atomicity is
    # `TestReservingAUse` below; here it is a yes or a no.
    invitations.reserve_use = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "deployment_settings_repo", settings_repo)
    monkeypatch.setattr(module, "invitation_repo", invitations)
    holder = MagicMock()
    holder.settings = settings_repo
    holder.invitations = invitations
    return holder


@pytest.fixture
def admits(monkeypatch) -> MagicMock:
    """`invitation_admission.admits`, as the policy sees it. Its own rules are
    `tests/test_invitation_admission.py`; here it is a yes or a no."""
    stub = MagicMock(return_value=True)
    monkeypatch.setattr(module, "admits", stub)
    return stub


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

        repos.invitations.first_pending_admitting.assert_not_called()


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
        repos.invitations.first_pending_admitting.return_value = a_link()

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
        repos.invitations.first_pending_admitting.return_value = a_link()

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
        repos.invitations.first_pending_admitting.return_value = a_link()

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
    """`invitation_repo.first_pending_admitting`, at the query level.

    Cross-tenant by construction - registration happens before an organization is
    chosen, so there is no tenant to scope to - and what keeps that safe is where
    the answer goes: the policy turns it into a boolean refusal, so a stranger
    probing the form never learns which organization invited the address.
    """

    @staticmethod
    async def _predicate(email: str) -> str:
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        await invitation_repo_module.first_pending_admitting(db, email=email)
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
        """Spent counts the reservations as well as the acceptances: a link admitting
        registrations it has no capacity left for is the whole defect."""
        sql = await self._predicate("me@acme.com")

        assert "used_count" in sql
        assert "max_uses" in sql
        assert "jsonb_array_length" in sql

    async def test_an_address_already_holding_a_reservation_still_matches(self):
        """Idempotent, so a registration retried after a network error is not refused
        by the reservation its first attempt made."""
        sql = await self._predicate("me@acme.com")

        assert "reserved_emails" in sql

    async def test_it_answers_the_row_it_found(self):
        found = a_link()
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=found))
        )

        answer = await invitation_repo_module.first_pending_admitting(db, email="me@acme.com")

        assert answer is found

    async def test_no_match_answers_nothing(self):
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        assert await invitation_repo_module.first_pending_admitting(db, email="me@acme.com") is None

    def test_the_model_it_queries_still_has_the_columns_it_names(self):
        """The query is written against `Invitation`, so a rename there would be
        caught by the type checker - but a *removed* nullable column would not, and
        the shape of the rule depends on both existing."""
        columns = Invitation.__table__.columns
        assert {
            "email",
            "email_domain",
            "max_uses",
            "used_count",
            "reserved_emails",
            "expires_at",
        } <= set(columns.keys())


class TestReservingAUse:
    """A capped link has to bound accounts, not only joins.

    `used_count` counts acceptances and acceptance needs a session, so a
    `max_uses=1` link admitted an unbounded number of registrations on an
    `invite_only` deployment - each one reading a count nothing had yet moved. One
    link posted in a channel, and closing sign-up was closed to nobody.

    The atomicity is the point and is proven against a real database in
    `tests/integration/test_invitation_reservations.py`; what is here is which
    invitations get a reservation at all, and what the policy does with the answer.
    """

    async def test_a_capped_link_has_a_use_held_before_the_account_exists(
        self, mock_db_session, repos
    ):
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.first_pending_admitting.return_value = a_link(max_uses=1)

        await check_may_register(mock_db_session, email="Me@Acme.com", is_first_user=False)

        assert repos.invitations.reserve_use.await_args.kwargs["email"] == "Me@Acme.com"

    async def test_a_link_with_no_use_left_refuses_the_registration(self, mock_db_session, repos):
        """The reservation is the second, atomic reading of the same condition the
        lookup checked - and the one that survives a race, because the lookup read a
        row this session had already loaded."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.first_pending_admitting.return_value = a_link(max_uses=1)
        repos.invitations.reserve_use.return_value = False

        with pytest.raises(AuthorizationError):
            await check_may_register(mock_db_session, email="second@acme.com", is_first_user=False)

    async def test_an_uncapped_link_reserves_nothing(self, mock_db_session, repos):
        """It bounds nothing, so there is nothing to hold and nothing that can fail."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.first_pending_admitting.return_value = a_link(max_uses=None)

        await check_may_register(mock_db_session, email="me@acme.com", is_first_user=False)

        repos.invitations.reserve_use.assert_not_called()

    async def test_an_email_invitation_reserves_nothing(self, mock_db_session, repos):
        """An address is its own limit of one, and `register` refuses an address that
        already has an account."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.first_pending_admitting.return_value = a_link(
            email="me@acme.com", max_uses=None
        )

        await check_may_register(mock_db_session, email="me@acme.com", is_first_user=False)

        repos.invitations.reserve_use.assert_not_called()

    async def test_a_token_carried_by_the_registration_reserves_too(
        self, mock_db_session, repos, admits
    ):
        """Possession admits a link no address-based query can see, and that is
        exactly the link whose capacity nothing else was counting."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link(max_uses=2)

        await check_may_register(
            mock_db_session,
            email="stranger@example.com",
            is_first_user=False,
            invitation_token="tok",
        )

        repos.invitations.reserve_use.assert_awaited_once()

    async def test_a_token_whose_link_is_spent_is_refused_rather_than_admitted(
        self, mock_db_session, repos, admits
    ):
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link(max_uses=1)
        repos.invitations.reserve_use.return_value = False

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session,
                email="stranger@example.com",
                is_first_user=False,
                invitation_token="tok",
            )

    async def test_a_token_that_lost_the_last_use_still_asks_about_the_address(
        self, mock_db_session, repos, admits
    ):
        """A token whose link lost the race may belong to somebody who was also
        invited by name. Refusing there would be an error about something they
        cannot fix - the same reason a stale token falls through."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link(max_uses=1)
        repos.invitations.first_pending_admitting.return_value = a_link(
            email="me@acme.com", max_uses=None
        )
        repos.invitations.reserve_use.return_value = False

        await check_may_register(
            mock_db_session, email="me@acme.com", is_first_user=False, invitation_token="tok"
        )

        repos.invitations.first_pending_admitting.assert_awaited_once()

    async def test_the_domain_allow_list_is_not_overridden_by_a_refused_reservation(
        self, mock_db_session, repos
    ):
        """The invitation is what overrides the list, and a link with nothing left is
        not an invitation for this person."""
        repos.settings.get.return_value = a_row(
            signup_mode="open", allowed_email_domains=["acme.com"]
        )
        repos.invitations.first_pending_admitting.return_value = a_link(max_uses=1)
        repos.invitations.reserve_use.return_value = False

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session, email="contractor@gmail.com", is_first_user=False
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

        assert checked == [
            {"email": "new@acme.com", "is_first_user": False, "invitation_token": None}
        ]

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

        assert checked == [
            {"email": "new@acme.com", "is_first_user": False, "invitation_token": None}
        ]

    async def test_an_invitation_survives_the_provider_round_trip(self, monkeypatch):
        """The gap #914 found. A shareable link constraining neither an address nor a
        domain is invisible to the address-based fallback, so `invite_only` refused
        the Google button for exactly the invitations that need a token - the same
        person could register with a password and not with the provider beside it.
        The route carries it in the session; this is the half that reads it."""
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
                provider="google",
                provider_id="g1",
                email="new@acme.com",
                invitation_token="tok",
            )

        assert checked == [
            {"email": "new@acme.com", "is_first_user": False, "invitation_token": "tok"}
        ]

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


class TestATokenTheRegistrationCarries:
    """The half `first_pending_admitting` cannot answer.

    A shareable link with neither an address nor a domain admits anybody holding it,
    and no query over the submitted address can see that. Holding the token is the
    proof, which is why it is the only thing that unlocks this case - and why a
    stranger who has one is not a stranger.
    """

    async def test_it_admits_an_address_no_invitation_names(self, mock_db_session, repos, admits):
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link()

        await check_may_register(
            mock_db_session,
            email="stranger@example.com",
            is_first_user=False,
            invitation_token="tok",
        )

        repos.invitations.get_by_token.assert_awaited_once_with(mock_db_session, "tok")

    async def test_a_token_naming_no_invitation_falls_back_rather_than_refusing(
        self, mock_db_session, repos, admits
    ):
        """A stale link in a bookmark must not turn a registration that would
        otherwise be allowed into an error about something the person cannot fix."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = None
        repos.invitations.first_pending_admitting.return_value = a_link()

        await check_may_register(
            mock_db_session, email="invited@acme.com", is_first_user=False, invitation_token="gone"
        )

        repos.invitations.first_pending_admitting.assert_awaited_once()

    async def test_a_token_for_an_invitation_that_does_not_admit_them_falls_back_too(
        self, mock_db_session, repos, admits
    ):
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link()
        admits.return_value = False

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session,
                email="stranger@example.com",
                is_first_user=False,
                invitation_token="tok",
            )

    async def test_it_overrides_the_domain_allow_list(self, mock_db_session, repos, admits):
        """Somebody holding `members:invite` named this person on purpose, and a
        domain list is deployment policy for strangers."""
        repos.settings.get.return_value = a_row(
            signup_mode="open", allowed_email_domains=["acme.com"]
        )
        repos.invitations.get_by_token.return_value = a_link()

        await check_may_register(
            mock_db_session,
            email="contractor@gmail.com",
            is_first_user=False,
            invitation_token="tok",
        )

    async def test_it_does_not_reopen_a_closed_deployment(self, mock_db_session, repos, admits):
        """ "Closed" that lets some registrations through is not closed - and an
        operator who wants invitations honoured has `invite_only` for it."""
        repos.settings.get.return_value = a_row(signup_mode="closed")
        repos.invitations.get_by_token.return_value = a_link()

        with pytest.raises(AuthorizationError):
            await check_may_register(
                mock_db_session,
                email="invited@acme.com",
                is_first_user=False,
                invitation_token="tok",
            )

    async def test_an_open_deployment_never_looks_a_token_up(self, mock_db_session, repos, admits):
        """The token grants nothing where nothing is being refused, so the query only
        runs where the answer changes the outcome."""
        repos.settings.get.return_value = a_row(signup_mode="open")

        await check_may_register(
            mock_db_session, email="anyone@example.com", is_first_user=False, invitation_token="tok"
        )

        repos.invitations.get_by_token.assert_not_called()

    async def test_registering_with_a_token_does_not_join_the_organization(
        self, mock_db_session, repos, admits
    ):
        """It admits the account and nothing else. Joining is
        `InvitationService.accept`, which the client calls once it has a session -
        otherwise a token in a sign-up body would be a membership grant on an
        unauthenticated route."""
        repos.settings.get.return_value = a_row(signup_mode="invite_only")
        repos.invitations.get_by_token.return_value = a_link()

        await check_may_register(
            mock_db_session, email="invited@acme.com", is_first_user=False, invitation_token="tok"
        )

        repos.invitations.accept.assert_not_called()


class TestTheTokenReachesThePolicyFromTheRequest:
    async def test_register_passes_what_the_body_carried(self, monkeypatch):
        from unittest.mock import patch

        from app.schemas.user import UserCreate
        from app.services.user import UserService

        seen: list[dict] = []

        async def _check(_db, **kwargs):
            seen.append(kwargs)

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=3)))
        monkeypatch.setattr("app.services.user.check_may_register", _check)
        service = UserService(db)

        with (
            patch("app.services.user.user_repo") as repo,
            patch("app.services.user.OrganizationService") as orgs,
            patch("app.services.user.get_email_service"),
            patch("app.services.user.DeploymentSettingsService"),
        ):
            repo.get_by_email = AsyncMock(return_value=None)
            repo.create = AsyncMock(return_value=MagicMock(id=uuid4(), email="new@acme.com"))
            orgs.return_value.create_personal_org = AsyncMock()

            await service.register(
                UserCreate(email="new@acme.com", password="password123", invitation_token="tok")
            )

        assert seen == [
            {"email": "new@acme.com", "is_first_user": False, "invitation_token": "tok"}
        ]

    async def test_a_registration_with_no_token_passes_none(self, monkeypatch):
        from unittest.mock import patch

        from app.schemas.user import UserCreate
        from app.services.user import UserService

        seen: list[dict] = []

        async def _check(_db, **kwargs):
            seen.append(kwargs)

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=3)))
        monkeypatch.setattr("app.services.user.check_may_register", _check)
        service = UserService(db)

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

        assert seen[0]["invitation_token"] is None
