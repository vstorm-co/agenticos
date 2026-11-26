"""Subscription accounts: one gateway scope per person per organization, spent only by its person."""

import json
import uuid
from collections.abc import AsyncGenerator, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

from app.agents.model_resolver import (
    PROVIDERS,
    ModelRequestSpec,
    ResolvedCredential,
    _build_provider,
    lacks_key,
)
from app.api import deps
from app.clients import subscription_gateway as client_module
from app.clients.subscription_gateway import GatewayAccount, SubscriptionGateway
from app.core.config import Settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.core.secret_purposes import all_purposes
from app.db.models.credential import ModelProfile
from app.main import app
from app.services import subscription_accounts as module
from app.services.model_profile import (
    ModelProfileService,
    _check_shape,
    _may_spend,
    choosable_for_others,
    is_sign_in,
)
from app.services.subscription_accounts import (
    SubscriptionAccountService,
    bind_to_person,
    gateway_scope,
    queue_wipe,
    wipe_scopes,
)
from app.worker.jobs import WIPE_SUBSCRIPTION_ACCOUNTS, WipeSubscriptionAccounts

pytestmark = pytest.mark.anyio

TOKEN = "g" * 40
URL = "http://subscription-gateway:8400"


def ctx(**overrides: object) -> AuthContext:
    values: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "role": OrgRoleName.MEMBER,
    }
    values.update(overrides)
    return AuthContext(**values)  # ty: ignore[invalid-argument-type] - test overrides


def gateway(handler: Callable[[httpx.Request], httpx.Response]) -> SubscriptionGateway:
    return SubscriptionGateway(URL + "/", TOKEN, transport=httpx.MockTransport(handler))


MEMBERSHIP_ID = uuid.UUID("00000000-0000-0000-0000-000000000031")


@pytest.fixture(autouse=True)
def membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module.member_repo, "get", AsyncMock(return_value=SimpleNamespace(id=MEMBERSHIP_ID))
    )


@pytest.fixture
def enabled() -> AsyncGenerator[None]:
    with (
        patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", URL),
        patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_TOKEN", TOKEN),
    ):
        yield


@pytest.fixture
def disabled() -> AsyncGenerator[None]:
    with patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", None):
        yield


def gateway_credential() -> ResolvedCredential:
    return ResolvedCredential(provider="subscription_accounts", secret=NoSecret())


# The scope


def test_a_scope_is_per_person_and_per_organization() -> None:
    org, other_org, alice, bob = (uuid.uuid4() for _ in range(4))
    assert gateway_scope(org, alice) == gateway_scope(org, alice)
    assert (
        len({gateway_scope(org, alice), gateway_scope(org, bob), gateway_scope(other_org, alice)})
        == 3
    )
    assert len(gateway_scope(org, alice)) == 64


# The client


async def test_the_client_sends_the_shared_token_and_reads_each_answer() -> None:
    seen: list[httpx.Request] = []
    answers = {
        ("POST", "/scopes/s/logins"): {
            "url": "https://x",
            "state": "st",
            "user_code": "C",
            "extra": 1,
        },
        ("GET", "/scopes/s/logins/st"): {"status": "ok"},
        ("POST", "/scopes/s/logins/st/callback"): {"accepted": True},
        ("DELETE", "/scopes/s/logins/st"): {"cancelled": True},
        ("GET", "/scopes/s/accounts"): {"items": [{"name": "a.json", "provider": "claude"}]},
        ("DELETE", "/scopes/s/accounts/a.json"): {"removed": True},
        ("GET", "/scopes/s/accounts/a.json/usage"): {"status": "unavailable", "windows": []},
        ("GET", "/scopes/s/accounts/a.json/models"): {"items": [{"id": "claude-sonnet"}]},
        ("POST", "/scopes/s/accounts/a.json/model-selection"): {
            "model": "account-test/claude-sonnet"
        },
        ("GET", "/scopes/s/v1/models"): {"data": [{"id": "claude-sonnet"}]},
        ("DELETE", "/scopes/s"): {"wiped": True},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answers[(request.method, request.url.path)])

    client = gateway(handler)
    started = await client.start_login("s", "claude")
    assert (started.state, started.user_code, started.flow) == ("st", "C", None)
    assert (await client.login_status("s", "st")).status == "ok"
    await client.complete_login("s", "st", "http://localhost:1/cb?code=x")
    await client.cancel_login("s", "st")
    assert await client.accounts("s") == [GatewayAccount(name="a.json", provider="claude")]
    await client.remove_account("s", "a.json")
    assert await client.models("s") == ["claude-sonnet"]
    assert (await client.account_usage("s", "a.json")).status == "unavailable"
    assert await client.account_models("s", "a.json") == ["claude-sonnet"]
    assert (
        await client.select_account_model("s", "a.json", "claude-sonnet")
    ).model == "account-test/claude-sonnet"
    await client.wipe("s")
    assert client.model_endpoint("s") == f"{URL}/scopes/s/v1"
    assert {request.headers["authorization"] for request in seen} == {f"Bearer {TOKEN}"}
    assert json.loads(seen[0].content) == {"provider": "claude"}
    assert json.loads(seen[2].content) == {"redirect_url": "http://localhost:1/cb?code=x"}


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (
            httpx.Response(400, json={"detail": "Invalid sign-in"}),
            BadRequestError,
            "Invalid sign-in",
        ),
        (
            httpx.Response(404, text="nope"),
            BadRequestError,
            "The subscription gateway refused this",
        ),
        (httpx.Response(401, json=["x"]), BadRequestError, "The subscription gateway refused this"),
        (httpx.Response(503, json={"detail": "busy"}), ExternalServiceError, "busy"),
        (httpx.Response(502, json={"detail": ""}), ExternalServiceError, "could not do this"),
        (httpx.Response(200, json={"unexpected": True}), ExternalServiceError, "cannot read"),
    ],
)
async def test_gateway_refusals_become_domain_errors(
    response: httpx.Response, error: type[Exception], message: str
) -> None:
    with pytest.raises(error) as raised:
        await gateway(lambda _request: response).accounts("s")
    assert message in str(raised.value)


async def test_an_unreachable_gateway_is_a_service_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ExternalServiceError):
        await gateway(handler).models("s")


async def test_the_configured_gateway_follows_settings(enabled: None) -> None:
    configured = client_module.configured_gateway()
    assert configured is not None and configured.base_url == URL and configured.token == TOKEN
    with patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", None):
        assert client_module.configured_gateway() is None


def test_the_gateway_url_needs_a_long_token() -> None:
    with pytest.raises(ValueError, match="SUBSCRIPTION_GATEWAY_TOKEN"):
        Settings(SUBSCRIPTION_GATEWAY_URL=URL, SUBSCRIPTION_GATEWAY_TOKEN="short")
    assert Settings(SUBSCRIPTION_GATEWAY_URL=URL, SUBSCRIPTION_GATEWAY_TOKEN=TOKEN)


# The service


async def test_the_service_acts_on_the_callers_own_scope_only(enabled: None) -> None:
    caller = ctx()
    scope = gateway_scope(caller.organization_id, caller.user_id, MEMBERSHIP_ID)
    fake = AsyncMock(spec=SubscriptionGateway)
    fake.accounts.return_value = []
    fake.models.return_value = ["m"]
    fake.account_usage.return_value = client_module.AccountUsage()
    fake.account_models.return_value = ["m"]
    fake.select_account_model.return_value = client_module.SelectedAccountModel(
        model="account-test/m"
    )
    db = MagicMock()
    service = SubscriptionAccountService(db)
    with (
        patch.object(module, "configured_gateway", return_value=fake),
        patch.object(module, "record_audit", AsyncMock()) as audit,
    ):
        assert await service.accounts(caller) == []
        assert await service.models(caller) == ["m"]
        assert (await service.account_usage(caller, "a.json")).status == "unavailable"
        assert await service.account_models(caller, "a.json") == ["m"]
        assert (await service.select_account_model(caller, "a.json", "m")).model == "account-test/m"
        await service.start_login(caller, "antigravity")
        await service.login_status(caller, "st")
        await service.complete_login(caller, "st", "https://localhost/cb")
        await service.cancel_login(caller, "st")
        await service.remove(caller, "a.json")
        with pytest.raises(BadRequestError):
            await service.complete_login(caller, "st", "javascript:alert(1)")
    for method in (
        "accounts",
        "models",
        "account_usage",
        "account_models",
        "select_account_model",
        "start_login",
        "login_status",
        "complete_login",
        "cancel_login",
        "remove_account",
    ):
        assert getattr(fake, method).await_args.args[0] == scope
    actions = [call.kwargs["action"] for call in audit.await_args_list]
    assert actions == ["subscription_account.sign_in_started", "subscription_account.removed"]
    assert all(
        "token" not in json.dumps(call.kwargs.get("details") or {})
        for call in audit.await_args_list
    )


@pytest.mark.parametrize(
    "caller",
    [
        ctx(api_key_id=uuid.uuid4()),
        ctx(user_id=None),
        ctx(subject_is_publisher_fallback=True),
        ctx(channel_identity_id=uuid.uuid4()),
    ],
)
async def test_only_a_signed_in_person_reaches_a_scope(caller: AuthContext, enabled: None) -> None:
    with pytest.raises(AuthorizationError):
        await SubscriptionAccountService(MagicMock()).accounts(caller)
    with pytest.raises(AuthorizationError):
        await SubscriptionAccountService(MagicMock()).select_account_model(caller, "a.json", "m")


async def test_the_service_names_the_settings_when_the_gateway_is_off(disabled: None) -> None:
    with pytest.raises(ConfigurationError, match="SUBSCRIPTION_GATEWAY_URL"):
        await SubscriptionAccountService(MagicMock()).accounts(ctx())


# Teardown


async def test_leaving_queues_a_durable_wipe_of_that_persons_scope(enabled: None) -> None:
    org, person = uuid.uuid4(), uuid.uuid4()
    with patch.object(module, "enqueue", AsyncMock()) as enqueue:
        await queue_wipe(MagicMock(), org, [person])
        await queue_wipe(MagicMock(), org, [])
    enqueue.assert_awaited_once()
    task, payload = enqueue.await_args.args[1:]
    assert task is WIPE_SUBSCRIPTION_ACCOUNTS
    assert payload == WipeSubscriptionAccounts(
        scopes=sorted([gateway_scope(org, person), gateway_scope(org, person, MEMBERSHIP_ID)])
    )


async def test_disabled_gateway_preserves_the_deletion_obligation(disabled: None) -> None:
    with patch.object(module, "enqueue", AsyncMock()) as enqueue:
        await queue_wipe(MagicMock(), uuid.uuid4(), [uuid.uuid4()])
    enqueue.assert_awaited_once()
    with pytest.raises(ConfigurationError):
        await wipe_scopes(WipeSubscriptionAccounts(scopes=["a" * 64]))


async def test_the_wipe_job_wipes_every_scope(enabled: None) -> None:
    fake = AsyncMock(spec=SubscriptionGateway)
    with patch.object(module, "configured_gateway", return_value=fake):
        await wipe_scopes(WipeSubscriptionAccounts(scopes=["a" * 64, "b" * 64]))
    assert [call.args[0] for call in fake.wipe.await_args_list] == ["a" * 64, "b" * 64]


async def test_ending_a_membership_wipes_the_persons_accounts() -> None:
    from app.services import member as member_module

    membership = MagicMock(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
    with (
        patch.object(module, "queue_wipe", AsyncMock()) as wipe,
        patch(
            "app.services.sandbox_workspace.SandboxWorkspaceService.purge_personal_coding",
            AsyncMock(),
        ),
        patch.multiple(
            member_module,
            group_repo=AsyncMock(),
            oauth_repo=AsyncMock(),
            api_key_repo=AsyncMock(),
            coding_account_repo=AsyncMock(),
            mcp_connection_repo=AsyncMock(),
            agent_trigger_repo=AsyncMock(),
            telephony_repo=AsyncMock(),
            member_repo=AsyncMock(),
            resource_grant_repo=AsyncMock(),
        ),
    ):
        await member_module.end_membership(MagicMock(), membership)
    wipe.assert_awaited_once()
    assert wipe.await_args.args[1:] == (membership.organization_id, [membership.user_id])


# Models and resolution


def test_the_provider_takes_no_key_and_has_no_vault_purpose() -> None:
    spec = PROVIDERS["subscription_accounts"]
    assert spec.personal_gateway
    assert not lacks_key(
        "subscription_accounts", secret_id=None, base_url=None, runs_without_key=False
    )
    assert "subscription_accounts" not in {purpose.id for purpose in all_purposes()}


def test_a_profile_takes_nothing_but_a_model(enabled: None) -> None:
    spec = PROVIDERS["subscription_accounts"]
    _check_shape(spec, secret_id=None, base_url=None, api=None)
    for field, value in (
        ("secret_id", {"secret_id": uuid.uuid4()}),
        ("base_url", {"base_url": "http://elsewhere"}),
        ("api", {"api": "responses"}),
        ("region", {"region": "eu"}),
    ):
        arguments = {"secret_id": None, "base_url": None, "api": None, **value}
        with pytest.raises(BadRequestError) as refused:
            _check_shape(spec, **arguments)  # ty: ignore[invalid-argument-type] - one field at a time
        assert field in str(refused.value.details)


def test_a_profile_is_refused_where_the_gateway_is_off(disabled: None) -> None:
    with pytest.raises(BadRequestError, match="SUBSCRIPTION_GATEWAY_URL"):
        _check_shape(PROVIDERS["subscription_accounts"], secret_id=None, base_url=None, api=None)


def test_the_platform_never_picks_it_for_somebody() -> None:
    profile = ModelProfile(
        id=uuid.uuid4(),
        provider="subscription_accounts",
        model="claude-sonnet",
        label="Mine",
        fallback_profile_ids=[],
        runs_without_key=False,
    )
    assert is_sign_in(profile)
    assert not choosable_for_others(profile, {})


async def test_only_a_person_may_spend_it() -> None:
    assert await _may_spend(gateway_credential(), uuid.uuid4())
    assert not await _may_spend(gateway_credential(), None)


def _spec(credential: ResolvedCredential, fallbacks: list[ResolvedCredential]) -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="Mine",
        provider=credential.provider,
        model="claude-sonnet",
        params={},
        credential=credential,
        secret_id=None,
        fallbacks=[(fallback, "m") for fallback in fallbacks],
    )


async def test_a_run_reaches_the_runners_own_scope(enabled: None) -> None:
    caller = ctx()
    key = ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test-123456"))
    spec = _spec(gateway_credential(), [gateway_credential(), key])
    with patch.object(ModelProfileService, "_resolve_in", AsyncMock(return_value=spec)):
        resolved = await ModelProfileService(MagicMock()).resolve(caller)
    endpoint = (
        f"{URL}/scopes/{gateway_scope(caller.organization_id, caller.user_id, MEMBERSHIP_ID)}/v1"
    )
    assert resolved.credential.base_url == endpoint
    assert isinstance(resolved.credential.secret, ApiKeySecret)
    assert resolved.credential.secret.api_key.get_secret_value() == TOKEN
    assert resolved.fallbacks[0][0].base_url == endpoint
    assert resolved.fallbacks[1][0] is key
    provider = _build_provider(PROVIDERS["subscription_accounts"], resolved.credential)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert str(provider.client.base_url).rstrip("/") == endpoint


async def test_a_spec_without_the_gateway_is_returned_as_it_is(enabled: None) -> None:
    key = ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test-123456"))
    spec = _spec(key, [])
    with patch.object(ModelProfileService, "_resolve_in", AsyncMock(return_value=spec)):
        assert await ModelProfileService(MagicMock()).resolve(ctx()) is spec
    assert await bind_to_person(MagicMock(), key, uuid.uuid4(), uuid.uuid4()) is key


async def test_nobody_behind_a_run_reaches_nobodys_accounts(enabled: None) -> None:
    spec = _spec(gateway_credential(), [])
    with patch.object(ModelProfileService, "_resolve_in", AsyncMock(return_value=spec)):
        with pytest.raises(AuthorizationError, match="own subscription"):
            await ModelProfileService(MagicMock()).resolve(ctx(api_key_id=uuid.uuid4()))
        with pytest.raises(BadRequestError, match="background work"):
            await ModelProfileService(MagicMock()).resolve_for_organization(uuid.uuid4())


def test_an_unbound_credential_cannot_build_a_client() -> None:
    with pytest.raises(BadRequestError, match="own run"):
        _build_provider(PROVIDERS["subscription_accounts"], gateway_credential())


# Routes


@pytest.fixture
def routes() -> AsyncGenerator[tuple[AsyncMock, AuthContext]]:
    caller = ctx()
    service = AsyncMock(spec=SubscriptionAccountService)
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    app.dependency_overrides[deps.get_subscription_account_service] = lambda: service
    try:
        yield service, caller
    finally:
        app.dependency_overrides.clear()


async def test_routes_hand_the_callers_context_to_the_service(
    routes: tuple[AsyncMock, AuthContext], enabled: None
) -> None:
    service, caller = routes
    service.accounts.return_value = [GatewayAccount(name="a.json", provider="claude", email="me@x")]
    service.start_login.return_value = client_module.LoginStarted(url="https://x", state="st")
    service.login_status.return_value = client_module.LoginStatus(status="wait")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/subscription-accounts")
        started = await client.post(
            "/api/v1/subscription-accounts/sign-ins", json={"provider": "claude"}
        )
        refused = await client.post(
            "/api/v1/subscription-accounts/sign-ins", json={"provider": "cursor"}
        )
        status = await client.get("/api/v1/subscription-accounts/sign-ins/st")
        finished = await client.post(
            "/api/v1/subscription-accounts/sign-ins/st/callback",
            json={"redirect_url": "http://localhost/cb"},
        )
        cancelled = await client.delete("/api/v1/subscription-accounts/sign-ins/st")
        removed = await client.delete("/api/v1/subscription-accounts/a.json")
        bad_name = await client.delete("/api/v1/subscription-accounts/a%20b")
    assert listed.json()["enabled"] is True
    assert listed.json()["items"][0]["email"] == "me@x"
    assert started.status_code == 201 and started.json()["state"] == "st"
    assert refused.status_code == 422
    assert status.json() == {"status": "wait", "error": None}
    assert (finished.status_code, cancelled.status_code, removed.status_code) == (204, 204, 204)
    assert bad_name.status_code == 422
    assert service.accounts.await_args.args == (caller,)
    service.remove.assert_awaited_once_with(caller, "a.json")


async def test_the_listing_says_when_the_gateway_is_off(
    routes: tuple[AsyncMock, AuthContext], disabled: None
) -> None:
    service, _ = routes
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/subscription-accounts")
    assert listed.json() == {"enabled": False, "items": []}
    service.accounts.assert_not_awaited()


async def test_the_model_list_is_what_the_callers_accounts_serve(
    routes: tuple[AsyncMock, AuthContext], enabled: None
) -> None:
    service, caller = routes
    service.models.return_value = ["claude-sonnet", "gemini-pro"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/providers/subscription_accounts/models")
        with patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", None):
            off = await client.get("/api/v1/providers/subscription_accounts/models")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == ["claude-sonnet", "gemini-pro"]
    assert listed.json()["source"] == "live"
    assert off.json()["items"] == [] and off.json()["source"] == "unlisted"
    service.models.assert_awaited_once_with(caller)


async def test_the_catalog_offers_subscription_accounts_only_with_a_gateway(
    routes: tuple[AsyncMock, AuthContext],
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", URL):
            on = (await client.get("/api/v1/providers/catalog")).json()["items"]
        with patch.object(client_module.settings, "SUBSCRIPTION_GATEWAY_URL", None):
            off = (await client.get("/api/v1/providers/catalog")).json()["items"]
    gateway_rows = [row for row in on if row["id"] == "subscription_accounts"]
    assert len(gateway_rows) == 1 and gateway_rows[0]["personal_gateway"] is True
    assert all(row["id"] != "subscription_accounts" for row in off)
    assert all(
        row["personal_gateway"] is False for row in on if row["id"] != "subscription_accounts"
    )


async def test_deleting_an_account_wipes_it_in_every_organization(enabled: None) -> None:
    person, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    listing = AsyncMock(side_effect=[[first, second], []])
    with (
        patch.object(module.member_repo, "list_organization_ids", listing),
        patch.object(module, "enqueue", AsyncMock()) as enqueue,
    ):
        await module.queue_wipe_person(MagicMock(), person)
        await module.queue_wipe_person(MagicMock(), person)
    assert enqueue.await_count == 2
    scopes = {scope for call in enqueue.await_args_list for scope in call.args[2].scopes}
    assert scopes == {
        gateway_scope(org, person, generation)
        for org in [first, second]
        for generation in [None, MEMBERSHIP_ID]
    }


async def test_deleting_an_organization_wipes_every_members_accounts(enabled: None) -> None:
    org, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with (
        patch.object(module.member_repo, "list_user_ids", AsyncMock(return_value=[first, second])),
        patch.object(module, "enqueue", AsyncMock()) as enqueue,
    ):
        await module.queue_organization_wipe(MagicMock(), org)
    payload = enqueue.await_args.args[2]
    assert payload.scopes == sorted(
        gateway_scope(org, person, generation)
        for person in [first, second]
        for generation in [None, MEMBERSHIP_ID]
    )
    assert enqueue.await_args.kwargs["organization_id"] == org


async def test_disabled_gateway_still_records_organization_and_person_cleanup(
    disabled: None,
) -> None:
    with (
        patch.object(module.member_repo, "list_user_ids", AsyncMock(return_value=[uuid.uuid4()])),
        patch.object(
            module.member_repo, "list_organization_ids", AsyncMock(return_value=[uuid.uuid4()])
        ),
        patch.object(module, "enqueue", AsyncMock()) as enqueue,
    ):
        await module.queue_organization_wipe(MagicMock(), uuid.uuid4())
        await module.queue_wipe_person(MagicMock(), uuid.uuid4())
    assert enqueue.await_count == 2


async def test_account_models_route_keeps_the_authenticated_context(
    routes: tuple[AsyncMock, AuthContext],
) -> None:
    service, caller = routes
    service.account_models.return_value = ["claude-sonnet"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.get("/api/v1/subscription-accounts/a.json/models")
        bad = await client.get("/api/v1/subscription-accounts/bad!name/models")
    assert answer.status_code == 200 and answer.json() == ["claude-sonnet"]
    assert bad.status_code == 422
    service.account_models.assert_awaited_once_with(caller, "a.json")


async def test_account_model_selection_route_keeps_the_authenticated_context(
    routes: tuple[AsyncMock, AuthContext],
) -> None:
    service, caller = routes
    service.select_account_model.return_value = client_module.SelectedAccountModel(
        model="account-test/claude"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.post(
            "/api/v1/subscription-accounts/a.json/model-selection", json={"model": "claude"}
        )
        bad = await client.post(
            "/api/v1/subscription-accounts/a.json/model-selection", json={"model": "bad model"}
        )
        long = await client.post(
            "/api/v1/subscription-accounts/a.json/model-selection", json={"model": "a" * 223}
        )
    assert answer.status_code == 200 and answer.json() == {"model": "account-test/claude"}
    assert bad.status_code == long.status_code == 422
    service.select_account_model.assert_awaited_once_with(caller, "a.json", "claude")


async def test_account_usage_route_keeps_the_authenticated_context(
    routes: tuple[AsyncMock, AuthContext],
) -> None:
    service, caller = routes
    service.account_usage.return_value = client_module.AccountUsage()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.get("/api/v1/subscription-accounts/a.json/usage")
        bad = await client.get("/api/v1/subscription-accounts/bad!name/usage")
    assert answer.status_code == 200 and answer.json()["status"] == "unavailable"
    assert bad.status_code == 422
    service.account_usage.assert_awaited_once_with(caller, "a.json")


@pytest.mark.parametrize("provider", ["subscription_accounts", "cliproxyapi"])
async def test_claude_gateway_keeps_all_tools_without_exceeding_strict_tool_limits(
    provider: str,
) -> None:
    import httpx2
    from pydantic_ai import Agent, Tool
    from pydantic_ai.models.openai import OpenAIChatModel

    from app.agents.model_resolver import build_model

    name = "account-" + "a" * 24 + "/claude-haiku-4-5-20251001"
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == name
        assert len(payload["tools"]) == 79
        assert all("strict" not in tool["function"] for tool in payload["tools"])
        return httpx2.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": name,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ready"},
                    }
                ],
            },
        )

    def available_tool() -> str:
        return "ready"

    model = build_model(
        ResolvedCredential(
            provider=provider,
            secret=ApiKeySecret(api_key="scope-key"),
            base_url="http://gateway.test/v1",
        ),
        name,
    )
    assert isinstance(model, OpenAIChatModel)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        model._provider._client = model.client.with_options(http_client=transport, max_retries=0)
        result = await Agent(
            model, tools=[Tool(available_tool, name=f"tool_{i}", strict=True) for i in range(79)]
        ).run("hello")
    assert result.output == "ready"
    assert len(seen) == 1


def test_other_subscription_models_keep_their_supported_strict_tools() -> None:
    from app.agents.model_resolver import build_model

    model = build_model(
        ResolvedCredential(
            provider="subscription_accounts",
            secret=ApiKeySecret(api_key="scope-key"),
            base_url="http://gateway.test/v1",
        ),
        "account-" + "a" * 24 + "/gpt-6-sol",
    )
    assert model.profile.get("openai_supports_strict_tool_definition", True)


@pytest.mark.security
async def test_delayed_or_retried_departure_wipes_cannot_delete_a_rejoined_members_accounts(
    enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = ctx()
    member = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(module.member_repo, "get", AsyncMock(return_value=member))
    queued = AsyncMock()
    monkeypatch.setattr(module, "enqueue", queued)
    old_scope = await SubscriptionAccountService(MagicMock())._scope(caller)
    await queue_wipe(MagicMock(), caller.organization_id, [caller.user_id])
    job = queued.await_args.args[2]
    member.id = uuid.uuid4()
    new_scope = await SubscriptionAccountService(MagicMock())._scope(caller)
    credentials = {old_scope: "old", new_scope: "new"}
    gateway = AsyncMock(spec=SubscriptionGateway)

    async def wipe(scope: str) -> None:
        credentials.pop(scope, None)

    gateway.wipe.side_effect = wipe
    monkeypatch.setattr(module, "configured_gateway", lambda: gateway)
    await wipe_scopes(job)
    await wipe_scopes(job)
    assert credentials == {new_scope: "new"}
    assert old_scope != new_scope


@pytest.mark.security
async def test_a_departed_member_cannot_reach_subscription_accounts(
    enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module.member_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError, match="active membership"):
        await SubscriptionAccountService(MagicMock()).accounts(ctx())
    with patch.object(module, "enqueue", AsyncMock()) as enqueue:
        caller = ctx()
        await queue_wipe(MagicMock(), caller.organization_id, [caller.user_id])
    assert enqueue.await_args.args[2].scopes == [
        gateway_scope(caller.organization_id, caller.user_id)
    ]
