"""An org's OAuth app is shared; each member's resulting grant stays scoped."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.agents import mcp_oauth
from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import McpOAuthClientSecret, SecretKind, normalized_mcp_server
from app.core.vault import VaultScope, unseal
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.repositories import organization_secret_repo
from app.services import mcp_connection as module
from app.services.mcp_connection import McpConnectionService, resolve_auth_headers
from app.services.organization_secret import OrganizationSecretService, SecretSharingGuard
from tests.test_mcp_connections import (
    _allow_any_url,
    _base_payload,
    _connection,
    _oauth_connection,
    _seal_into,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def ctx():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


@pytest.fixture
def discovery(monkeypatch):
    _allow_any_url(monkeypatch)
    server = mcp_oauth.DiscoveredServer(
        authorization_endpoint="https://srv/authorize",
        token_endpoint="https://srv/token",
        registration_endpoint=None,
        resource="https://srv/mcp",
        scope="read",
        metadata=MagicMock(token_endpoint_auth_methods_supported=["client_secret_post"]),
    )
    monkeypatch.setattr(mcp_oauth, "discover", AsyncMock(return_value=server))
    monkeypatch.setattr(mcp_oauth, "register_client", AsyncMock(return_value=("dcr", None)))
    return server


@pytest.fixture
def service(monkeypatch):
    repo = MagicMock(
        get_by_name=AsyncMock(return_value=None), create=AsyncMock(), update=AsyncMock()
    )
    monkeypatch.setattr(module, "mcp_connection_repo", repo)
    return McpConnectionService(AsyncMock()), repo


async def test_shared_app_stages_source_identity_without_disclosing_secret(
    ctx, discovery, service, monkeypatch
):
    svc, repo = service
    secret_id, generation = uuid4(), uuid4()
    credentials = McpOAuthClientSecret(
        server_url="https://srv/mcp", client_id="shared-id", client_secret="shared-secret"
    )
    identity = AsyncMock(return_value=(credentials, secret_id, generation))
    monkeypatch.setattr(OrganizationSecretService, "mcp_oauth_client_identity", identity)
    url = await svc.oauth_start(user_id=ctx.user_id, ctx=ctx, name="Slack", url="https://srv/mcp")
    assert "shared-id" in url and "shared-secret" not in url
    payload = mcp_oauth.McpOAuthPayload.model_validate_json(
        unseal(
            repo.create.await_args.kwargs["oauth_pending_payload"],
            scope=VaultScope.user(ctx.user_id),
        )
    )
    assert payload.organization_oauth_client
    assert payload.account_source_organization_id == ctx.organization_id
    assert payload.account_source_secret_id == secret_id
    assert payload.account_source_generation == generation
    assert repo.create.await_args.kwargs["account_source_organization_id"] == ctx.organization_id
    mcp_oauth.register_client.assert_not_awaited()


@pytest.mark.parametrize("explicit", [False, True])
async def test_explicit_client_and_dcr_take_precedence(
    ctx, discovery, service, monkeypatch, explicit
):
    svc, _ = service
    if not explicit:
        monkeypatch.setattr(
            mcp_oauth,
            "discover",
            AsyncMock(
                return_value=replace(discovery, registration_endpoint="https://srv/register")
            ),
        )
    identity = AsyncMock(side_effect=AssertionError("Shared client should not be read"))
    monkeypatch.setattr(OrganizationSecretService, "mcp_oauth_client_identity", identity)
    url = await svc.oauth_start(
        user_id=ctx.user_id,
        ctx=ctx,
        name="MCP",
        url="https://srv/mcp",
        **({"client_id": "explicit"} if explicit else {}),
    )
    assert ("explicit" if explicit else "dcr") in url
    identity.assert_not_awaited()


async def test_missing_shared_client_is_actionable(ctx, discovery, service, monkeypatch):
    svc, repo = service
    monkeypatch.setattr(
        OrganizationSecretService, "mcp_oauth_client_identity", AsyncMock(return_value=None)
    )
    with pytest.raises(mcp_oauth.OAuthError, match=r"administrator.*Vault"):
        await svc.oauth_start(user_id=ctx.user_id, ctx=ctx, name="MCP", url="https://srv/mcp")
    repo.create.assert_not_awaited()


@pytest.mark.parametrize(
    "state", ["valid", "deleted", "rotated", "replaced", "other-org", "former-member", "no-source"]
)
async def test_grant_source_checks_current_org_membership_and_generation(ctx, monkeypatch, state):
    secret_id, generation = uuid4(), uuid4()
    payload = _base_payload(
        organization_oauth_client=True,
        account_source_organization_id=ctx.organization_id,
        account_source_secret_id=secret_id,
        account_source_generation=generation,
    )
    conn = _oauth_connection(payload, user_id=ctx.user_id)
    row = OrganizationSecret(id=secret_id, authorization_generation=generation)
    if state == "rotated":
        row.authorization_generation = uuid4()
    if state == "replaced":
        row.id = uuid4()
    if state == "no-source":
        payload.account_source_secret_id = None
    monkeypatch.setattr(
        module, "decider_context", AsyncMock(return_value=None if state == "former-member" else ctx)
    )
    monkeypatch.setattr(
        organization_secret_repo,
        "mcp_oauth_client",
        AsyncMock(return_value=None if state == "deleted" else row),
    )
    valid = await McpConnectionService(AsyncMock())._account_source_current(
        conn, payload, uuid4() if state == "other-org" else ctx.organization_id
    )
    assert valid is (state == "valid")


async def test_even_fresh_access_token_is_refused_after_source_revocation(ctx, monkeypatch):
    payload = _base_payload(
        organization_oauth_client=True,
        access_token="fresh",
        expires_at=None,
        account_source_organization_id=ctx.organization_id,
    )
    conn = _oauth_connection(payload)
    # No source id: refusal happens before any DB query, even with an unexpired token.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def transaction():
        yield AsyncMock()

    monkeypatch.setattr(module, "get_worker_db_context", transaction)
    assert await resolve_auth_headers(conn) is None


async def test_probe_exposes_only_availability(ctx, discovery, service, monkeypatch):
    svc, _ = service
    monkeypatch.setattr(
        organization_secret_repo,
        "mcp_oauth_client",
        AsyncMock(return_value=OrganizationSecret(id=uuid4())),
    )
    result = await svc.probe_sign_in("https://srv/mcp", ctx)
    assert result.model_dump() == {
        "sign_in": True,
        "registers_clients": False,
        "organization_client_available": True,
    }
    result = await svc.probe_sign_in("https://srv/mcp?transport=1", ctx)
    assert not result.organization_client_available


async def test_sharing_cannot_create_a_second_org_client(ctx, monkeypatch):
    from app.services import organization_secret as secrets_module

    monkeypatch.setattr(secrets_module, "hold_subject", AsyncMock())
    monkeypatch.setattr(
        organization_secret_repo,
        "mcp_oauth_client",
        AsyncMock(return_value=OrganizationSecret(id=uuid4())),
    )
    secret = OrganizationSecret(
        id=uuid4(), kind=SecretKind.MCP_OAUTH_CLIENT.value, mcp_oauth_server="https://srv/mcp"
    )
    with pytest.raises(AlreadyExistsError):
        await SecretSharingGuard().before_visibility(AsyncMock(), ctx, secret, Visibility.ORG)
    # Narrowing the audience does not ask for an organization-wide client.
    await SecretSharingGuard().before_visibility(AsyncMock(), ctx, secret, Visibility.PRIVATE)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@srv/mcp",
        "https://srv/mcp?token=secret",
        "https://srv/mcp#fragment",
        "file:///tmp/client",
        "https://srv:wrong/mcp",
    ],
)
def test_shared_identity_rejects_ambiguous_or_credential_urls(url):
    with pytest.raises(ValidationError):
        McpOAuthClientSecret(server_url=url, client_id="client")


def test_identity_normalization_retains_endpoint_and_masks_credentials():
    assert normalized_mcp_server("https://SRV:443/mcp/") == "https://srv/mcp"
    assert normalized_mcp_server("http://[::1]:8080/mcp/") == "http://[::1]:8080/mcp"
    secret = McpOAuthClientSecret(
        server_url="https://srv/mcp", client_id="id1234", client_secret="never-output"
    )
    assert secret.hint == "1234"
    assert "never-output" not in repr(secret)


@pytest.mark.parametrize("organization", ["current", "other", "absent"])
async def test_personal_tools_cannot_reuse_a_shared_client_in_another_org(
    ctx, monkeypatch, organization
):
    from app.agents.spec import PersonalMcpServerRef

    payload = _base_payload(
        organization_oauth_client=True,
        access_token="fresh",
        account_source_organization_id=ctx.organization_id,
    )
    conn = _oauth_connection(payload, user_id=ctx.user_id)
    monkeypatch.setattr(
        module.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[conn]),
    )
    monkeypatch.setattr(
        McpConnectionService,
        "_account_source_current",
        AsyncMock(return_value=organization == "current"),
    )
    headers = AsyncMock(return_value={"Authorization": "Bearer fresh"})
    monkeypatch.setattr(module, "resolve_auth_headers", headers)
    result = await module._own_specs(
        AsyncMock(),
        PersonalMcpServerRef(account="personal", catalog_key="notion"),
        user_id=ctx.user_id,
        organization_id=None if organization == "absent" else ctx.organization_id,
    )
    if organization == "current":
        assert not isinstance(result, str) and result[0].spec.recheck_source
    else:
        assert result == "unauthorized"
        headers.assert_not_awaited()


async def test_shared_client_revocation_stops_a_cached_toolset(ctx, monkeypatch):
    from contextlib import asynccontextmanager

    from app.agents.mcp import McpServerSpec
    from app.core.exceptions import AuthorizationError

    payload = _base_payload(
        organization_oauth_client=True, account_source_organization_id=ctx.organization_id
    )
    conn = _oauth_connection(payload, user_id=ctx.user_id, url=payload.server_url)
    monkeypatch.setattr(module.mcp_connection_repo, "get_by_id", AsyncMock(return_value=conn))
    current = AsyncMock(return_value=True)
    monkeypatch.setattr(McpConnectionService, "_account_source_current", current)

    @asynccontextmanager
    async def transaction():
        yield AsyncMock()

    monkeypatch.setattr(module, "get_worker_db_context", transaction)
    spec = McpServerSpec(
        name="notion",
        url=conn.url,
        source_connection_id=conn.id,
        authorization_generation=conn.authorization_generation,
        recheck_source=True,
    )
    check = module._delegated_source_check(
        spec, organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    await check()
    current.return_value = False
    with pytest.raises(AuthorizationError, match="OAuth client changed"):
        await check()


async def test_shared_client_tools_are_guarded_even_for_an_ordinary_chat(ctx, monkeypatch):
    from pydantic_ai.toolsets import FunctionToolset

    from app.agents.mcp import AuthorityChecked
    from app.agents.spec import PersonalMcpServerRef

    payload = _base_payload(
        organization_oauth_client=True, account_source_organization_id=ctx.organization_id
    )
    conn = _oauth_connection(payload, user_id=ctx.user_id)
    monkeypatch.setattr(
        module.mcp_connection_repo, "get_org_scoped_by_ids", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        module.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[conn]),
    )
    monkeypatch.setattr(
        McpConnectionService, "_account_source_current", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        module, "resolve_auth_headers", AsyncMock(return_value={"Authorization": "Bearer token"})
    )

    async def probe(specs):
        return [(spec, FunctionToolset()) for spec in specs]

    monkeypatch.setattr(module, "probe_toolsets", probe)
    result = await module.build_toolsets_for_agent(
        AsyncMock(),
        organization_id=ctx.organization_id,
        refs=[PersonalMcpServerRef(account="personal", catalog_key="notion")],
        sender_user_id=ctx.user_id,
    )
    assert len(result.toolsets) == 1
    assert isinstance(result.toolsets[0], AuthorityChecked)


@pytest.mark.parametrize("valid", [True, False])
async def test_shared_client_callback_rechecks_source_and_promotes_metadata_atomically(
    ctx, service, monkeypatch, valid
):
    svc, repo = service
    payload = _base_payload(
        organization_oauth_client=True,
        account_source_organization_id=ctx.organization_id,
        code_verifier="pkce",
    )
    conn = _connection(auth_type="oauth", oauth_state="state")
    conn.oauth_pending_payload = _seal_into(conn, payload.model_dump_json())
    repo.get_by_oauth_state = AsyncMock(return_value=conn)
    repo.update.return_value = conn
    current = AsyncMock(return_value=valid)
    monkeypatch.setattr(svc, "_account_source_current", current)
    exchange = AsyncMock(
        return_value=(payload.model_copy(update={"access_token": SecretStr("fresh")}), ["read"])
    )
    monkeypatch.setattr(module, "_complete_mcp_flow", exchange)
    monkeypatch.setattr(svc, "_probe", AsyncMock(return_value=(conn, [], None)))
    if valid:
        assert await svc.oauth_callback(state="state", code="code") is conn
        assert (
            repo.update.await_args.kwargs["update_data"]["account_source_organization_id"]
            == ctx.organization_id
        )
    else:
        with pytest.raises(mcp_oauth.OAuthError, match="OAuth client changed"):
            await svc.oauth_callback(state="state", code="code")
        exchange.assert_not_awaited()


async def test_personal_consent_cannot_claim_another_user_identity(ctx, service):
    from app.core.exceptions import AuthorizationError

    svc, repo = service
    with pytest.raises(AuthorizationError, match="own active organization"):
        await svc.oauth_start(user_id=uuid4(), ctx=ctx, name="MCP", url="https://srv/mcp")
    repo.get_by_name.assert_not_awaited()
