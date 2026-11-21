"""Quota metadata uses fixed provider URLs and never returns token-bearing data."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.subscription_gateway import _usage
from app.subscription_gateway._instances import GatewayError, Instance

pytestmark = pytest.mark.anyio


def instance() -> Instance:
    return Instance(
        "scope", 1234, "client-key", "management-key", MagicMock(spec=asyncio.subprocess.Process), 0
    )


async def test_antigravity_groups_preserve_weekly_daily_and_hourly_limits() -> None:
    requests: list[httpx.Request] = []

    async def send(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        call = json.loads(request.content)
        assert request.url.host == "127.0.0.1"
        assert request.headers["Authorization"] == "Bearer management-key"
        assert call["auth_index"] == "my-account"
        assert call["header"]["Authorization"] == "Bearer $TOKEN$"
        if len(requests) == 1:
            assert call["url"] == "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
            body = {"cloudaicompanionProject": "project"}
        else:
            assert (
                call["url"]
                == "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
            )
            assert json.loads(call["data"]) == {"project": "project"}
            body = {
                "groups": [
                    {
                        "displayName": "Gemini",
                        "buckets": [
                            {
                                "window": "weekly",
                                "remainingFraction": 0.39,
                                "resetTime": "2099-01-01T00:00:00Z",
                            },
                            {"displayName": "5-hour", "remainingFraction": 0.5},
                            {"window": "daily", "remainingFraction": 0.2},
                            {"window": "custom", "remainingFraction": 0},
                            {"remainingFraction": 0.8},
                            {"remainingFraction": 0.5, "disabled": True},
                            {"resetTime": "2099-01-01T00:00:00Z"},
                        ],
                    }
                ]
            }
        return httpx.Response(200, json={"status_code": 200, "body": json.dumps(body)})

    client_class = httpx.AsyncClient
    with patch.object(
        _usage.httpx,
        "AsyncClient",
        side_effect=lambda **_kwargs: client_class(transport=httpx.MockTransport(send)),
    ):
        result = await _usage.antigravity_usage(instance(), "my-account")
    assert result.status == "available"
    assert [window.duration_minutes for window in result.windows] == [10080, 300, 1440, None, None]
    assert result.windows[0].remaining_percent == 39
    assert len(result.windows) == 5
    assert "TOKEN" not in result.model_dump_json()
    assert len(requests) == 2


@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, "unavailable"),
        ({"groups": []}, "unavailable"),
        ({"groups": [{"buckets": [{"remainingFraction": 0.1}]}]}, "available"),
        (
            {
                "groups": [
                    {"buckets": [{"remainingFraction": 0.2, "resetTime": "2000-01-01T00:00:00Z"}]}
                ]
            },
            "stale",
        ),
    ],
)
async def test_no_project_empty_labels_and_expired_windows_are_explicit(
    body: dict[str, object],
    expected: str,
) -> None:
    async def send(request: httpx.Request) -> httpx.Response:
        call = json.loads(request.content)
        payload = (
            ({"cloudaicompanionProject": "p"} if body else {})
            if "loadCodeAssist" in call["url"]
            else body
        )
        return httpx.Response(200, json={"status_code": 200, "body": json.dumps(payload)})

    client_class = httpx.AsyncClient
    with patch.object(
        _usage.httpx,
        "AsyncClient",
        side_effect=lambda **_kwargs: client_class(transport=httpx.MockTransport(send)),
    ):
        result = await _usage.antigravity_usage(instance(), "a")
    assert result.status == expected
    if result.windows:
        assert result.windows[0].label is None


@pytest.mark.parametrize("failure", ["http", "provider", "json", "shape", "transport"])
async def test_quota_failures_do_not_return_provider_bodies_or_tokens(failure: str) -> None:
    async def send(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError("private-token", request=request)
        if failure == "http":
            return httpx.Response(500, text="private-token")
        return httpx.Response(
            200,
            json={
                "status_code": 403 if failure == "provider" else 200,
                "body": "private-token" if failure == "json" else "[]",
            },
        )

    client_class = httpx.AsyncClient
    with (
        patch.object(
            _usage.httpx,
            "AsyncClient",
            side_effect=lambda **_kwargs: client_class(transport=httpx.MockTransport(send)),
        ),
        pytest.raises(GatewayError) as error,
    ):
        await _usage.antigravity_usage(instance(), "a")
    assert error.value.status == 502
    assert "private-token" not in str(error.value)


def test_provider_window_duration_names() -> None:
    assert _usage._duration("0 hour") is None
    assert _usage._duration("2 hours") == 120


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 64,
                        "limit_window_seconds": 604800,
                        "reset_at": 4000000000,
                    },
                    "secondary_window": {"used_percent": 0, "limit_window_seconds": 0},
                }
            },
            "available",
        ),
        ({}, "unavailable"),
        ({"rate_limit": {"primary_window": {"used_percent": 0}}}, "available"),
        ({"rate_limit": {"primary_window": {"used_percent": 80, "reset_at": 1}}}, "stale"),
        (
            {
                "rate_limit": {
                    "primary_window": {},
                    "secondary_window": {"used_percent": 0, "limit_window_seconds": 0},
                }
            },
            "unavailable",
        ),
    ],
)
async def test_codex_live_usage_does_not_require_an_inference_response(
    payload: dict[str, object], expected: str
) -> None:
    async def send(request: httpx.Request) -> httpx.Response:
        call = json.loads(request.content)
        assert call["method"] == "GET"
        assert call["url"] == "https://chatgpt.com/backend-api/wham/usage"
        assert call["header"]["ChatGPT-Account-Id"] == "my-account"
        assert call["data"] == ""
        return httpx.Response(200, json={"status_code": 200, "body": json.dumps(payload)})

    client_class = httpx.AsyncClient
    with patch.object(
        _usage.httpx,
        "AsyncClient",
        side_effect=lambda **_kwargs: client_class(transport=httpx.MockTransport(send)),
    ):
        result = await _usage.codex_usage(instance(), "credential", "my-account")
    assert result.status == expected
    if result.windows and result.windows[0].duration_minutes == 10080:
        assert result.windows[0].remaining_percent == 36
        assert len(result.windows) == 1


async def test_codex_live_usage_refuses_malformed_provider_data() -> None:
    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status_code": 200, "body": "private-token"})
    )
    with (
        patch.object(
            _usage.httpx,
            "AsyncClient",
            side_effect=lambda **_kwargs: client_class(transport=transport),
        ),
        pytest.raises(GatewayError, match="could not be read"),
    ):
        await _usage.codex_usage(instance(), "credential", "account")
