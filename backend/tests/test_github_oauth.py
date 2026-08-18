"""GitHub's OAuth App flow: the consent URL it builds and the token exchange.

The HTTP call is mocked at `httpx.AsyncClient` (the pattern `test_portals.py` and
the web-search tests use), so these assert this module's own logic - what it sends
GitHub, and how it reads what GitHub sends back, including the quirks a classic
OAuth App has - not GitHub's behaviour.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.services.portals import github_oauth

pytestmark = pytest.mark.anyio


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """An async-context httpx stand-in that records the one POST it is sent."""

    def __init__(self, response: _Resp, calls: list[dict[str, Any]]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self._calls.append({"url": url, **kwargs})
        return self._response


def _patch_client(response: _Resp, calls: list[dict[str, Any]]):
    return patch("httpx.AsyncClient", lambda **_kw: _FakeClient(response, calls))


class TestTheConsentUrl:
    def test_it_carries_the_client_id_scopes_state_and_redirect(self) -> None:
        url = github_oauth.authorization_url(
            client_id="Iv1.abc",
            redirect_uri="https://app/api/me/mcp-connections/oauth/callback",
            scopes=["repo", "admin:repo_hook"],
            state="the-state",
        )
        assert url.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=Iv1.abc" in url
        # Space-joined scope, url-encoded: "repo admin:repo_hook".
        assert "scope=repo+admin%3Arepo_hook" in url
        assert "state=the-state" in url
        assert "redirect_uri=https%3A%2F%2Fapp" in url

    def test_it_disables_signup_so_no_new_account_is_offered(self) -> None:
        url = github_oauth.authorization_url(
            client_id="cid", redirect_uri="https://app/cb", scopes=["repo"], state="s"
        )
        assert "allow_signup=false" in url


class TestTheTokenExchange:
    async def test_it_asks_for_json_and_posts_the_credentials_and_code(self) -> None:
        calls: list[dict[str, Any]] = []
        payload = {"access_token": "gho_x", "token_type": "bearer", "scope": "repo,admin:repo_hook"}
        with _patch_client(_Resp(200, payload), calls):
            token = await github_oauth.exchange_code(
                client_id="cid",
                client_secret="csecret",
                code="the-code",
                redirect_uri="https://app/cb",
            )
        assert token.access_token == "gho_x"
        # The comma-separated scope becomes the granted list.
        assert token.granted_scopes == ["repo", "admin:repo_hook"]

        sent = calls[0]
        assert sent["url"] == github_oauth.TOKEN_ENDPOINT
        # Without this header GitHub answers form-encoded and `.json()` breaks.
        assert sent["headers"]["Accept"] == "application/json"
        assert sent["data"] == {
            "client_id": "cid",
            "client_secret": "csecret",
            "code": "the-code",
            "redirect_uri": "https://app/cb",
        }

    async def test_a_token_with_no_refresh_or_expiry_is_tolerated(self) -> None:
        """A classic OAuth App token has neither - the model must not require them."""
        calls: list[dict[str, Any]] = []
        with _patch_client(_Resp(200, {"access_token": "gho_x", "scope": "repo"}), calls):
            token = await github_oauth.exchange_code(
                client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
            )
        assert token == github_oauth.GithubToken(access_token="gho_x", granted_scopes=["repo"])

    async def test_a_missing_scope_string_yields_no_granted_scopes(self) -> None:
        calls: list[dict[str, Any]] = []
        with _patch_client(_Resp(200, {"access_token": "gho_x"}), calls):
            token = await github_oauth.exchange_code(
                client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
            )
        assert token.granted_scopes == []

    async def test_a_non_200_is_a_recoverable_error_without_the_body(self) -> None:
        with _patch_client(_Resp(500, "boom"), []), pytest.raises(github_oauth.GithubOAuthError):
            await github_oauth.exchange_code(
                client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
            )

    async def test_a_200_error_body_is_a_recoverable_error(self) -> None:
        """A bad or expired code is a 200 with an error payload, not a 4xx."""
        body = {"error": "bad_verification_code", "error_description": "the code expired"}
        with _patch_client(_Resp(200, body), []), pytest.raises(github_oauth.GithubOAuthError):
            await github_oauth.exchange_code(
                client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
            )

    async def test_a_200_without_a_token_is_a_recoverable_error(self) -> None:
        with (
            _patch_client(_Resp(200, {"scope": "repo"}), []),
            pytest.raises(github_oauth.GithubOAuthError),
        ):
            await github_oauth.exchange_code(
                client_id="cid", client_secret="cs", code="c", redirect_uri="https://app/cb"
            )
