"""Signing in with a company directory, and letting it decide who belongs where.

The public surface of the package (#1773):

- `DirectorySignInService` - an LDAP password or a Kerberos ticket in, an
  account out, with memberships reconciled on the way.
- `DirectorySyncService` - that reconciliation on its own, for the OIDC callback,
  whose identity provider reports groups too.
- `DirectoryMappingService` - an organization's mappings from directory groups to
  roles and groups.
- `build_directory` / `build_ticket_acceptor` - the adapters the deployment's
  settings describe, for the composition root to inject.

The adapters and the contract they satisfy are package-internal; everything else
reaches a directory through the services.
"""

from app.core.config import Settings
from app.services.directory.contract import Directory, TicketAcceptor
from app.services.directory.kerberos import GssapiTicketAcceptor
from app.services.directory.ldap_directory import LdapConfig, LdapDirectory
from app.services.directory.mappings import DirectoryMappingService
from app.services.directory.sign_in import DirectorySignInService
from app.services.directory.sync import DirectorySyncService


def build_directory(settings: Settings) -> Directory | None:
    """The configured directory, or None when `LDAP_URL` is unset."""
    config = LdapConfig.from_settings(settings)
    return LdapDirectory(config) if config is not None else None


def build_ticket_acceptor(settings: Settings) -> TicketAcceptor | None:
    """The Kerberos ticket acceptor, or None when Kerberos sign-in is off."""
    if not settings.KERBEROS_ENABLED:
        return None
    return GssapiTicketAcceptor(
        keytab=settings.KERBEROS_KEYTAB or None,
        service_principal=settings.KERBEROS_SERVICE_PRINCIPAL or None,
    )


__all__ = [
    "DirectoryMappingService",
    "DirectorySignInService",
    "DirectorySyncService",
    "build_directory",
    "build_ticket_acceptor",
]
