"""The LDAP adapter, against `ldap3`'s in-memory directory (#1773).

`MOCK_SYNC` is `ldap3`'s own offline server: it answers binds against the
`userPassword` of the entries it holds and evaluates search filters, so these
tests drive the real two-step bind and the real filter escaping rather than a
mock of either. What it cannot show - TLS, a real server's result codes for a
locked account - is what `verified_tls_connections` and the result-code tests
below pin by other means.
"""

from __future__ import annotations

import ssl
import uuid

import pytest
from ldap3 import MOCK_SYNC, NONE, Connection, Server
from ldap3.core.exceptions import LDAPSocketOpenError

from app.core.config import Settings
from app.services.directory.contract import (
    DirectoryAccountUnusable,
    DirectoryCredentialsRejected,
    DirectoryUnavailable,
)
from app.services.directory.ldap_directory import (
    LdapConfig,
    LdapDirectory,
    _entries,
    verified_tls_connections,
)

SERVICE_DN = "cn=svc,dc=corp"
PEOPLE = "ou=people,dc=corp"
JANE_DN = "cn=jane,ou=people,dc=corp"
FINANCE_DN = "cn=finance,ou=groups,dc=corp"


def _config(**overrides: object) -> LdapConfig:
    values: dict[str, object] = {
        "url": "ldaps://dc.corp.example",
        "start_tls": False,
        "ca_cert_file": None,
        "bind_dn": SERVICE_DN,
        "bind_password": "service-secret",
        "user_base_dn": PEOPLE,
        "user_filter": "(&(objectClass=person)(|(uid={username})(mail={username})))",
        "email_attribute": "mail",
        "name_attribute": "displayName",
        "id_attribute": "entryUUID",
        "group_attribute": "memberOf",
        "group_base_dn": None,
        "group_filter": "(member={dn})",
        "kerberos_filter": "(userPrincipalName={principal})",
        "timeout_seconds": 5,
    }
    values.update(overrides)
    return LdapConfig(**values)  # type: ignore[arg-type]


class _Directory:
    """An in-memory directory and a connection factory onto it."""

    def __init__(self) -> None:
        self.server = Server("fake", get_info=NONE)
        self.opened: list[Connection] = []
        seed = self.connect(SERVICE_DN, "service-secret")
        self._add = seed.strategy.add_entry
        self._add(SERVICE_DN, {"objectClass": "person", "userPassword": "service-secret"})

    def connect(self, user: str | None, password: str | None) -> Connection:
        connection = Connection(
            self.server, user=user, password=password, client_strategy=MOCK_SYNC
        )
        self.opened.append(connection)
        return connection

    def person(self, dn: str, **attributes: object) -> None:
        self._add(dn, {"objectClass": "person", **attributes})


@pytest.fixture
def directory() -> _Directory:
    fake = _Directory()
    fake.person(
        JANE_DN,
        uid="jane",
        mail="jane@corp.example",
        displayName="Jane Doe",
        userPassword="correct horse",
        entryUUID="7d3c2b1a-0000-4000-8000-000000000001",
        memberOf=[FINANCE_DN, "cn=ai,ou=groups,dc=corp"],
        userPrincipalName="jane@CORP.EXAMPLE",
    )
    return fake


class TestAuthenticate:
    def test_the_right_password_signs_in_with_the_directorys_address_and_groups(self, directory):
        identity = LdapDirectory(_config(), directory.connect).authenticate("jane", "correct horse")

        assert identity.subject == "7d3c2b1a-0000-4000-8000-000000000001"
        assert identity.email == "jane@corp.example"
        assert identity.full_name == "Jane Doe"
        assert identity.groups == frozenset({FINANCE_DN, "cn=ai,ou=groups,dc=corp"})

    @pytest.mark.security
    def test_a_wrong_password_is_refused(self, directory):
        with pytest.raises(DirectoryCredentialsRejected):
            LdapDirectory(_config(), directory.connect).authenticate("jane", "wrong")

    @pytest.mark.security
    def test_an_unknown_account_is_refused_the_same_way(self, directory):
        """No difference between "no such user" and "wrong password" reaches the caller."""
        with pytest.raises(DirectoryCredentialsRejected) as refused:
            LdapDirectory(_config(), directory.connect).authenticate("nobody", "whatever")

        assert refused.value.message == "Invalid username or password"

    @pytest.mark.security
    def test_an_empty_password_never_reaches_a_bind(self, directory):
        """An empty simple bind is an unauthenticated bind many servers accept (RFC 4513)."""
        with pytest.raises(DirectoryCredentialsRejected):
            LdapDirectory(_config(), directory.connect).authenticate("jane", "")

        assert directory.opened[1:] == []

    @pytest.mark.security
    def test_a_filter_metacharacter_in_the_username_finds_nobody(self, directory):
        """`*` unescaped would match every account, and the first would be bound as."""
        with pytest.raises(DirectoryCredentialsRejected):
            LdapDirectory(_config(), directory.connect).authenticate("*", "correct horse")

    @pytest.mark.security
    def test_two_accounts_matching_one_name_is_a_refusal_not_the_first(self, directory):
        directory.person(
            "cn=jane2,ou=people,dc=corp",
            uid="jane2",
            mail="jane",
            userPassword="correct horse",
            entryUUID="7d3c2b1a-0000-4000-8000-000000000002",
        )

        with pytest.raises(DirectoryAccountUnusable):
            LdapDirectory(_config(), directory.connect).authenticate("jane", "correct horse")

    def test_an_account_with_no_address_cannot_sign_in(self, directory):
        directory.person(
            "cn=noaddr,ou=people,dc=corp",
            uid="noaddr",
            userPassword="pw",
            entryUUID="7d3c2b1a-0000-4000-8000-000000000003",
        )

        with pytest.raises(DirectoryAccountUnusable):
            LdapDirectory(_config(), directory.connect).authenticate("noaddr", "pw")

    def test_an_active_directory_guid_is_rendered_the_way_windows_prints_it(self, directory):
        guid = uuid.uuid4()
        directory.person(
            "cn=ad,ou=people,dc=corp",
            uid="ad",
            mail="ad@corp.example",
            userPassword="pw",
            objectGUID=guid.bytes_le,
        )

        identity = LdapDirectory(
            _config(id_attribute="objectGUID"), directory.connect
        ).authenticate("ad", "pw")

        assert identity.subject == str(guid)

    def test_groups_can_come_from_a_search_where_there_is_no_member_of(self, directory):
        directory._add(FINANCE_DN, {"objectClass": "groupOfNames", "member": JANE_DN})
        directory._add(
            "cn=other,ou=groups,dc=corp", {"objectClass": "groupOfNames", "member": "cn=x"}
        )
        config = _config(group_base_dn="ou=groups,dc=corp", group_filter="(member={dn})")

        identity = LdapDirectory(config, directory.connect).authenticate("jane", "correct horse")

        assert identity.groups == frozenset({FINANCE_DN})


class TestLookupPrincipal:
    def test_a_principal_resolves_to_its_account_without_a_password(self, directory):
        identity = LdapDirectory(_config(), directory.connect).lookup_principal("jane@CORP.EXAMPLE")

        assert identity.email == "jane@corp.example"
        assert FINANCE_DN in identity.groups

    def test_the_username_half_of_a_principal_can_be_searched_on(self, directory):
        config = _config(kerberos_filter="(uid={username})")

        identity = LdapDirectory(config, directory.connect).lookup_principal("jane@CORP.EXAMPLE")

        assert identity.subject == "7d3c2b1a-0000-4000-8000-000000000001"

    def test_a_principal_nobody_holds_is_unusable(self, directory):
        with pytest.raises(DirectoryAccountUnusable):
            LdapDirectory(_config(), directory.connect).lookup_principal("ghost@CORP.EXAMPLE")


class _Scripted:
    """A connection stand-in whose bind and search outcomes a test chooses."""

    def __init__(
        self,
        *,
        bind: bool = True,
        bind_code: int = 0,
        search_code: int = 0,
        response: object = None,
        open_error: Exception | None = None,
    ) -> None:
        self._bind = bind
        self._bind_code = bind_code
        self._search_code = search_code
        self.response = response if response is not None else []
        self._open_error = open_error
        self.result: dict[str, object] = {}
        self.tls_started = False
        self.unbound = False

    def open(self) -> None:
        if self._open_error is not None:
            raise self._open_error

    def start_tls(self) -> None:
        self.tls_started = True

    def bind(self) -> bool:
        self.result = {"result": self._bind_code}
        return self._bind

    def search(self, *args: object, **kwargs: object) -> bool:
        self.result = {"result": self._search_code}
        return self._search_code == 0

    def unbind(self) -> None:
        self.unbound = True


def _factory(*connections: _Scripted):
    queue = list(connections)
    return lambda user, password: queue.pop(0)


_JANE_ENTRY = [
    {
        "type": "searchResEntry",
        "dn": JANE_DN,
        "raw_attributes": {"mail": [b"jane@corp.example"], "entryUUID": [b"id-1"]},
    }
]


class TestTheDirectoryMisbehaving:
    def test_an_unreachable_directory_is_unavailable_and_the_connection_is_closed(self):
        service = _Scripted(open_error=LDAPSocketOpenError("refused"))

        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(_config(), _factory(service)).authenticate("jane", "pw")

        assert service.unbound

    def test_a_refused_service_account_is_a_configuration_fault_not_a_wrong_password(self):
        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(_config(), _factory(_Scripted(bind=False, bind_code=49))).authenticate(
                "jane", "pw"
            )

    def test_a_failed_search_is_not_read_as_no_such_account(self):
        """A wrong base DN would otherwise tell the whole company its passwords are wrong."""
        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(_config(), _factory(_Scripted(search_code=32))).authenticate("jane", "pw")

    def test_a_failed_group_search_is_unavailable_too(self):
        person = _Scripted()
        config = _config(group_base_dn="ou=groups,dc=corp")

        class _GroupSearchFails(_Scripted):
            def __init__(self) -> None:
                super().__init__(response=_JANE_ENTRY)
                self.calls = 0

            def search(self, *args: object, **kwargs: object) -> bool:
                self.calls += 1
                self.result = {"result": 0 if self.calls == 1 else 50}
                return self.calls == 1

        failing = _GroupSearchFails()
        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(config, _factory(failing, person)).authenticate("jane", "pw")
        assert failing.calls == 2

    @pytest.mark.parametrize("code", [49, 48, 53])
    def test_an_account_state_refusal_is_the_persons_refusal(self, code):
        with pytest.raises(DirectoryCredentialsRejected):
            LdapDirectory(
                _config(),
                _factory(_Scripted(response=_JANE_ENTRY), _Scripted(bind=False, bind_code=code)),
            ).authenticate("jane", "pw")

    def test_any_other_bind_failure_is_the_directorys(self):
        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(
                _config(),
                _factory(_Scripted(response=_JANE_ENTRY), _Scripted(bind=False, bind_code=51)),
            ).authenticate("jane", "pw")

    def test_the_person_bind_dropping_is_unavailable(self):
        person = _Scripted(open_error=LDAPSocketOpenError("reset"))

        with pytest.raises(DirectoryUnavailable):
            LdapDirectory(
                _config(), _factory(_Scripted(response=_JANE_ENTRY), person)
            ).authenticate("jane", "pw")

        assert person.unbound

    def test_start_tls_upgrades_both_connections_before_either_binds(self):
        service = _Scripted(response=_JANE_ENTRY)
        person = _Scripted()

        LdapDirectory(
            _config(url="ldap://dc.corp.example", start_tls=True), _factory(service, person)
        ).authenticate("jane", "pw")

        assert service.tls_started and person.tls_started


class TestResponseParsing:
    def test_referrals_and_malformed_items_are_ignored(self):
        response = [
            {"type": "searchResRef", "uri": ["ldap://elsewhere"]},
            "not a dict",
            {"type": "searchResEntry", "dn": 7, "raw_attributes": {}},
            {"type": "searchResEntry", "dn": "cn=a", "raw_attributes": "nope"},
            {
                "type": "searchResEntry",
                "dn": "cn=b",
                "raw_attributes": {"Mail": [b"b@x", "not bytes"], "odd": "scalar"},
            },
        ]

        (entry,) = _entries(response)

        assert entry.dn == "cn=b"
        assert entry.attributes == {"mail": [b"b@x"]}

    def test_a_response_that_is_not_a_list_has_no_entries(self):
        assert _entries(None) == []

    def test_undecodable_values_are_skipped_rather_than_guessed(self):
        (entry,) = _entries(
            [
                {
                    "type": "searchResEntry",
                    "dn": "cn=c",
                    "raw_attributes": {
                        "mail": [b"\xff\xfe"],
                        "memberOf": [b"\xff", b"cn=g"],
                        "entryUUID": [b"\xff\xfe\xfd"],
                        "displayName": [b"   "],
                    },
                }
            ]
        )

        assert entry.text("mail") is None
        assert entry.text("displayName") is None
        assert entry.text("absent") is None
        assert entry.texts("memberOf") == ["cn=g"]


class TestConfiguration:
    def test_nothing_is_configured_without_a_url(self):
        assert LdapConfig.from_settings(Settings(LDAP_URL="")) is None

    def test_every_setting_reaches_the_adapter(self):
        config = LdapConfig.from_settings(
            Settings(
                LDAP_URL="ldaps://dc.corp.example",
                LDAP_USER_BASE_DN=PEOPLE,
                LDAP_BIND_DN=SERVICE_DN,
                LDAP_BIND_PASSWORD="s",
                LDAP_CA_CERT_FILE="/etc/ssl/corp.pem",
                LDAP_GROUP_BASE_DN="ou=groups,dc=corp",
            )
        )

        assert config is not None
        assert (config.bind_dn, config.ca_cert_file, config.group_base_dn) == (
            SERVICE_DN,
            "/etc/ssl/corp.pem",
            "ou=groups,dc=corp",
        )

    def test_real_connections_verify_the_certificate_and_bound_their_waits(self, tmp_path):
        bundle = tmp_path / "corp.pem"
        bundle.write_text("-----BEGIN CERTIFICATE-----\n")
        connect = verified_tls_connections(_config(ca_cert_file=str(bundle)))

        connection = connect(SERVICE_DN, "s")
        anonymous = connect(None, None)

        assert connection.server.ssl is True
        assert connection.server.tls.validate == ssl.CERT_REQUIRED
        assert connection.server.tls.ca_certs_file == str(bundle)
        assert connection.server.connect_timeout == 5
        # An int, not merely 5: `ldap3` packs the read timeout with
        # `struct.pack('LL', ...)` on Linux and macOS, and a float there failed
        # every real connection while every test against the in-memory server
        # passed - found by signing in against a real OpenLDAP.
        assert type(connection.receive_timeout) is int
        assert connection.receive_timeout == 5
        assert connection.authentication == "SIMPLE"
        assert anonymous.authentication == "ANONYMOUS"
        assert connection.closed
