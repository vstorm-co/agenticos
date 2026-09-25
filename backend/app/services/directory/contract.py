"""What the sign-in needs from a directory, independent of how it is reached.

Two narrow contracts. `Directory` turns credentials or a Kerberos principal into
a `DirectoryIdentity`; `TicketAcceptor` turns a SPNEGO token into a principal.
The sign-in service depends on these and nothing else, so replacing `ldap3` or
`gssapi` is an adapter and a line in `app/api/deps.py`, never a change to who is
admitted or which organization they land in.

Both contracts are synchronous and blocking - that is what the libraries behind
them are - and the service runs them off the event loop. Neither retries: a bind
the directory refused is an answer, and one it never received is reported as
unavailable for the person to try again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import AuthenticationError, ExternalServiceError


@dataclass(frozen=True)
class DirectoryIdentity:
    """One directory account, as far as signing it in is concerned.

    `subject` is the directory's stable identifier for the account (an
    `entryUUID` or `objectGUID`), which the platform account is keyed on.
    `groups` are what the directory reports, verbatim; matching them against
    mappings is case-insensitive and happens elsewhere.
    """

    subject: str
    email: str
    full_name: str | None
    groups: frozenset[str]


@dataclass(frozen=True)
class AcceptedTicket:
    """A Kerberos ticket this service accepted: whose it was, and what to answer."""

    principal: str
    response_token: bytes | None


class Directory(Protocol):
    """Looks accounts up in a company directory."""

    def authenticate(self, username: str, password: str) -> DirectoryIdentity:
        """Find the account `username` names and prove `password` is its own.

        Raises:
            DirectoryCredentialsRejected: No such account, or the password is wrong.
            DirectoryAccountUnusable: The account cannot be signed in here.
            DirectoryUnavailable: The directory could not be asked.
        """
        ...

    def lookup_principal(self, principal: str) -> DirectoryIdentity:
        """The account a Kerberos principal belongs to.

        Raises:
            DirectoryAccountUnusable: No single account, or one with no address.
            DirectoryUnavailable: The directory could not be asked.
        """
        ...


class TicketAcceptor(Protocol):
    """Accepts a SPNEGO/Kerberos token addressed to this service."""

    def accept(self, token: bytes) -> AcceptedTicket:
        """Validate one token against this service's key.

        Raises:
            TicketRejected: The token is not a ticket this service accepts.
        """
        ...


class DirectoryCredentialsRejected(AuthenticationError):
    """The username or the password is wrong - deliberately indistinguishable."""

    message = "Invalid username or password"
    code = "DIRECTORY_CREDENTIALS_REJECTED"


class DirectoryAccountUnusable(AuthenticationError):
    """The directory has the account, and it still cannot be signed in here.

    No address to key an account on, two accounts matching one name, a principal
    nobody in the directory holds. Which of those it was goes to the log: the
    sign-in page is public.
    """

    message = "That directory account cannot be used to sign in here."
    code = "DIRECTORY_ACCOUNT_UNUSABLE"


class DirectoryUnavailable(ExternalServiceError):
    """The directory did not answer, or refused the service account."""

    message = "The directory could not be reached. Try again in a moment."
    code = "DIRECTORY_UNAVAILABLE"


class TicketRejected(AuthenticationError):
    """The browser's Kerberos token was not a ticket this service accepts."""

    message = "Windows sign-in did not work from this device. Sign in with your password instead."
    code = "KERBEROS_TICKET_REJECTED"
