"""Trusted broker transport; credentials stay in the existing owner-bound Vault.

The origin is deployment configuration, never model/user input. Every request is
DNS-pinned, TLS-verified and refuses redirects. Only native account OAuth uses it.
"""

from collections.abc import Mapping
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
from mcp.shared.auth import OAuthToken
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from app.agents.mcp_oauth import McpOAuthPayload, OAuthError, OAuthGrantRevoked
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError


class BridgeStart(BaseModel):
    authorization_url: str
    client_id: str


class BridgeGrant(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_in: int | None = None
    scope: str | None = None
    receipt: SecretStr | None = None

    def token(self) -> OAuthToken:
        return OAuthToken(
            access_token=self.access_token.get_secret_value(),
            refresh_token=self.refresh_token.get_secret_value() if self.refresh_token else None,
            expires_in=self.expires_in,
            scope=self.scope,
        )


class BridgeProvider(BaseModel):
    provider: str
    configured: bool
    deployment_allowed: bool
    client_id: str | None = None


class BridgeFailure(BaseModel):
    error: str


async def _request(path: str, data: Mapping[str, str | list[str]] | None = None) -> bytes:
    if not settings.OAUTH_BRIDGE_URL:
        raise OAuthError("AgenticOS account connection is disabled on this deployment")
    try:
        async with (
            PinnedAsyncClient(timeout=httpx2.Timeout(15 if data is not None else 3)) as client,
            client.stream(
                "POST" if data is not None else "GET", settings.OAUTH_BRIDGE_URL + path, json=data
            ) as response,
        ):
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise OAuthError("The account bridge returned an invalid response")
            if not response.is_success:
                try:
                    failure = BridgeFailure.model_validate_json(body)
                except ValidationError:
                    raise OAuthError("The account bridge refused this request") from None
                if failure.error in {
                    "invalid_ticket",
                    "invalid_proof",
                    "provider_grant_revoked",
                }:
                    raise OAuthGrantRevoked("Reconnect this account through AgenticOS")
                raise OAuthError("The account bridge could not complete this request")
            return bytes(body)
    except httpx2.HTTPError, UrlRefusedError:
        raise OAuthError("The account bridge is unavailable; try your own credentials") from None


async def status(provider: str) -> Literal["disabled", "unavailable", "unconfigured", "ready"]:
    if not settings.OAUTH_BRIDGE_URL:
        return "disabled"
    try:
        origin = settings.FRONTEND_URL.rstrip("/")
        providers = TypeAdapter(list[BridgeProvider]).validate_json(
            await _request("/v1/providers?" + urlencode({"origin": origin}))
        )
    except OAuthError, ValidationError:
        return "unavailable"
    return (
        "ready"
        if any(p.provider == provider and p.configured and p.deployment_allowed for p in providers)
        else "unconfigured"
    )


async def start(
    *, provider: str, redirect_uri: str, state: str, scopes: list[str], challenge: str
) -> BridgeStart:
    try:
        result = BridgeStart.model_validate_json(
            await _request(
                "/v1/oauth/start",
                {
                    "provider": provider,
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "scopes": scopes,
                    "code_challenge": challenge,
                },
            )
        )
    except ValidationError:
        raise OAuthError("The account bridge returned an invalid consent response") from None
    # The broker may return only the intended provider consent endpoint, never
    # an arbitrary browser redirect or a URL carrying a different client identity.
    url = urlsplit(result.authorization_url)
    expected = {
        "google": ("accounts.google.com", "/o/oauth2/v2/auth"),
        "microsoft": ("login.microsoftonline.com", "/common/oauth2/v2.0/authorize"),
        "slack": ("slack.com", "/oauth/v2/authorize"),
    }.get(provider)
    params = parse_qs(url.query)
    if (
        url.scheme != "https"
        or expected != (url.netloc, url.path)
        or url.fragment
        or params.get("client_id") != [result.client_id]
        or params.get("redirect_uri")
        != [settings.OAUTH_BRIDGE_URL + "/v1/oauth/callback/" + provider]
        or params.get("response_type") != ["code"]
        or not params.get("state")
        or (
            provider != "slack"
            and (
                params.get("code_challenge") != [challenge]
                or params.get("code_challenge_method") != ["S256"]
                or params.get("scope") != [" ".join(scopes)]
            )
        )
        or (provider == "slack" and params.get("user_scope") != [",".join(scopes)])
    ):
        raise OAuthError("The account bridge returned an unexpected consent destination")
    return result


async def token(payload: McpOAuthPayload, *, code: str | None = None) -> BridgeGrant:
    if not payload.bridge_url or payload.bridge_url != settings.OAUTH_BRIDGE_URL:
        raise OAuthGrantRevoked("The account bridge changed; reconnect this account")
    if code is not None:
        if not payload.code_verifier:
            raise OAuthError("Restart this account connection")
        path = "/v1/oauth/token"
        data = {
            "provider": payload.provider or "",
            "ticket": code,
            "code_verifier": payload.code_verifier,
        }
    else:
        if not payload.refresh_token or not payload.bridge_receipt:
            raise OAuthGrantRevoked("Reconnect this account through AgenticOS")
        path = "/v1/oauth/refresh"
        data = {
            "provider": payload.provider or "",
            "receipt": payload.bridge_receipt.get_secret_value(),
            "refresh_token": payload.refresh_token.get_secret_value(),
        }
    try:
        result = BridgeGrant.model_validate_json(await _request(path, data))
    except ValidationError:
        raise OAuthError("The account bridge returned an invalid token response") from None
    if result.refresh_token and not result.receipt:
        raise OAuthError("The account bridge returned an incomplete token response")
    return result
