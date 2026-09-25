"""Signing in with a directory account, and the sync's race paths (#1773).

The directory and the ticket acceptor are typed fakes here: what is under test
is the sign-in's own sequence - verify, find or create the account under the
sign-up policy with the directory's admission, refuse a deactivated one, then
reconcile memberships - and the two sign-in methods ending at one account.
The sync's behaviour over real rows is `tests/integration/test_directory_groups.py`.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.services.directory import (
    DirectorySignInService,
    DirectorySyncService,
    build_directory,
    build_ticket_acceptor,
)
from app.services.directory.contract import AcceptedTicket, DirectoryIdentity
from app.services.directory.kerberos import GssapiTicketAcceptor
from app.services.directory.ldap_directory import LdapDirectory
from app.services.directory.sync import winning_role

pytestmark = pytest.mark.anyio

JANE = DirectoryIdentity(
    subject="guid-1",
    email="jane@corp.example",
    full_name="Jane Doe",
    groups=frozenset({"CN=Finance,DC=corp"}),
)


class _Directory:
    def __init__(self) -> None:
        self.asked: list[tuple[str, ...]] = []

    def authenticate(self, username: str, password: str) -> DirectoryIdentity:
        self.asked.append(("authenticate", username, password))
        return JANE

    def lookup_principal(self, principal: str) -> DirectoryIdentity:
        self.asked.append(("lookup", principal))
        return JANE


class _Acceptor:
    def accept(self, token: bytes) -> AcceptedTicket:
        return AcceptedTicket(principal="jane@CORP.EXAMPLE", response_token=b"answer")


def _user(*, active: bool = True) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), is_active=active)


@pytest.fixture
def wired():
    """The account lookup and the sync, patched at the service boundary."""
    user = _user()
    with (
        patch(
            "app.services.directory.sign_in.UserService.get_or_create_oauth_user",
            new=AsyncMock(return_value=user),
        ) as account,
        patch(
            "app.services.directory.sign_in.DirectorySyncService.admits",
            new=AsyncMock(return_value=True),
        ) as admits,
        patch(
            "app.services.directory.sign_in.DirectorySyncService.apply", new=AsyncMock()
        ) as apply,
    ):
        yield user, account, admits, apply


async def test_a_password_sign_in_creates_the_account_admitted_by_its_groups(wired):
    user, account, admits, apply = wired
    directory = _Directory()

    signed_in = await DirectorySignInService(
        MagicMock(), directory=directory, acceptor=None
    ).sign_in_with_password("jane", "pw", invitation_token="tok")

    assert signed_in is user
    assert directory.asked == [("authenticate", "jane", "pw")]
    assert account.call_args.kwargs == {
        "provider": "ldap",
        "provider_id": "guid-1",
        "email": "jane@corp.example",
        "full_name": "Jane Doe",
        "invitation_token": "tok",
        "admitted_by_directory": True,
    }
    assert admits.call_args.args == (JANE.groups,)
    assert apply.call_args.args == (user.id, JANE.groups)
    assert apply.call_args.kwargs == {"provider": "ldap"}


async def test_a_ticket_resolves_to_the_same_account_as_the_password(wired):
    """Both ways in end at one directory entry, so they must end at one account."""
    user, account, _, _ = wired
    directory = _Directory()

    signed_in, answer = await DirectorySignInService(
        MagicMock(), directory=directory, acceptor=_Acceptor()
    ).sign_in_with_ticket(b"token")

    assert (signed_in, answer) == (user, b"answer")
    assert directory.asked == [("lookup", "jane@CORP.EXAMPLE")]
    assert account.call_args.kwargs["provider"] == "ldap"
    assert account.call_args.kwargs["provider_id"] == "guid-1"


@pytest.mark.security
async def test_a_deactivated_account_is_refused_and_its_memberships_left_alone(wired):
    user, _, _, apply = wired
    user.is_active = False

    with pytest.raises(AuthenticationError):
        await DirectorySignInService(
            MagicMock(), directory=_Directory(), acceptor=None
        ).sign_in_with_password("jane", "pw")

    apply.assert_not_awaited()


@pytest.mark.security
async def test_an_unconfigured_directory_answers_like_an_unknown_provider():
    service = DirectorySignInService(MagicMock(), directory=None, acceptor=None)

    with pytest.raises(NotFoundError):
        await service.sign_in_with_password("jane", "pw")
    with pytest.raises(NotFoundError):
        await service.sign_in_with_ticket(b"t")
    with pytest.raises(NotFoundError):
        service.require_kerberos()


async def test_kerberos_needs_the_directory_as_well_as_the_acceptor():
    service = DirectorySignInService(MagicMock(), directory=None, acceptor=_Acceptor())

    with pytest.raises(NotFoundError):
        service.require_kerberos()
    DirectorySignInService(
        MagicMock(), directory=_Directory(), acceptor=_Acceptor()
    ).require_kerberos()


class TestComposition:
    def test_no_url_builds_no_directory_and_kerberos_off_builds_no_acceptor(self):
        settings = Settings(LDAP_URL="", KERBEROS_ENABLED=False)

        assert build_directory(settings) is None
        assert build_ticket_acceptor(settings) is None

    def test_the_configured_adapters_are_built(self):
        settings = Settings(
            LDAP_URL="ldaps://dc.corp.example",
            LDAP_USER_BASE_DN="ou=people,dc=corp",
            KERBEROS_ENABLED=True,
            KERBEROS_KEYTAB="/etc/agenticos.keytab",
        )

        assert isinstance(build_directory(settings), LdapDirectory)
        assert isinstance(build_ticket_acceptor(settings), GssapiTicketAcceptor)


class _Savepoint:
    """`begin_nested()` whose block raises what the database would on a lost race."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _db() -> MagicMock:
    db = MagicMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())
    return db


class TestTheSyncRacingItself:
    """Two sign-ins by one person at once: the loser keeps what the winner wrote."""

    async def test_a_membership_created_concurrently_is_not_an_error(self):
        org_id, user_id = uuid.uuid4(), uuid.uuid4()
        mapping = MagicMock(organization_id=org_id, role="member", group_id=None)
        with (
            patch(
                "app.services.directory.sync.directory_mapping_repo.list_matching",
                new=AsyncMock(return_value=[mapping]),
            ),
            patch("app.services.directory.sync.member_repo") as members,
            patch("app.services.directory.sync.group_repo") as groups,
            patch("app.services.directory.sync.record_audit", new=AsyncMock()) as audit,
        ):
            members.get = AsyncMock(return_value=None)
            members.create = AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
            members.list_for_user_by_source = AsyncMock(return_value=[])
            groups.list_memberships_in_org = AsyncMock(return_value=[])
            groups.organizations_with_directory_groups = AsyncMock(return_value=[])

            await DirectorySyncService(_db()).apply(user_id, ["g"], provider="ldap")

        audit.assert_not_awaited()

    async def test_a_group_membership_created_concurrently_is_not_an_error(self):
        org_id, user_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        mapping = MagicMock(organization_id=org_id, role="member", group_id=group_id)
        with (
            patch(
                "app.services.directory.sync.directory_mapping_repo.list_matching",
                new=AsyncMock(return_value=[mapping]),
            ),
            patch("app.services.directory.sync.member_repo") as members,
            patch("app.services.directory.sync.group_repo") as groups,
            patch("app.services.directory.sync.record_audit", new=AsyncMock()) as audit,
        ):
            members.get = AsyncMock(
                return_value=MagicMock(source="directory", role="member", organization_id=org_id)
            )
            members.list_for_user_by_source = AsyncMock(return_value=[])
            groups.list_memberships_in_org = AsyncMock(return_value=[])
            groups.add_member = AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
            groups.organizations_with_directory_groups = AsyncMock(return_value=[org_id])

            await DirectorySyncService(_db()).apply(user_id, ["g"], provider="ldap")

        audit.assert_not_awaited()


class TestWinningRole:
    def test_a_role_outside_the_catalog_resolves_to_the_least_a_member_holds(self):
        """The schema forbids it, so such a row was written some other way - fail low."""
        assert winning_role([MagicMock(role="superuser")]) == "viewer"

    def test_the_first_role_of_the_precedence_wins(self):
        mappings = [MagicMock(role="viewer"), MagicMock(role="operator"), MagicMock(role="admin")]

        assert winning_role(mappings) == "admin"
