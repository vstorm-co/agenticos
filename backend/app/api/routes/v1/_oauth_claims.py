"""Where a provider actually keeps the claims this sign-in needs.

Authlib parses the ID token into `token["userinfo"]` when `openid` is in scope,
and for Google that is the whole story. It is not the whole story in general: an
OIDC provider is entitled to keep `email` and `email_verified` at its UserInfo
endpoint and put neither in the ID token, and a callback reading only the parsed
token rejects such a provider for supplying nothing - having been given a valid,
verified identity one request away.

So the ID token's claims are used when they are sufficient, and the discovered
UserInfo endpoint is asked when they are not. Asked *second* rather than always:
it is a network round trip per sign-in, and the providers that need it are the
minority.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: What has to be present before the UserInfo endpoint can be skipped.
_SUFFICIENT = ("sub", "email")


async def claims_for(client: Any, token: dict[str, Any]) -> dict[str, Any] | None:
    """The claims to judge this sign-in on, from the ID token or UserInfo.

    Args:
        client: The authlib client the round trip was made with.
        token: What `authorize_access_token` returned.

    Returns:
        The merged claims, or None where neither source produced any. UserInfo is
        merged *over* the ID token: where both carry a claim, the endpoint the
        provider directs profile reads at is the one that is current.
    """
    parsed: dict[str, Any] = dict(token.get("userinfo") or {})
    if all(parsed.get(name) for name in _SUFFICIENT) and _says_verified(parsed):
        return parsed

    try:
        fetched = await client.userinfo(token=token)
    except Exception:
        # Not fatal on its own: the ID token may still carry enough, and the
        # caller refuses on the claims rather than on the fetch.
        logger.warning("oauth_userinfo_fetch_failed", exc_info=True)
        return parsed or None
    return {**parsed, **dict(fetched or {})} or None


def _says_verified(claims: dict[str, Any]) -> bool:
    """Whether some verification claim is present at all - not whether it is true.

    A present `email_verified: false` is an answer, and fetching UserInfo would
    not change it. An absent one is the case worth a round trip.
    """
    from app.core.oauth import verification_claim_names

    return any(name in claims for name in verification_claim_names())
