"""The `TicketAcceptor` contract over GSSAPI, for SPNEGO ("Negotiate") sign-in.

A browser on a domain-joined machine, pointed at a host its policy trusts,
answers `WWW-Authenticate: Negotiate` with a Kerberos ticket for
`HTTP/<host>`. Accepting it with this service's key proves who the person is
without a password crossing the network at all.

`gssapi` arrives with the `kerberos` extra, which a default install and CI do not
have: it builds against the system Kerberos libraries (`libkrb5-dev` to build,
`libgssapi-krb5-2` to run). Everything else in this package works without it, and
a deployment that enabled Kerberos without the extra gets a `ConfigurationError`
naming the extra rather than an `ImportError` from inside a request.

Only a ticket accepted in one step is accepted at all. Kerberos inside SPNEGO
completes in one leg; the multi-leg exchange is NTLM, which is not a ticket, is
not offered, and would need state held between requests to finish.
"""

from __future__ import annotations

import logging

from app.core.exceptions import ConfigurationError
from app.services.directory.contract import AcceptedTicket, TicketRejected

logger = logging.getLogger(__name__)

MISSING_EXTRA = (
    "Kerberos sign-in needs the `kerberos` extra: build the image with "
    '`--build-arg EXTRAS="--extra kerberos"` (it needs libkrb5-dev to build and '
    "libgssapi-krb5-2 to run)"
)


class GssapiTicketAcceptor:
    """Accepts tickets for this service with the key in its keytab."""

    def __init__(self, *, keytab: str | None, service_principal: str | None) -> None:
        self._keytab = keytab
        self._service_principal = service_principal

    def accept(self, token: bytes) -> AcceptedTicket:
        """See `TicketAcceptor.accept`.

        Raises:
            ConfigurationError: The `kerberos` extra is not installed.
            TicketRejected: The token is malformed, for another service, expired,
                or needs a second leg.
        """
        try:
            # ty: `gssapi` is the `kerberos` extra, absent from a default install
            # and from CI by design - see the module docstring. The import is
            # inside the `try` for the same reason, and the `except` below is
            # what a deployment missing the extra actually gets.
            import gssapi  # ty: ignore[unresolved-import]
            from gssapi.exceptions import GSSError  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise ConfigurationError(message=MISSING_EXTRA) from exc

        try:
            name = (
                gssapi.Name(self._service_principal, gssapi.NameType.kerberos_principal)
                if self._service_principal
                else None
            )
            credentials = gssapi.Credentials(
                name=name,
                usage="accept",
                store={"keytab": self._keytab} if self._keytab else None,
            )
            context = gssapi.SecurityContext(creds=credentials, usage="accept")
            response_token = context.step(token)
        except GSSError as exc:
            # The library's own text names principals and realms; the log keeps
            # it for the operator and the visitor gets one sentence.
            logger.warning("kerberos_ticket_rejected", extra={"reason": str(exc)})
            raise TicketRejected() from exc
        if not context.complete:
            logger.warning("kerberos_ticket_incomplete")
            raise TicketRejected()
        return AcceptedTicket(principal=str(context.initiator_name), response_token=response_token)
