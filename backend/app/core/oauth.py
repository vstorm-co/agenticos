"""The identity providers this deployment can sign somebody in with.

Two, and they are the same protocol. `google` is registered unconditionally
because its discovery document is a constant and the button is hidden by the
frontend's own `OAUTH_PROVIDERS`; `oidc` is a *generic* OpenID Connect provider
the deployment points at its own issuer - Entra ID, Okta, Keycloak - and is
registered only when one is configured, so an unset issuer answers 404 rather
than redirecting a browser at an empty URL (#1419).

Discovery is the whole of the configuration. A deployment gives the issuer and
the client pair; the authorization, token, userinfo and JWKS endpoints come from
`<issuer>/.well-known/openid-configuration`, which is the document the provider
itself keeps correct across a key rotation or an endpoint move.

The generic client asks for PKCE. Authlib adds the challenge and remembers the
verifier in the same session cookie it keeps `state` in, so an authorization code
intercepted between the provider and this callback is useless without the
browser that started the flow. Google is deliberately left as it was: its client
is a confidential one whose secret this server holds, and changing a working
sign-in is not this issue's to do.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings
from app.core.exceptions import NotFoundError

#: The provider a route may name. Not every one is configured - `sign_in_client`
#: answers that - but a name outside this tuple never reaches authlib at all.
SIGN_IN_PROVIDERS: tuple[str, ...] = ("google", "oidc")

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

#: The OIDC client, rebuilt when the configuration behind it changes.
#:
#: Built on first use rather than at import, because authlib fetches the
#: discovery document through the client and a deployment with no issuer set
#: should never have one to fetch. Keyed on the configuration so that changing
#: the issuer in a test gets a new client, while an unchanged one keeps the
#: metadata and the JWKS authlib has already cached on it.
_oidc_client: tuple[tuple[str, str], Any] | None = None


def _oidc() -> Any | None:
    """This deployment's generic OIDC client, or None if none is configured."""
    global _oidc_client
    issuer, client_id = settings.OIDC_ISSUER.rstrip("/"), settings.OIDC_CLIENT_ID
    if not issuer or not client_id:
        return None
    if _oidc_client is None or _oidc_client[0] != (issuer, client_id):
        _oidc_client = (
            (issuer, client_id),
            oauth.register(
                name="oidc",
                client_id=client_id,
                client_secret=settings.OIDC_CLIENT_SECRET,
                server_metadata_url=f"{issuer}/.well-known/openid-configuration",
                client_kwargs={
                    "scope": settings.OIDC_SCOPES,
                    # PKCE. Authlib puts the challenge on the authorization
                    # request and the verifier in the same session cookie it
                    # keeps `state` in, so an authorization code intercepted
                    # between the provider and this callback is useless without
                    # the browser that started the flow.
                    "code_challenge_method": "S256",
                },
            ),
        )
    return _oidc_client[1]


def sign_in_client(provider: str) -> Any:
    """The authlib client for `provider`, or a refusal naming nothing useful.

    Args:
        provider: The name in the request path.

    Returns:
        The registered client, ready to start or finish a round trip.

    Raises:
        NotFoundError: The provider is not one this deployment offers - either
            not a name it knows or one nobody configured. The two are answered
            identically and with no detail: the sign-in page is public, and which
            identity provider a company runs is not a fact a stranger gets to
            enumerate by guessing paths.
    """
    client = _oidc() if provider == "oidc" else oauth.google if provider == "google" else None
    if client is None:
        raise NotFoundError(message="Unknown sign-in provider")
    return client


def redirect_uri_for(provider: str) -> str:
    """Where the provider sends the browser back, as registered with it.

    A setting rather than `request.url_for`: the value has to match the one
    registered at the provider exactly, and a deployment behind a proxy that
    rewrites the scheme or the host would otherwise build a URI the provider
    refuses.
    """
    return settings.GOOGLE_REDIRECT_URI if provider == "google" else settings.OIDC_REDIRECT_URI


#: The claims a provider may use to say an address is confirmed.
#:
#: `email_verified` is the standard one. `xms_edov` is Microsoft Entra ID's,
#: which is what its v2 tokens carry instead - Entra does not emit
#: `email_verified` at all, so requiring only the standard name would reject
#: every Entra account on a deployment that had configured Entra exactly as
#: documented. It is an *optional* claim there, enabled on the app registration;
#: an Entra tenant that has not enabled it sends neither, and neither is
#: believed. `OIDC_VERIFIED_CLAIM` adds a third for a provider that names it
#: something else again.
_VERIFIED_CLAIMS: tuple[str, ...] = ("email_verified", "xms_edov")

#: What a provider may send as "yes" for one of those claims.
#:
#: A boolean is what the specification says; Entra has shipped `xms_edov` as the
#: string `"true"` in places, and a claim that arrives as a string is still the
#: provider saying yes. Anything else - absent, false, `"0"` - is not. `True` and
#: `1` are the same value in Python, so the boolean covers both.
_AFFIRMATIVE: frozenset[object] = frozenset({True, "true", "True", "1"})


def verification_claim_names() -> tuple[str, ...]:
    """Every claim this deployment accepts as "the address is confirmed"."""
    if settings.OIDC_VERIFIED_CLAIM:
        return (*_VERIFIED_CLAIMS, settings.OIDC_VERIFIED_CLAIM)
    return _VERIFIED_CLAIMS


def _is_verified(userinfo: Mapping[str, object]) -> bool:
    """Whether some claim this provider sends confirms the address.

    One true claim is enough and no claim is not. Absent counts as unverified
    deliberately: a provider that lets somebody set an address nobody confirmed
    is a provider on which anybody can claim anybody's work address, and the
    sign-up policy's domain allow-list is built on an address meaning something.
    """
    names = (
        (*_VERIFIED_CLAIMS, settings.OIDC_VERIFIED_CLAIM)
        if settings.OIDC_VERIFIED_CLAIM
        else _VERIFIED_CLAIMS
    )
    return any(userinfo.get(name) in _AFFIRMATIVE for name in names)


def verified_identity(userinfo: Mapping[str, object] | None) -> tuple[str, str, str | None] | None:
    """The `(subject, email, name)` this token vouches for, or None to refuse.

    Three conditions, and all three are the provider's own claims rather than
    anything this server can check afterwards:

    - a `sub`, because it is the only stable identifier. An email changes when
      somebody marries or a domain is bought, and matching on it alone would
      hand the next holder of an address the previous holder's account.
    - an `email`, because the account, the invitation and the sign-up policy are
      all keyed on one.
    - a verification claim, **required rather than merely believed**. See
      `_is_verified` for which claims count and why absent is not one.

    Args:
        userinfo: The claims off the token, or None where the exchange returned
            none and the userinfo endpoint had nothing to add.

    Returns:
        The identity to sign in, or None where any condition fails. The caller
        turns that into one sentence for the visitor; which of the three failed
        is in the log, not in the redirect.
    """
    if not userinfo:
        return None
    subject = userinfo.get("sub")
    email = userinfo.get("email")
    if not isinstance(subject, str) or not isinstance(email, str) or not subject or not email:
        return None
    if not _is_verified(userinfo):
        return None
    name = userinfo.get("name")
    return subject, email, name if isinstance(name, str) else None


def identity_key(provider: str, subject: str) -> str:
    """The stored `oauth_id` for this subject, namespaced where it has to be.

    An OIDC `sub` is unique **within its issuer** and nowhere else, so storing a
    bare one under a single `oidc` provider name means that pointing the
    deployment at a different tenant, realm or provider can collide with a
    subject issued by the old one - and `get_or_create_oauth_user` matches on the
    pair before it ever looks at the address, so the new principal would be
    signed into the old one's account. The issuer goes in the key.

    `google` keeps its bare subject: its issuer is a constant, and rewriting the
    key would orphan every account that has signed in with it.
    """
    if provider != "oidc":
        return subject
    return f"{settings.OIDC_ISSUER.rstrip('/')}#{subject}"
