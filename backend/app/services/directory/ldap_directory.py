"""The `Directory` contract over LDAP, with `ldap3`.

A sign-in is the standard two-step bind (RFC 4513): search for the account with
the service account's credentials, then bind *as the account* with the password
the person typed. The directory is the only thing that ever checks the password;
it is not stored, hashed or logged here.

Three refusals are deliberate, and each is a known way LDAP sign-ins fail open:

- **An empty password never reaches a bind.** A simple bind with a name and no
  password is an *unauthenticated* bind (RFC 4513 s.5.1.2), which many servers
  answer with success. `ldap3` refuses one too; this refuses first.
- **The username is escaped into the filter** (RFC 4515), so `*)(uid=*` finds
  nobody rather than everybody.
- **Two accounts matching one name is a refusal, not the first of them.** A
  filter matching on `uid`, `mail` and `sAMAccountName` at once can match two
  people, and binding as whichever came back first would sign one in as the
  other if they shared a password.

TLS is verified: the certificate chain against the system store or
`LDAP_CA_CERT_FILE`, and the host name against the certificate. `ldap://` without
StartTLS is refused at startup unless plaintext is allowed explicitly.
"""

from __future__ import annotations

import logging
import ssl
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from ldap3 import NO_ATTRIBUTES, NONE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.core.config import Settings
from app.services.directory.contract import (
    DirectoryAccountUnusable,
    DirectoryCredentialsRejected,
    DirectoryIdentity,
    DirectoryUnavailable,
)

logger = logging.getLogger(__name__)

#: `invalidCredentials`. Active Directory also answers it for a disabled,
#: locked or expired account, with the reason in a sub-code nobody outside the
#: directory should be told.
_INVALID_CREDENTIALS = 49
#: `inappropriateAuthentication` and `unwillingToPerform` - how OpenLDAP's
#: password policy and some appliances refuse a bind for an account state
#: rather than a transport problem. Still the person's refusal, not an outage.
_ACCOUNT_REFUSALS = frozenset({48, 53})
#: `success` and `sizeLimitExceeded` - the second is what asking for at most two
#: accounts answers when a name matches more, and the two it did return are the
#: whole point of asking.
_SEARCH_ANSWERED = frozenset({0, 4})


@dataclass(frozen=True)
class LdapConfig:
    """Everything the adapter reads from the deployment's settings."""

    url: str
    start_tls: bool
    ca_cert_file: str | None
    bind_dn: str | None
    bind_password: str | None
    user_base_dn: str
    user_filter: str
    email_attribute: str
    name_attribute: str
    id_attribute: str
    group_attribute: str
    group_base_dn: str | None
    group_filter: str
    kerberos_filter: str
    timeout_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> LdapConfig | None:
        """The configuration, or None where no directory is configured."""
        if not settings.LDAP_URL:
            return None
        return cls(
            url=settings.LDAP_URL,
            start_tls=settings.LDAP_START_TLS,
            ca_cert_file=settings.LDAP_CA_CERT_FILE or None,
            bind_dn=settings.LDAP_BIND_DN or None,
            bind_password=settings.LDAP_BIND_PASSWORD or None,
            user_base_dn=settings.LDAP_USER_BASE_DN,
            user_filter=settings.LDAP_USER_FILTER,
            email_attribute=settings.LDAP_EMAIL_ATTRIBUTE,
            name_attribute=settings.LDAP_NAME_ATTRIBUTE,
            id_attribute=settings.LDAP_ID_ATTRIBUTE,
            group_attribute=settings.LDAP_GROUP_ATTRIBUTE,
            group_base_dn=settings.LDAP_GROUP_BASE_DN or None,
            group_filter=settings.LDAP_GROUP_FILTER,
            kerberos_filter=settings.LDAP_KERBEROS_FILTER,
            timeout_seconds=settings.LDAP_TIMEOUT_SECONDS,
        )


#: Opens an unbound connection as `(user DN, password)`, or anonymously for `(None, None)`.
ConnectionFactory = Callable[[str | None, str | None], Connection]


def verified_tls_connections(config: LdapConfig) -> ConnectionFactory:
    """Real connections to the configured directory, TLS verified and time-bounded.

    Nothing is opened here - `ldap3` connects on `open()` - so building the
    factory at startup costs no network round trip.
    """
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=config.ca_cert_file)
    server = Server(
        config.url,
        use_ssl=config.url.startswith("ldaps://"),
        tls=tls,
        get_info=NONE,
        connect_timeout=config.timeout_seconds,
    )

    def connect(user: str | None, password: str | None) -> Connection:
        return Connection(
            server,
            user=user,
            password=password,
            authentication="SIMPLE" if user else "ANONYMOUS",
            read_only=True,
            receive_timeout=config.timeout_seconds,
            raise_exceptions=False,
        )

    return connect


@dataclass(frozen=True)
class _Entry:
    """One search result: its DN and its raw attribute values, names case-folded."""

    dn: str
    attributes: Mapping[str, list[bytes]]

    def first(self, attribute: str) -> bytes | None:
        values = self.attributes.get(attribute.casefold())
        return values[0] if values else None

    def text(self, attribute: str) -> str | None:
        raw = self.first(attribute)
        if raw is None:
            return None
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        return value or None

    def texts(self, attribute: str) -> list[str]:
        found = []
        for raw in self.attributes.get(attribute.casefold(), []):
            try:
                found.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                continue
        return found


def _entries(response: object) -> list[_Entry]:
    """The search entries in an `ldap3` response, ignoring referrals.

    The response is untyped in `ldap3`, so it is narrowed here once rather than
    trusted wherever it is read.
    """
    if not isinstance(response, list):
        return []
    found: list[_Entry] = []
    for item in response:
        if not isinstance(item, Mapping) or item.get("type") != "searchResEntry":
            continue
        dn = item.get("dn")
        # A `Mapping`, not a `dict`: `ldap3` hands the attributes back in its own
        # `CaseInsensitiveDict`, which is neither.
        raw = item.get("raw_attributes")
        if not isinstance(dn, str) or not isinstance(raw, Mapping):
            continue
        attributes = {
            str(name).casefold(): [value for value in values if isinstance(value, bytes)]
            for name, values in raw.items()
            if isinstance(values, list)
        }
        found.append(_Entry(dn=dn, attributes=attributes))
    return found


def _fill(template: str, **values: str) -> str:
    """Put escaped values into a filter template's `{name}` placeholders.

    `str.replace` rather than `str.format`: a filter an operator wrote may name
    only some of the placeholders, and `format` would raise on the rest.
    """
    for name, value in values.items():
        template = template.replace("{" + name + "}", escape_filter_chars(value))
    return template


def _result_code(connection: Connection) -> int | None:
    code = connection.result.get("result") if isinstance(connection.result, dict) else None
    return code if isinstance(code, int) else None


class LdapDirectory:
    """Finds and verifies accounts in one LDAP directory."""

    def __init__(self, config: LdapConfig, connect: ConnectionFactory | None = None) -> None:
        self._config = config
        self._connect = connect or verified_tls_connections(config)

    def authenticate(self, username: str, password: str) -> DirectoryIdentity:
        """See `Directory.authenticate`."""
        if not password:
            raise DirectoryCredentialsRejected()
        with self._service_connection() as connection:
            entries = self._search_accounts(
                connection, _fill(self._config.user_filter, username=username)
            )
            if not entries:
                raise DirectoryCredentialsRejected()
            if len(entries) > 1:
                logger.warning("ldap_sign_in_ambiguous", extra={"matches": len(entries)})
                raise DirectoryAccountUnusable()
            entry = entries[0]
            self._bind_as(entry.dn, password)
            groups = self._groups(connection, entry, username=username)
        return self._identity(entry, groups)

    def lookup_principal(self, principal: str) -> DirectoryIdentity:
        """See `Directory.lookup_principal`."""
        username = principal.partition("@")[0]
        search = _fill(self._config.kerberos_filter, principal=principal, username=username)
        with self._service_connection() as connection:
            entries = self._search_accounts(connection, search)
            if len(entries) != 1:
                logger.warning("kerberos_principal_unresolved", extra={"matches": len(entries)})
                raise DirectoryAccountUnusable()
            entry = entries[0]
            groups = self._groups(connection, entry, username=username)
        return self._identity(entry, groups)

    @contextmanager
    def _service_connection(self) -> Iterator[Connection]:
        """A connection bound as the service account (or anonymously), closed afterwards."""
        connection = self._connect(self._config.bind_dn, self._config.bind_password)
        try:
            self._open(connection)
            if not connection.bind():
                # The service account itself was refused: a configuration fault,
                # not the person's, and nothing they can fix by retyping.
                logger.error("ldap_service_bind_refused", extra={"code": _result_code(connection)})
                raise DirectoryUnavailable()
            yield connection
        except LDAPException as exc:
            logger.warning("ldap_unreachable", extra={"error": type(exc).__name__})
            raise DirectoryUnavailable() from exc
        finally:
            connection.unbind()

    def _open(self, connection: Connection) -> None:
        connection.open()
        if self._config.start_tls:
            connection.start_tls()

    def _bind_as(self, dn: str, password: str) -> None:
        """Prove `password` is the account's by binding as it."""
        connection = self._connect(dn, password)
        try:
            self._open(connection)
            bound = bool(connection.bind())
            code = _result_code(connection)
        except LDAPException as exc:
            logger.warning("ldap_unreachable", extra={"error": type(exc).__name__})
            raise DirectoryUnavailable() from exc
        finally:
            connection.unbind()
        if bound:
            return
        if code == _INVALID_CREDENTIALS or code in _ACCOUNT_REFUSALS:
            raise DirectoryCredentialsRejected()
        logger.warning("ldap_user_bind_failed", extra={"code": code})
        raise DirectoryUnavailable()

    def _search_accounts(self, connection: Connection, search_filter: str) -> list[_Entry]:
        config = self._config
        connection.search(
            config.user_base_dn,
            search_filter,
            search_scope="SUBTREE",
            attributes=[
                config.email_attribute,
                config.name_attribute,
                config.id_attribute,
                config.group_attribute,
            ],
            # Two is enough to know a name is ambiguous, and no more are read.
            size_limit=2,
        )
        self._require_answer(connection)
        return _entries(connection.response)

    @staticmethod
    def _require_answer(connection: Connection) -> None:
        """Refuse a search the directory did not answer.

        A base DN that does not exist, a filter the server cannot parse, a
        service account not allowed to read the tree: each comes back as a
        failed search with no entries, and reading that as "no such account"
        would tell every person in the company their password is wrong. It is
        a configuration fault, and it is reported as one.
        """
        code = _result_code(connection)
        if code not in _SEARCH_ANSWERED:
            logger.error("ldap_search_failed", extra={"code": code})
            raise DirectoryUnavailable()

    def _groups(self, connection: Connection, entry: _Entry, *, username: str) -> frozenset[str]:
        """The account's groups: its `memberOf`, or a search where the directory keeps none."""
        config = self._config
        if config.group_base_dn is None:
            return frozenset(entry.texts(config.group_attribute))
        connection.search(
            config.group_base_dn,
            _fill(config.group_filter, dn=entry.dn, username=username),
            search_scope="SUBTREE",
            attributes=NO_ATTRIBUTES,
        )
        self._require_answer(connection)
        return frozenset(found.dn for found in _entries(connection.response))

    def _identity(self, entry: _Entry, groups: frozenset[str]) -> DirectoryIdentity:
        config = self._config
        subject = _subject(entry.first(config.id_attribute))
        email = entry.text(config.email_attribute)
        if subject is None or email is None:
            logger.warning(
                "ldap_account_incomplete",
                extra={"has_id": subject is not None, "has_email": email is not None},
            )
            raise DirectoryAccountUnusable()
        return DirectoryIdentity(
            subject=subject,
            email=email,
            full_name=entry.text(config.name_attribute),
            groups=groups,
        )


def _subject(raw: bytes | None) -> str | None:
    """The account's stable identifier as text.

    Active Directory's `objectGUID` is sixteen raw bytes in the mixed-endian
    layout Windows uses, and is rendered the way Windows prints it so the key
    matches what an administrator sees in their own tools. Anything else - an
    `entryUUID`, a FreeIPA `ipaUniqueID` - is already text.
    """
    if raw is None:
        return None
    if len(raw) == 16:
        return str(uuid.UUID(bytes_le=raw))
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return value or None
