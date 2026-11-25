"""Copilot remains a distinct model gateway with AgenticOS identity and account catalogs."""

import json
from unittest.mock import patch

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.models.github_copilot import GitHubCopilotModel
from pydantic_ai.providers.github_copilot import GitHubCopilotProvider

from app.agents.copilot import AgenticCopilotProvider
from app.agents.model_resolver import ResolvedCredential, build_model, get_provider
from app.clients.github_copilot import CopilotAccountClient, CopilotGrant, CopilotPending
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.services.model_catalog import models_for

pytestmark = pytest.mark.anyio


def test_copilot_is_distinct_from_github_models_and_never_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_COPILOT_API_KEY", "environment-account-token")
    monkeypatch.setenv("GH_TOKEN", "general-github-token")
    monkeypatch.setenv("GITHUB_TOKEN", "general-github-token")
    monkeypatch.setenv("GITHUB_COPILOT_BASE_URL", "https://unapproved.example")
    monkeypatch.setenv("GITHUB_COPILOT_INTEGRATION_ID", "vscode-chat")
    model = build_model(
        ResolvedCredential(provider="github_copilot", secret=ApiKeySecret(api_key="owner-token")),
        "plan-model",
    )
    assert isinstance(model, GitHubCopilotModel)
    assert isinstance(model._provider, GitHubCopilotProvider)
    assert model._provider.client.api_key == "owner-token"
    assert str(model._provider.client.base_url) == "https://api.githubcopilot.com"
    assert get_provider("github_copilot").id != get_provider("github").id
    with pytest.raises(BadRequestError, match="explicit account token"):
        build_model(ResolvedCredential(provider="github_copilot", secret=NoSecret()), "plan-model")


async def test_sdk_tool_round_trip_cannot_replace_agenticos_identity() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.url.host == "api.githubcopilot.com"
        assert request.headers["authorization"] == "Bearer owner-token"
        assert request.headers["copilot-integration-id"] == "agenticos"
        assert request.headers["user-agent"] == "AgenticOS"
        assert "x-api-key" not in request.headers and "api-key" not in request.headers
        assert (
            "editor-version" not in request.headers
            and "editor-plugin-version" not in request.headers
        )
        message = (
            {"role": "assistant", "content": "5"}
            if len(requests) > 1
            else {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "sum-1",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"a":2,"b":3}'},
                    }
                ],
            }
        )
        return httpx2.Response(
            200,
            json={
                "id": f"answer-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "plan-model",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "stop" if len(requests) > 1 else "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http,
        AgenticCopilotProvider("owner-token", http_client=http) as provider,
    ):
        agent = Agent(GitHubCopilotModel("plan-model", provider=provider))

        @agent.tool_plain
        def add(a: int, b: int) -> int:
            return a + b

        result = await agent.run(
            "Add two and three",
            model_settings={
                "extra_headers": {
                    "copilot-integration-id": "vscode-chat",
                    "editor-version": "vscode/1",
                    "editor-plugin-version": "copilot/1",
                    "User-Agent": "other-editor",
                    "Authorization": "Bearer somebody-else",
                    "x-api-key": "another-account",
                    "api-key": "another-account",
                }
            },
        )
        assert result.output == "5"
    assert len(requests) == 2
    sent = json.loads(requests[1].content)
    assert any(
        message.get("role") == "tool" and message["content"] == "5" for message in sent["messages"]
    )


async def test_catalog_has_only_account_supported_chat_endpoints_without_a_global_fallback() -> (
    None
):
    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/models"
        assert request.headers["authorization"] == "Bearer account-key"
        assert request.headers["copilot-integration-id"] == "agenticos"
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"id": "chat.id", "supported_endpoints": ["/chat/completions"]},
                    {"id": "responses-only", "supported_endpoints": ["/responses"]},
                    {"id": "unknown"},
                ]
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        client = CopilotAccountClient(http)
        models = await client.models("account-key")
        assert [model.id for model in models] == ["chat.id"]
        with patch("app.clients.github_copilot.CopilotAccountClient", return_value=client):
            listed, source = await models_for("github_copilot", api_key="account-key")
        assert [model.id for model in listed] == ["chat.id"] and source == "live"
    assert await models_for("github_copilot") == ([], "unlisted")
    with pytest.raises(ValueError, match=r"fixed GitHub\.com"):
        await models_for("github_copilot", api_key="account-key", base_url="https://other.example")


@pytest.mark.parametrize(
    "response",
    [
        {"error": "authorization_pending"},
        {"error": "slow_down", "interval": 12},
        {"access_token": "owner-token", "token_type": "bearer", "scope": ""},
    ],
)
async def test_device_poll_uses_only_the_caller_owned_application(
    response: dict[str, object],
) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://github.com/login/oauth/access_token"
        assert (
            b"client_id=our-client" in request.content
            and b"device_code=private-code" in request.content
        )
        return httpx2.Response(200, json=response)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        result = await CopilotAccountClient(http).poll(
            client_id="our-client", device_code="private-code"
        )
    assert isinstance(result, CopilotPending if "error" in response else CopilotGrant)


@pytest.mark.security
@pytest.mark.parametrize(
    "response",
    [
        {"error": "access_denied"},
        {"error": "expired_token"},
        {"error": "private_secret"},
        {
            "access_token": "owner-token",
            "token_type": "bearer",
            "refresh_token": "never-drop-refresh",
        },
        {"access_token": "owner-token", "token_type": "bearer", "expires_in": 60},
        {"access_token": "owner-token", "token_type": "bearer", "refresh_token_expires_in": 60},
        {"access_token": "sensitive", "token_type": "unexpected"},
    ],
)
async def test_denied_expiring_or_malformed_grants_are_refused_without_tokens_in_errors(
    response: dict[str, object],
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=response))
    ) as http:
        with pytest.raises(BadRequestError) as error:
            await CopilotAccountClient(http).poll(
                client_id="our-client", device_code="private-code"
            )
    assert all(
        secret not in str(error.value)
        for secret in ["owner-token", "never-drop-refresh", "sensitive", "private_secret"]
    )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_account_or_quota_refusal_returns_no_curated_catalog(status: int) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(status))
    ) as http:
        client = CopilotAccountClient(http)
        with pytest.raises(BadRequestError):
            await client.models("account-key")
        with patch("app.clients.github_copilot.CopilotAccountClient", return_value=client):
            assert await models_for("github_copilot", api_key="account-key") == ([], "unlisted")
        with pytest.raises(BadRequestError):
            await client.poll(client_id="our-client", device_code="private-code")


async def test_malformed_model_catalog_is_an_explicit_refusal() -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"data": [{"id": 3}]}))
    ) as http:
        with pytest.raises(BadRequestError, match="invalid model catalog"):
            await CopilotAccountClient(http).models("account-key")


@pytest.mark.security
@pytest.mark.parametrize("token", ["", "private\nheader", "private token", "secret-ł", "x" * 8193])
async def test_invalid_bearer_values_are_refused_before_http_and_never_echoed(token: str) -> None:
    with pytest.raises(BadRequestError) as error:
        AgenticCopilotProvider(token)
    assert not token or token not in str(error.value)
    with pytest.raises(BadRequestError):
        await CopilotAccountClient().models(token)


async def test_account_client_owns_only_the_http_client_it_creates() -> None:
    owned = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "own-model",
                            "name": "Own model",
                            "supported_endpoints": ["/chat/completions"],
                        }
                    ]
                },
            )
        )
    )
    with patch("app.clients.github_copilot.httpx2.AsyncClient", return_value=owned):
        assert (await CopilotAccountClient().models("own-token"))[0].name == "Own model"
    assert owned.is_closed


async def test_device_start_uses_our_app_and_handles_a_vendor_refusal() -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://github.com/login/device/code"
        assert b"client_id=our-client" in request.content
        return httpx2.Response(
            200,
            json={
                "device_code": "private-code",
                "user_code": "OWN-CODE",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        challenge = await CopilotAccountClient(http).start("our-client")
        assert challenge.user_code == "OWN-CODE"
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(403))
    ) as http:
        with pytest.raises(BadRequestError, match="could not start"):
            await CopilotAccountClient(http).start("our-client")


async def test_a_copilot_model_does_not_inherit_another_vendors_metered_price() -> None:
    from pydantic_ai.usage import RequestUsage

    from app.agents.capabilities.budget import _capability as budget

    with patch.object(budget, "calc_price", side_effect=LookupError("No Copilot price")) as prices:
        assert (
            budget.price_request(
                RequestUsage(input_tokens=100, output_tokens=10), "gpt-5.4", "github_copilot"
            )
            is None
        )
    prices.assert_not_called()


async def test_a_legacy_http_client_is_refused_explicitly_and_remains_caller_owned() -> None:
    import httpx

    async with AgenticCopilotProvider("own-token") as provider, httpx.AsyncClient() as legacy:
        with pytest.raises(TypeError, match="httpx2"):
            provider._create_openai_client(base_url=None, api_key="own-token", http_client=legacy)
        assert not legacy.is_closed


@pytest.mark.parametrize("payload", [[], {"unexpected": True}])
async def test_a_malformed_device_reply_cannot_be_treated_as_pending_or_connected(
    payload: object,
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as http:
        with pytest.raises(BadRequestError, match="invalid device token response"):
            await CopilotAccountClient(http).poll(client_id="own-app", device_code="private-device")


@pytest.mark.parametrize(
    "reported,expected",
    [
        (None, "github_copilot"),
        ("github-copilot", "github_copilot"),
        ("github_copilot", "github_copilot"),
        ("openai", "openai"),
        ("anthropic", "anthropic"),
    ],
)
@pytest.mark.parametrize(
    "provider",
    [
        "github_copilot",
        "kimi_code",
        "alibaba_coding_plan",
        "opencode_go",
        "ollama_cloud",
        "cliproxyapi",
        "subscription_accounts",
        "nous_portal",
        "chutes",
        "synthetic",
    ],
)
async def test_explicit_metered_fallback_is_priced_under_its_own_provider(
    reported: str | None, expected: str, provider: str
) -> None:
    from decimal import Decimal

    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage

    from app.agents.capabilities.budget import _capability as budget

    guard = budget.BudgetGuard(provider=provider)
    expected = provider if reported in {None, "github_copilot", "github-copilot"} else expected
    response = ModelResponse(
        parts=[TextPart("done")],
        model_name="billed-model",
        provider_name=reported,
        usage=RequestUsage(input_tokens=10, output_tokens=2),
    )
    with patch.object(budget, "price_request", return_value=Decimal("0.25")) as price:
        guard._record(response)
    assert price.call_args.args[-1] == expected
    assert guard.ledger.total_usd == Decimal("0.25")


async def test_unverified_copilot_cost_metadata_does_not_become_a_usd_bill() -> None:

    from pydantic_ai.usage import RequestUsage

    from app.agents.capabilities.budget import _capability as budget

    ledger = budget.SpendLedger()
    entry = ledger.record(
        "gpt-5.4",
        RequestUsage(input_tokens=10, output_tokens=2, details={"cost": 3}),
        "github_copilot",
    )
    assert not entry.priced and not entry.provider_reported


async def test_revocation_between_tool_round_trips_does_not_reuse_a_cached_token() -> None:
    from app.core.exceptions import AuthorizationError

    calls = 0
    requests = 0

    async def token() -> str:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AuthorizationError(message="connection disconnected")
        return "live-owner-token"

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        assert request.headers["authorization"] == "Bearer live-owner-token"
        return httpx2.Response(
            200,
            json={
                "id": "first",
                "object": "chat.completion",
                "created": 1,
                "model": "plan-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "work-1",
                                    "type": "function",
                                    "function": {"name": "work", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http,
        AgenticCopilotProvider(
            "initial-private-token", http_client=http, token_source=token
        ) as provider,
    ):
        agent = Agent(GitHubCopilotModel("plan-model", provider=provider))

        @agent.tool_plain
        def work() -> str:
            return "done"

        with pytest.raises(AuthorizationError, match="disconnected"):
            await agent.run("Do the work")
    assert calls == 2 and requests == 1


def test_a_copilot_profile_cannot_silently_ignore_a_custom_destination() -> None:
    with pytest.raises(BadRequestError, match="fixed GitHub"):
        build_model(
            ResolvedCredential(
                provider="github_copilot",
                secret=ApiKeySecret(api_key="private-token"),
                base_url="https://somewhere.example",
            ),
            "model",
        )
