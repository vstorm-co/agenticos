"""Portal adapters: the base's manual fallback, the registry, and GitHub's hooks.

The GitHub calls are mocked at `httpx.AsyncClient` (the pattern the web-search and
mattermost tests use), so these assert the adapter's own logic - which repos it
keeps, what it sends, and that a non-201 falls back to forbidden rather than
inventing a hook - not GitHub's behaviour.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.services.portals import get_adapter
from app.services.portals.base import PortalAdapter, PortalTarget, RegisteredWebhook
from app.services.portals.exceptions import (
    WebhookRegistrationForbidden,
    WebhookRegistrationUnavailable,
)
from app.services.portals.github import GitHubPortalAdapter

pytestmark = pytest.mark.anyio


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """An async-context httpx stand-in returning one canned response per verb."""

    def __init__(self, response: _Resp, calls: list[tuple[str, str]]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **_kw: Any) -> _Resp:
        self._calls.append(("GET", url))
        return self._response

    async def post(self, url: str, **_kw: Any) -> _Resp:
        self._calls.append(("POST", url))
        return self._response

    async def delete(self, url: str, **_kw: Any) -> _Resp:
        self._calls.append(("DELETE", url))
        return self._response


def _patch_client(response: _Resp, calls: list[tuple[str, str]]):
    return patch("httpx.AsyncClient", lambda **_kw: _FakeClient(response, calls))


class TestTheBaseIsManualByDefault:
    async def test_registering_is_unavailable_unless_an_adapter_overrides_it(self) -> None:
        with pytest.raises(WebhookRegistrationUnavailable):
            await PortalAdapter().register_webhook(
                access_token="t", target=None, webhook_url="u", secret="s"
            )

    async def test_deleting_is_a_no_op(self) -> None:
        assert (
            await PortalAdapter().delete_webhook(
                access_token="t", target=None, provider_webhook_id="1"
            )
            is None
        )

    async def test_listing_targets_is_empty(self) -> None:
        assert await PortalAdapter().list_preset_targets(access_token="t") == []


class TestTheRegistry:
    def test_github_resolves_and_the_unknown_does_not(self) -> None:
        assert isinstance(get_adapter("github"), GitHubPortalAdapter)
        assert get_adapter("no-such-portal") is None


class TestTheGithubAdapter:
    async def test_only_repos_the_account_can_admin_are_offered(self) -> None:
        calls: list[tuple[str, str]] = []
        payload = [
            {"full_name": "acme/api", "permissions": {"admin": True}},
            {"full_name": "acme/read-only", "permissions": {"admin": False}},
            {"full_name": "acme/no-perms"},
        ]
        with _patch_client(_Resp(200, payload), calls):
            targets = await GitHubPortalAdapter().list_preset_targets(access_token="t")
        assert targets == [PortalTarget(id="acme/api", label="acme/api")]
        assert calls == [("GET", "/user/repos")]

    async def test_a_failed_listing_is_empty_not_an_error(self) -> None:
        with _patch_client(_Resp(401), []):
            assert await GitHubPortalAdapter().list_preset_targets(access_token="t") == []

    async def test_a_created_hook_returns_its_provider_id(self) -> None:
        calls: list[tuple[str, str]] = []
        with _patch_client(_Resp(201, {"id": 987654}), calls):
            result = await GitHubPortalAdapter().register_webhook(
                access_token="t", target="acme/api", webhook_url="https://x/hook", secret="sec"
            )
        assert result == RegisteredWebhook(provider_webhook_id="987654")
        assert calls == [("POST", "/repos/acme/api/hooks")]

    async def test_registering_without_a_repository_is_forbidden(self) -> None:
        with pytest.raises(WebhookRegistrationForbidden):
            await GitHubPortalAdapter().register_webhook(
                access_token="t", target=None, webhook_url="https://x/hook", secret="sec"
            )

    async def test_a_rejected_registration_falls_back_to_forbidden(self) -> None:
        with _patch_client(_Resp(403), []), pytest.raises(WebhookRegistrationForbidden):
            await GitHubPortalAdapter().register_webhook(
                access_token="t", target="acme/api", webhook_url="https://x/hook", secret="s"
            )

    async def test_delete_removes_the_hook_when_there_is_a_target(self) -> None:
        calls: list[tuple[str, str]] = []
        with _patch_client(_Resp(204), calls):
            await GitHubPortalAdapter().delete_webhook(
                access_token="t", target="acme/api", provider_webhook_id="987654"
            )
        assert calls == [("DELETE", "/repos/acme/api/hooks/987654")]

    async def test_delete_without_a_target_does_nothing(self) -> None:
        calls: list[tuple[str, str]] = []
        with _patch_client(_Resp(204), calls):
            await GitHubPortalAdapter().delete_webhook(
                access_token="t", target=None, provider_webhook_id="987654"
            )
        assert calls == []
