"""Slack user OAuth uses authed_user tokens, never the installation's bot token."""

from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.agents.mcp_oauth import OAuthError

AUTHORIZE_ENDPOINT = "https://slack.com/oauth/v2/authorize"
TOKEN_ENDPOINT = "https://slack.com/api/oauth.v2.access"


class SlackToken(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_in: int | None = None
    scope: str = ""


class SlackResponse(BaseModel):
    ok: bool
    authed_user: SlackToken | None = None


def authorization_url(*, client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    return (
        AUTHORIZE_ENDPOINT
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "user_scope": ",".join(scopes),
                "state": state,
            }
        )
    )


async def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> SlackToken:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        if not response.is_success:
            raise OAuthError("Slack refused the connection request")
        parsed = SlackResponse.model_validate_json(response.content)
    except httpx.HTTPError, ValidationError:
        raise OAuthError("Slack could not complete the connection") from None
    if not parsed.ok or parsed.authed_user is None:
        raise OAuthError("Slack did not grant a user token; check the app's user scopes")
    return parsed.authed_user


class SlackIdentity(BaseModel):
    ok: bool
    team: str = ""
    team_id: str = ""
    user: str = ""
    user_id: str = ""


async def identify(token: SecretStr) -> tuple[str, list[str]]:
    """Validate a pasted token and return its workspace label and actual scopes."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            )
        if not response.is_success:
            raise OAuthError("Slack refused this token")
        identity = SlackIdentity.model_validate_json(response.content)
    except httpx.HTTPError, ValidationError:
        raise OAuthError("Slack could not validate this token") from None
    if not identity.ok or not identity.team_id or not identity.user_id:
        raise OAuthError("Slack refused this token")
    scopes = [
        scope.strip()
        for scope in response.headers.get("x-oauth-scopes", "").split(",")
        if scope.strip()
    ]
    return f"{identity.team or identity.team_id} / {identity.user or identity.user_id}", scopes
