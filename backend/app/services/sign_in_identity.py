"""Normalize GitHub's OAuth identity without trusting its public email field.

GitHub is not an OIDC provider. Only its authenticated email endpoint can attest
that the primary address is verified. Provider tokens are used transiently and
never stored: the caller issues an ordinary AgenticOS session afterwards.
"""

from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, ValidationError

from app.core.exceptions import AuthenticationError


class _Profile(BaseModel):
    model_config = ConfigDict(strict=True)

    id: Annotated[int, Field(gt=0)]
    name: str | None = None


class _Email(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr
    primary: bool
    verified: bool


_EMAILS = TypeAdapter(list[_Email])


async def github_claims(access_token: object) -> dict[str, object] | None:
    """Return a stable subject and verified primary email, or refuse the identity.

    Requests use fixed GitHub endpoints, bounded timeouts and no redirects.
    Missing primary/verified email refuses sign-in rather than choosing another
    address which may lead to a different local account.
    """
    if not isinstance(access_token, str) or not access_token:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        ) as client:
            profile_response = await client.get("https://api.github.com/user")
            profile_response.raise_for_status()
            profile = _Profile.model_validate_json(profile_response.content)
            email_response = await client.get(
                "https://api.github.com/user/emails", params={"per_page": 100}
            )
            email_response.raise_for_status()
            emails = _EMAILS.validate_json(email_response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        raise AuthenticationError(
            message="GitHub could not verify your sign-in. Try again."
        ) from exc
    primary = next((email for email in emails if email.primary and email.verified), None)
    if primary is None:
        return None
    return {
        "sub": str(profile.id),
        "email": str(primary.email),
        "email_verified": True,
        "name": profile.name,
    }
