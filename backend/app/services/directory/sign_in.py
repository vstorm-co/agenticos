"""Signing a person in with their directory account - by password or by Kerberos ticket.

Both ways end at the same directory entry, so both end at the same platform
account: it is keyed on the entry's stable identifier under the provider name
`ldap`, whichever way the person arrived. Somebody who signs in with a password
on Monday and through Windows sign-in on Tuesday is one account, not two.

The sequence is the one an OIDC sign-in follows, with the directory standing in
for the identity provider: verify the identity, find or create the account under
the deployment's sign-up policy, then reconcile the person's directory-managed
memberships with the organizations' mappings. A mapping matching one of their
groups admits them past `invite_only`, as an invitation would.

The directory and the ticket acceptor are blocking libraries, so they run in a
worker thread. Cancelling the request does not stop a bind already on the wire;
it only stops waiting for it, and nothing is written for a sign-in that did not
finish.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, NotFoundError
from app.db.models.user import User
from app.services.directory.contract import (
    AcceptedTicket,
    Directory,
    DirectoryIdentity,
    TicketAcceptor,
)
from app.services.directory.sync import DirectorySyncService
from app.services.user import UserService

#: The provider name directory accounts are stored under, for both ways in.
DIRECTORY_PROVIDER = "ldap"


class DirectorySignInService:
    """Turns directory credentials or a Kerberos ticket into a signed-in account."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        directory: Directory | None,
        acceptor: TicketAcceptor | None,
    ) -> None:
        self.db = db
        self._directory = directory
        self._acceptor = acceptor

    def _require_directory(self) -> Directory:
        if self._directory is None:
            # The same refusal an unconfigured OIDC provider gets: which sign-in
            # methods a deployment runs is not something a stranger enumerates.
            raise NotFoundError(message="Unknown sign-in provider")
        return self._directory

    def _require_acceptor(self) -> TicketAcceptor:
        if self._acceptor is None:
            raise NotFoundError(message="Unknown sign-in provider")
        return self._acceptor

    def require_kerberos(self) -> None:
        """Refuse before any challenge is sent, when Kerberos sign-in is not configured.

        Raises:
            NotFoundError: Kerberos or the directory it resolves principals in is off.
        """
        self._require_acceptor()
        self._require_directory()

    async def sign_in_with_password(
        self, username: str, password: str, *, invitation_token: str | None = None
    ) -> User:
        """The account behind these directory credentials, created on first sign-in.

        Raises:
            NotFoundError: No directory is configured.
            DirectoryCredentialsRejected: Wrong username or password.
            DirectoryAccountUnusable: The account cannot be signed in here.
            DirectoryUnavailable: The directory could not be asked.
            AuthorizationError: The sign-up policy refuses a new account.
            AuthenticationError: The platform account is deactivated.
        """
        directory = self._require_directory()
        identity = await asyncio.to_thread(directory.authenticate, username, password)
        return await self._account_for(identity, invitation_token=invitation_token)

    async def sign_in_with_ticket(
        self, token: bytes, *, invitation_token: str | None = None
    ) -> tuple[User, bytes | None]:
        """The account behind a Kerberos ticket, and the token to answer the browser with.

        Raises:
            NotFoundError: Kerberos, or the directory it needs, is not configured.
            TicketRejected: The token is not a ticket for this service.
            DirectoryAccountUnusable: No single directory account holds the principal.
            DirectoryUnavailable: The directory could not be asked.
            AuthorizationError: The sign-up policy refuses a new account.
            AuthenticationError: The platform account is deactivated.
        """
        acceptor = self._require_acceptor()
        directory = self._require_directory()
        ticket: AcceptedTicket = await asyncio.to_thread(acceptor.accept, token)
        identity = await asyncio.to_thread(directory.lookup_principal, ticket.principal)
        user = await self._account_for(identity, invitation_token=invitation_token)
        return user, ticket.response_token

    async def _account_for(
        self, identity: DirectoryIdentity, *, invitation_token: str | None
    ) -> User:
        sync = DirectorySyncService(self.db)
        user = await UserService(self.db).get_or_create_oauth_user(
            provider=DIRECTORY_PROVIDER,
            provider_id=identity.subject,
            email=identity.email,
            full_name=identity.full_name,
            invitation_token=invitation_token,
            admitted_by_directory=await sync.admits(identity.groups),
        )
        if not user.is_active:
            raise AuthenticationError(message="User account is disabled")
        await sync.apply(user.id, identity.groups, provider=DIRECTORY_PROVIDER)
        return user
