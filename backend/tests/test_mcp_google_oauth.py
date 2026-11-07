"""Google's MCP consent must request refreshable access without changing other providers."""

import httpx2
import pytest
from mcp.shared.auth import OAuthMetadata

from app.agents.mcp_oauth import DiscoveredServer, authorization_url


@pytest.mark.parametrize(
    "scope", [None, "https://www.googleapis.com/auth/calendar", "openid offline_access"]
)
def test_google_consent_requests_offline_access_even_without_an_oidc_scope(
    scope: str | None,
) -> None:
    params = _consent("https://accounts.google.com/o/oauth2/v2/auth", scope)
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    assert params["state"] == "state"
    assert params["code_challenge"] == "challenge"
    assert params["code_challenge_method"] == "S256"
    assert params["resource"] == "https://calendarmcp.googleapis.com/mcp/v1"
    assert params.get("scope") == scope


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://login.microsoftonline.com/authorize",
        "https://accounts.google.com.example.org/authorize",
        "https://accounts.google.com@evil.example/authorize",
        "http://accounts.google.com/authorize",
        "https://accounts.google.com:8443/authorize",
    ],
)
def test_google_parameters_do_not_leak_to_other_authorization_origins(endpoint: str) -> None:
    params = _consent(endpoint, "read")
    assert "access_type" not in params
    assert "prompt" not in params


def _consent(endpoint: str, scope: str | None) -> httpx2.QueryParams:
    server = DiscoveredServer(
        authorization_endpoint=endpoint,
        token_endpoint="https://oauth2.googleapis.com/token",
        registration_endpoint=None,
        resource="https://calendarmcp.googleapis.com/mcp/v1",
        scope=scope,
        metadata=OAuthMetadata(
            issuer="https://accounts.google.com",
            authorization_endpoint=endpoint,
            token_endpoint="https://oauth2.googleapis.com/token",
            response_types_supported=["code"],
        ),
    )
    return httpx2.URL(
        authorization_url(
            server,
            client_id="client",
            redirect_uri="https://console.example/callback",
            state="state",
            code_challenge="challenge",
        )
    ).params
