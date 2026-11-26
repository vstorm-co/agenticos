"""Official application grants retain registration but never infer plan consent."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx2
import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from app.agents.chatgpt_plan import ChatGPTPlanProvider
from app.agents.model_resolver import ResolvedCredential, build_model, build_with_fallbacks
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.secret_kinds import (
    OpenAIChatGPTSecret,
    SecretKind,
    TypedSecret,
    seal_secret,
    unseal_kind,
)
from app.core.vault import VaultScope
from app.db.models.resource_grant import Visibility
from app.services import chatgpt_plan as plan
from app.services.chatgpt_plan import (
    ChatGPTPlanService,
    VaultChatGPTCredentials,
    as_secret,
    credentials,
)
from tests.test_openai_codex import _ctx

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def grant(
    *, scope: str = "openid chatgpt.tokens.use.direct", suffix: str = "original"
) -> OpenAIChatGPTCredentials:
    return OpenAIChatGPTCredentials(
        client_id="agenticos-client",
        access_token=f"access-{suffix}",
        refresh_token=f"refresh-{suffix}",
        id_token="id-token-value",
        scope=scope,
    )


class Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ttl: int) -> None:
        assert ttl == 900
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.values.get(key) != value:
            return False
        del self.values[key]
        return True


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch):
    ctx = _ctx()
    host = uuid4()
    monkeypatch.setattr(plan.settings, "OPENAI_CHATGPT_PLAN_USAGE_ENABLED", True)
    monkeypatch.setattr(plan.settings, "OPENAI_CHATGPT_HOST_ID", host)
    registration = MagicMock(host_id=host, client_id=None, generation=uuid4())
    monkeypatch.setattr(plan.registrations, "start", AsyncMock(return_value=registration))
    monkeypatch.setattr(plan.registrations, "get", AsyncMock(return_value=registration))
    monkeypatch.setattr(plan.registrations, "claim_client", AsyncMock(return_value=True))

    @asynccontextmanager
    async def session():
        yield MagicMock()

    monkeypatch.setattr(plan, "get_db_context", session)
    redis = Redis()
    service = ChatGPTPlanService(MagicMock(), redis)
    return ctx, registration, redis, service


async def start(setup) -> str:
    ctx, _, _, service = setup
    url = await service.start_sign_in(ctx)
    query = parse_qs(urlsplit(url).query)
    return "http://127.0.0.1:1455/auth/callback?" + urlencode(
        {"state": query["state"][0], "code": "code-value", "client_id": "agenticos-client"}
    )


async def test_sign_in_names_agenticos_and_reuses_the_durable_client_and_host(setup) -> None:
    ctx, registration, redis, service = setup
    registration.client_id = "saved-client"
    url = await service.start_sign_in(ctx)
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["saved-client"]
    assert query["ext_agent_host_id"] == [registration.host_id.urn]
    assert query["prompt"] == ["consent"] and "agent_name_hint" not in query
    assert len(redis.values) == 1 and "code_verifier" not in url
    registration.client_id = None
    query = parse_qs(urlsplit(await service.start_sign_in(ctx)).query)
    assert query["agent_name_hint"] == ["AgenticOS"]


@pytest.mark.parametrize("enabled,host", [(False, uuid4()), (True, None)])
async def test_operator_eligibility_is_required_before_any_registration(
    setup, monkeypatch: pytest.MonkeyPatch, enabled: bool, host
) -> None:
    ctx, _, redis, service = setup
    monkeypatch.setattr(plan.settings, "OPENAI_CHATGPT_PLAN_USAGE_ENABLED", enabled)
    monkeypatch.setattr(plan.settings, "OPENAI_CHATGPT_HOST_ID", host)
    with pytest.raises(BadRequestError, match="disabled"):
        await service.start_sign_in(ctx)
    assert not redis.values
    plan.registrations.start.assert_not_awaited()


async def test_a_changed_installation_id_cannot_reuse_another_hosts_registration(setup) -> None:
    ctx, row, redis, service = setup
    row.host_id = uuid4()
    with pytest.raises(BadRequestError, match="installation identity"):
        await service.start_sign_in(ctx)
    assert not redis.values


@pytest.mark.parametrize("scope", ["openid", "openid chatgpt.tokens.use.direct"])
async def test_both_declined_and_granted_plan_consent_are_saved_with_an_explicit_result(
    setup, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    ctx, _, redis, service = setup
    callback = await start(setup)
    exchange = AsyncMock(return_value=grant(scope=scope))
    monkeypatch.setattr(plan.OpenAIChatGPTOAuthFlow, "exchange_code", exchange)
    create = AsyncMock(return_value=MagicMock(id=uuid4()))
    monkeypatch.setattr(plan.OrganizationSecretService, "create", create)
    result = await service.create(
        ctx, callback_url=callback, name="My plan", description=None, visibility=Visibility.PRIVATE
    )
    assert result.plan_usage_granted == ("chatgpt.tokens.use.direct" in scope)
    stored = create.call_args.kwargs["value"]
    assert credentials(stored) == grant(scope=scope)
    assert create.call_args.kwargs["purpose"] == "openai_chatgpt" and not redis.values
    with pytest.raises(NotFoundError):
        await service.create(
            ctx,
            callback_url=callback,
            name="Replay",
            description=None,
            visibility=Visibility.PRIVATE,
        )


async def test_registration_is_durable_even_when_the_token_exchange_fails(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = setup
    callback = await start(setup)

    async def exchange(_self, _code, *, client_id):
        plan.registrations.claim_client.assert_awaited_once()
        raise UserError("invalid grant")

    monkeypatch.setattr(plan.OpenAIChatGPTOAuthFlow, "exchange_code", exchange)
    with pytest.raises(BadRequestError, match="registration was saved"):
        await service.create(
            ctx,
            callback_url=callback,
            name="My plan",
            description=None,
            visibility=Visibility.PRIVATE,
        )
    assert plan.registrations.claim_client.call_args.kwargs["client_id"] == "agenticos-client"


@pytest.mark.parametrize(
    "callback",
    [
        "http://localhost:1455/auth/callback?code=x&state=x",
        "https://127.0.0.1:1455/auth/callback?code=x&state=x",
        "http://127.0.0.1:1455/auth/callback?state=x&state=y",
        "http://127.0.0.1:1455/auth/callback?code=x",
    ],
)
async def test_callback_requires_the_exact_loopback_and_unambiguous_state(
    setup, callback: str
) -> None:
    ctx, _, _, service = setup
    with pytest.raises(BadRequestError):
        await service.create(
            ctx,
            callback_url=callback,
            name="My plan",
            description=None,
            visibility=Visibility.PRIVATE,
        )


async def test_another_member_cannot_consume_the_pending_callback(setup) -> None:
    ctx, _, redis, service = setup
    callback = await start(setup)
    with pytest.raises(NotFoundError):
        await service.create(
            _ctx(org_id=ctx.organization_id),
            callback_url=callback,
            name="Stolen",
            description=None,
            visibility=Visibility.PRIVATE,
        )
    assert redis.values


@pytest.mark.parametrize(
    "change", ["declined", "missing_client", "mismatch", "stale", "superseded"]
)
async def test_refused_or_superseded_sign_ins_cannot_store_a_grant(
    setup, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    ctx, row, _, service = setup
    if change == "mismatch":
        row.client_id = "existing-client"
    callback = await start(setup)
    if change == "declined":
        callback += "&error=access_denied"
    if change == "missing_client":
        callback = callback.replace("&client_id=agenticos-client", "")
    if change == "stale":
        plan.registrations.claim_client.return_value = False
    if change == "superseded":
        plan.registrations.get.return_value = MagicMock(generation=uuid4())
    monkeypatch.setattr(
        plan.OpenAIChatGPTOAuthFlow, "exchange_code", AsyncMock(return_value=grant())
    )
    create = AsyncMock()
    monkeypatch.setattr(plan.OrganizationSecretService, "create", create)
    with pytest.raises((BadRequestError, ConflictError)):
        await service.create(
            ctx,
            callback_url=callback,
            name="My plan",
            description=None,
            visibility=Visibility.PRIVATE,
        )
    create.assert_not_awaited()


async def test_official_grants_cannot_be_typed_or_shared_during_connection(setup) -> None:
    ctx, _, _, service = setup
    with pytest.raises(ValidationError):
        TypeAdapter(TypedSecret).validate_python(as_secret(grant()).model_dump())
    with pytest.raises(BadRequestError, match="privately"):
        await service.create(
            ctx, callback_url="unused", name="Shared", description=None, visibility=Visibility.ORG
        )


async def test_vault_rotation_uses_compare_and_swap_and_preserves_connection_generation(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _ = setup
    value = as_secret(grant())
    sealed = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
    row = MagicMock(
        id=uuid4(),
        owner_user_id=ctx.user_id,
        authorization_generation=uuid4(),
        kind=SecretKind.OPENAI_CHATGPT.value,
        sealed_secret=sealed.ciphertext,
        key_version=sealed.key_version,
    )
    monkeypatch.setattr(plan.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.organization_secret_repo, "get_locked", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.member_repo, "get", AsyncMock(return_value=MagicMock()))
    update = AsyncMock()
    monkeypatch.setattr(plan.organization_secret_repo, "update", update)
    source = VaultChatGPTCredentials(
        organization_id=ctx.organization_id,
        secret_id=row.id,
        generation=row.authorization_generation,
    )
    assert await source.load() == grant()
    await source.assert_current()
    await source.save(grant(suffix="rotated"))
    written = update.call_args.kwargs["update_data"]
    assert "authorization_generation" not in written
    rotated = unseal_kind(
        written["sealed_secret"],
        model=OpenAIChatGPTSecret,
        scope=VaultScope.organization(ctx.organization_id),
        key_version=written["key_version"],
    )
    assert credentials(rotated) == grant(suffix="rotated")
    assert "refresh-rotated" not in repr(source)
    with pytest.raises(ConflictError):
        await source.save(grant(suffix="loser"))
    row.authorization_generation = uuid4()
    with pytest.raises(BadRequestError, match="grant changed"):
        await source.assert_current()


async def test_model_construction_requires_a_durable_official_source_and_has_no_fallback() -> None:
    value = as_secret(grant())
    credential = ResolvedCredential(provider="openai_chatgpt", secret=value)
    with pytest.raises(BadRequestError, match="durable"):
        build_model(credential, "gpt-6.1-sol")
    with pytest.raises(BadRequestError, match="fallback"):
        build_with_fallbacks((credential, "gpt-6.1-sol"), [(credential, "gpt-6.1-sol")])
    source = VaultChatGPTCredentials(organization_id=uuid4(), secret_id=uuid4(), generation=uuid4())
    model = build_model(
        ResolvedCredential(provider="openai_chatgpt", secret=value, chatgpt_source=source),
        "gpt-6.1-sol",
    )
    assert model.profile.get("openai_responses_requires_store_false")
    assert model.profile.get("openai_responses_requires_streaming")
    assert not model.profile.get("openai_supports_batch_api")
    async with model:
        pass


async def test_real_sdk_streams_only_public_responses_and_checks_cached_grant_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from tests.test_stav_cost import _wire

    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer access-original"
        assert body["stream"] is True and body["store"] is False
        assert body["model"] == "gpt-6.1-sol"
        assert "temperature" not in body and "max_output_tokens" not in body
        return _wire("responses", True, {})

    source = VaultChatGPTCredentials(organization_id=uuid4(), secret_id=uuid4(), generation=uuid4())
    current = AsyncMock()
    monkeypatch.setattr(source, "assert_current", current)
    monkeypatch.setattr(source, "load", AsyncMock(return_value=grant()))
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        provider = ChatGPTPlanProvider(source, http_client=client)
        model = OpenAIResponsesModel("gpt-6.1-sol", provider=provider)
        messages = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
        reply = await model.request(
            messages,
            {"temperature": 0.5, "max_tokens": 10, "openai_store": True},
            ModelRequestParameters(),
        )
        assert reply.parts[0].content == "hello"
        current.side_effect = BadRequestError(message="Grant revoked")
        with pytest.raises(BadRequestError, match="revoked"):
            await model.request(messages, None, ModelRequestParameters())
        assert len(requests) == 1


async def test_account_catalog_uses_the_selected_grant_and_keeps_only_visible_models(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _ = setup
    row = MagicMock(id=uuid4(), authorization_generation=uuid4(), owner_user_id=ctx.user_id)
    monkeypatch.setattr(plan.OrganizationSecretService, "get_usable", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "load", AsyncMock(return_value=grant()))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "assert_current", AsyncMock())

    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://api.openai.com/v1/models"
        assert request.headers["authorization"] == "Bearer access-original"
        return httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "account-model",
                        "display_name": "Account model",
                        "visibility": "list",
                    },
                    {"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"},
                ]
            },
        )

    original = ChatGPTPlanProvider
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        monkeypatch.setattr(
            "app.agents.chatgpt_plan.ChatGPTPlanProvider",
            lambda source: original(source, http_client=client),
        )
        listed = await plan.account_models(MagicMock(), ctx, row.id)
    assert [model.id for model in listed] == ["account-model"]
    assert listed[0].surfaces == ("responses",)


async def test_declined_plan_grants_cannot_reach_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.openai import OpenAIResponsesModel

    source = VaultChatGPTCredentials(organization_id=uuid4(), secret_id=uuid4(), generation=uuid4())
    monkeypatch.setattr(source, "load", AsyncMock(return_value=grant(scope="openid")))
    monkeypatch.setattr(source, "assert_current", AsyncMock())

    def refuse(_request: httpx2.Request) -> httpx2.Response:
        pytest.fail("A grant without plan consent reached inference")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)) as client:
        model = OpenAIResponsesModel(
            "gpt-6.1-sol", provider=ChatGPTPlanProvider(source, http_client=client)
        )
        with pytest.raises(UserError, match="plan usage"):
            await model.request(
                [ModelRequest(parts=[UserPromptPart(content="Work")])],
                None,
                ModelRequestParameters(),
            )


async def test_sdk_401_refresh_persists_the_rotated_grant_before_replaying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from tests.test_stav_cost import _wire

    source = VaultChatGPTCredentials(organization_id=uuid4(), secret_id=uuid4(), generation=uuid4())
    monkeypatch.setattr(source, "load", AsyncMock(return_value=grant()))
    monkeypatch.setattr(source, "assert_current", AsyncMock())
    save = AsyncMock()
    monkeypatch.setattr(source, "save", save)
    calls: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        if request.url.host == "auth.openai.com":
            assert b"grant_type=refresh_token" in request.content
            assert b"client_id=agenticos-client" in request.content
            return httpx2.Response(
                200,
                json={
                    "access_token": "access-renewed",
                    "refresh_token": "refresh-renewed",
                    "scope": "chatgpt.tokens.use.direct",
                },
            )
        if len(calls) == 1:
            return httpx2.Response(
                401, json={"error": {"message": "Expired", "type": "authentication_error"}}
            )
        save.assert_awaited_once()
        assert request.headers["authorization"] == "Bearer access-renewed"
        return _wire("responses", True, {})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        model = OpenAIResponsesModel(
            "gpt-6.1-sol", provider=ChatGPTPlanProvider(source, http_client=client)
        )
        response = await model.request(
            [ModelRequest(parts=[UserPromptPart(content="Work")])], None, ModelRequestParameters()
        )
    assert response.parts[0].content == "hello" and len(calls) == 3
    assert save.call_args.args[0].client_id == "agenticos-client"


@pytest.mark.parametrize("reason", ["missing", "generation", "kind", "owner", "membership"])
async def test_the_vault_source_refuses_removed_or_replaced_authority(
    setup, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    ctx, _, _, _ = setup
    row = MagicMock(
        id=uuid4(),
        owner_user_id=ctx.user_id,
        authorization_generation=uuid4(),
        kind="openai_chatgpt",
    )
    generation = row.authorization_generation
    if reason == "generation":
        row.authorization_generation = uuid4()
    if reason == "kind":
        row.kind = "openai_codex"
    if reason == "owner":
        row.owner_user_id = None
    monkeypatch.setattr(
        plan.organization_secret_repo,
        "get",
        AsyncMock(return_value=None if reason == "missing" else row),
    )
    monkeypatch.setattr(
        plan.member_repo,
        "get",
        AsyncMock(return_value=None if reason == "membership" else MagicMock()),
    )
    source = VaultChatGPTCredentials(
        organization_id=ctx.organization_id, secret_id=row.id, generation=generation
    )
    with pytest.raises(BadRequestError, match="grant changed"):
        await source.load()


async def test_a_consumed_callback_cannot_win_again_and_a_saved_client_need_not_be_repeated(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, row, redis, service = setup
    row.client_id = "agenticos-client"
    callback = (await start(setup)).replace("&client_id=agenticos-client", "")
    exchange = AsyncMock(return_value=grant())
    monkeypatch.setattr(plan.OpenAIChatGPTOAuthFlow, "exchange_code", exchange)
    monkeypatch.setattr(
        plan.OrganizationSecretService, "create", AsyncMock(return_value=MagicMock())
    )
    result = await service.create(
        ctx, callback_url=callback, name="Again", description=None, visibility=Visibility.PRIVATE
    )
    assert result.plan_usage_granted
    callback = await start(setup)
    monkeypatch.setattr(redis, "delete_if_equal", AsyncMock(return_value=False))
    with pytest.raises(ConflictError, match="already used"):
        await service.create(
            ctx, callback_url=callback, name="Lost", description=None, visibility=Visibility.PRIVATE
        )
    assert exchange.await_count == 1


async def test_reconnect_checks_owner_and_edit_access_before_exchanging_a_code(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = setup
    callback = await start(setup)
    row = MagicMock(owner_user_id=ctx.user_id)
    monkeypatch.setattr(plan.OrganizationSecretService, "get_usable", AsyncMock(return_value=row))
    monkeypatch.setattr(plan, "resolve_access", AsyncMock(return_value=True))
    exchange = AsyncMock(return_value=grant())
    monkeypatch.setattr(plan.OpenAIChatGPTOAuthFlow, "exchange_code", exchange)
    update = AsyncMock(return_value=row)
    monkeypatch.setattr(plan.OrganizationSecretService, "update", update)
    result = await service.reconnect(ctx, uuid4(), callback_url=callback)
    assert result.connection is row and result.plan_usage_granted
    row.owner_user_id = uuid4()
    with pytest.raises(NotFoundError):
        await service.reconnect(ctx, uuid4(), callback_url="unused")
    row.owner_user_id = ctx.user_id
    plan.resolve_access.return_value = False
    with pytest.raises(NotFoundError):
        await service.reconnect(ctx, uuid4(), callback_url="unused")
    assert exchange.await_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {"models": []},
        {"models": [{"slug": "same", "display_name": "A", "visibility": "list"}] * 2},
        {"models": [{"slug": "bad id", "display_name": "A", "visibility": "list"}]},
        {"models": [{"slug": "good", "display_name": "", "visibility": "list"}]},
        {"data": []},
        {"models": [{"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"}] * 2049},
    ],
)
async def test_account_catalog_is_bounded_and_rejects_ambiguous_or_incompatible_shapes(
    setup, monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    ctx, _, _, _ = setup
    row = MagicMock(id=uuid4(), authorization_generation=uuid4(), owner_user_id=ctx.user_id)
    monkeypatch.setattr(plan.OrganizationSecretService, "get_usable", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "load", AsyncMock(return_value=grant()))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "assert_current", AsyncMock())
    original = ChatGPTPlanProvider
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, json=body))
    ) as client:
        monkeypatch.setattr(
            "app.agents.chatgpt_plan.ChatGPTPlanProvider",
            lambda source: original(source, http_client=client),
        )
        if body == {"models": []}:
            assert await plan.account_models(MagicMock(), ctx, row.id) == []
        else:
            with pytest.raises(BadRequestError):
                await plan.account_models(MagicMock(), ctx, row.id)


async def test_shared_profiles_cannot_lend_the_official_owners_grant_to_another_person(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.model_profile import _may_spend, choosable_for_others, is_sign_in

    ctx, _, _, _ = setup
    row = MagicMock(id=uuid4(), owner_user_id=ctx.user_id, authorization_generation=uuid4())
    monkeypatch.setattr(plan.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.member_repo, "get", AsyncMock(return_value=MagicMock(role="owner")))
    monkeypatch.setattr(plan, "resolve_access", AsyncMock(return_value=True))
    source = VaultChatGPTCredentials(
        organization_id=ctx.organization_id,
        secret_id=row.id,
        generation=row.authorization_generation,
    )
    credential = ResolvedCredential(
        provider="openai_chatgpt", secret=as_secret(grant()), chatgpt_source=source
    )
    assert await _may_spend(credential, ctx.user_id)
    assert not await _may_spend(credential, uuid4())
    assert not await _may_spend(credential, None)
    assert not await _may_spend(
        ResolvedCredential(provider="openai_chatgpt", secret=as_secret(grant())), ctx.user_id
    )
    profile = MagicMock(provider="openai_chatgpt", fallback_profile_ids=[])
    assert is_sign_in(profile) and not choosable_for_others(profile, {})
    row.authorization_generation = uuid4()
    assert not await source.visible_to(ctx.user_id)
    row.authorization_generation = source.generation
    plan.member_repo.get.return_value = None
    assert not await source.visible_to(ctx.user_id)


async def test_model_resolution_preserves_the_official_durable_source_and_exact_model_catalog(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import model_profile as profiles
    from app.services.model_catalog import CatalogModel
    from tests.test_model_profiles import _credential, _db, _profile

    ctx, _, _, _ = setup
    secret = _credential(ctx, provider="openai_chatgpt", secret=as_secret(grant()))
    profile = _profile(
        ctx, secret=secret, provider="openai_chatgpt", model="account-model", api="responses"
    )
    monkeypatch.setattr(profiles.organization_secret_repo, "get", AsyncMock(return_value=secret))
    service = profiles.ModelProfileService(_db())
    resolved = await service.resolve_credential(ctx.organization_id, profile)
    assert resolved.chatgpt_source is not None and resolved.credential_source is None
    assert resolved.chatgpt_source.generation == secret.authorization_generation
    monkeypatch.setattr(
        plan.OrganizationSecretService,
        "chatgpt_models",
        AsyncMock(return_value=[CatalogModel(id="account-model", name="Account model")]),
    )
    assert (
        await service._listed_model(ctx, "openai_chatgpt", "account-model", None, secret.id)
    ).id == "account-model"
    for model, secret_id in [("missing", secret.id), ("account-model", None)]:
        with pytest.raises(BadRequestError):
            await service._listed_model(ctx, "openai_chatgpt", model, None, secret_id)


async def test_official_sdk_completes_a_streamed_function_tool_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from tests.test_stav_cost import _responses, _wire

    source = VaultChatGPTCredentials(organization_id=uuid4(), secret_id=uuid4(), generation=uuid4())
    monkeypatch.setattr(source, "load", AsyncMock(return_value=grant()))
    monkeypatch.setattr(source, "assert_current", AsyncMock())
    requests: list[dict[str, object]] = []
    used: list[str] = []

    def lookup() -> str:
        used.append("looked up")
        return "authorized tool result"

    def respond(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert body["stream"] is True and body["store"] is False
        if len(requests) > 1:
            assert "authorized tool result" in json.dumps(body["input"])
            assert "previous_response_id" not in body
            return _wire("responses", True, {})
        call = {
            "id": "fc_test",
            "type": "function_call",
            "call_id": "call_lookup",
            "name": "lookup",
            "arguments": "{}",
            "status": "completed",
        }
        response = {**_responses({}), "output": [call]}
        events = [
            {
                "type": "response.created",
                "response": {**response, "status": "in_progress", "output": [], "usage": None},
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**call, "arguments": "", "status": "in_progress"},
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_test",
                "output_index": 0,
                "delta": "{}",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": call},
            {"type": "response.completed", "response": response},
        ]
        content = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return httpx2.Response(200, text=content, headers={"content-type": "text/event-stream"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        model = OpenAIResponsesModel(
            "gpt-6.1-sol", provider=ChatGPTPlanProvider(source, http_client=client)
        )
        agent = Agent(model, tools=[lookup])
        result = await agent.run("Use lookup and report the result")
    assert result.output == "hello" and used == ["looked up"] and len(requests) == 2


async def test_official_profiles_refuse_fallbacks_at_creation_and_update(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.model_profile import ModelProfileUpdate
    from app.services.model_profile import ModelProfileService
    from tests.test_model_profiles import _db, _profile

    ctx, _, _, _ = setup
    service = ModelProfileService(_db())
    with pytest.raises(BadRequestError, match="automatic fallbacks"):
        await service.create_profile(
            ctx,
            label="Official",
            provider="openai_chatgpt",
            model="account-model",
            secret_id=uuid4(),
            fallback_profile_ids=[uuid4()],
        )
    profile = _profile(ctx, provider="openai_chatgpt", api="responses", fallbacks=[uuid4()])
    monkeypatch.setattr(service, "_get_profile", AsyncMock(return_value=profile))
    with pytest.raises(BadRequestError, match="automatic fallbacks"):
        await service.update_profile(ctx, profile.id, ModelProfileUpdate(label="Renamed"))


def test_subscription_tokens_are_never_priced_as_a_metered_openai_api_bill() -> None:
    from pydantic_ai.usage import RequestUsage

    from app.agents.capabilities.budget import price_request

    usage = RequestUsage(input_tokens=1000, output_tokens=100)
    for provider in ["openai_chatgpt", "openai-chatgpt"]:
        assert price_request(usage, "gpt-4.1", provider) is None
    assert price_request(usage, "gpt-4.1", "openai") is not None


async def test_the_vault_source_refuses_a_registration_from_another_installation(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, registration, _, _ = setup
    row = MagicMock(
        id=uuid4(),
        owner_user_id=ctx.user_id,
        authorization_generation=uuid4(),
        kind="openai_chatgpt",
    )
    monkeypatch.setattr(plan.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.member_repo, "get", AsyncMock(return_value=MagicMock()))
    registration.host_id = uuid4()
    source = VaultChatGPTCredentials(
        organization_id=ctx.organization_id,
        secret_id=row.id,
        generation=row.authorization_generation,
    )
    with pytest.raises(BadRequestError, match="installation registration changed"):
        await source.load()


async def test_an_oversized_account_catalog_is_refused_while_streaming(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _ = setup
    row = MagicMock(id=uuid4(), authorization_generation=uuid4(), owner_user_id=ctx.user_id)
    monkeypatch.setattr(plan.OrganizationSecretService, "get_usable", AsyncMock(return_value=row))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "load", AsyncMock(return_value=grant()))
    monkeypatch.setattr(plan.VaultChatGPTCredentials, "assert_current", AsyncMock())
    original = ChatGPTPlanProvider
    huge = b'{"models": [' + b" " * (3 * 1024 * 1024) + b"]}"
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, content=huge))
    ) as client:
        monkeypatch.setattr(
            "app.agents.chatgpt_plan.ChatGPTPlanProvider",
            lambda source: original(source, http_client=client),
        )
        with pytest.raises(BadRequestError, match="excessive model catalog"):
            await plan.account_models(MagicMock(), ctx, row.id)


async def test_the_secret_service_lists_only_the_selected_chatgpt_accounts_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.organization_secret import OrganizationSecretService

    listed = AsyncMock(return_value=["gpt-x"])
    monkeypatch.setattr(plan, "account_models", listed)
    db, ctx, secret = MagicMock(), _ctx(), uuid4()
    assert await OrganizationSecretService(db).chatgpt_models(ctx, secret) == ["gpt-x"]
    listed.assert_awaited_once_with(db, ctx, secret)


@pytest.mark.security
@pytest.mark.parametrize("caller", [None, "another_member"])
async def test_account_catalog_refuses_other_members_before_constructing_a_provider(
    setup, monkeypatch: pytest.MonkeyPatch, caller: str | None
) -> None:
    from dataclasses import replace

    from app.core.exceptions import AuthorizationError

    ctx, _, _, _ = setup
    row = MagicMock(id=uuid4(), owner_user_id=ctx.user_id)
    read = AsyncMock(return_value=row)
    provider = MagicMock()
    monkeypatch.setattr(plan.OrganizationSecretService, "get_usable", read)
    monkeypatch.setattr("app.agents.chatgpt_plan.ChatGPTPlanProvider", provider)
    ctx = replace(ctx, user_id=None if caller is None else uuid4())
    with pytest.raises(AuthorizationError, match="grant owner"):
        await plan.account_models(MagicMock(), ctx, row.id)
    provider.assert_not_called()
