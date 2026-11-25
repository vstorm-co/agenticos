"""Configured identity providers; names only, never their client credentials."""

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.core.config import Settings

SignInProvider = Literal["google", "oidc", "ldap", "kerberos"]


def configured_sign_in_providers(config: Settings) -> list[SignInProvider]:
    providers: list[SignInProvider] = []
    if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
        providers.append("google")
    if config.OIDC_ISSUER and config.OIDC_CLIENT_ID:
        providers.append("oidc")
    if config.LDAP_URL:
        providers.append("ldap")
        if config.KERBEROS_ENABLED:
            providers.append("kerberos")
    return providers
