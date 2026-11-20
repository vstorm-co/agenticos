"""A rotating credential commits independently and is never sent to a stale binding."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from mcp.shared.auth import OAuthToken
from pydantic import SecretStr

from app.core.permissions import Perm
from app.services import mcp_connection as service
from app.services.mcp_connection import OAuthError
from tests.test_mcp_connections import _base_payload, _connection, _oauth_connection, _seal_into

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "field",
    [
        "url",
        "user_id",
        "auth_type",
        "is_enabled",
        "purpose",
        "granted_scopes",
        "authorization_generation",
    ],
)
async def test_a_changed_binding_never_receives_the_rotated_credential(monkeypatch, field):
    payload = _base_payload(access_token="old", refresh_token="rotate", expires_at=0)
    before = _oauth_connection(payload, purpose="mcp", granted_scopes=["read"])
    values = {
        "url": "https://other.example/mcp",
        "user_id": uuid4(),
        "auth_type": "bearer",
        "is_enabled": False,
        "purpose": "portal",
        "granted_scopes": ["write"],
        "authorization_generation": uuid4(),
    }
    after = _oauth_connection(
        payload,
        id=before.id,
        user_id=before.user_id,
        purpose="mcp",
        granted_scopes=["read"],
        authorization_generation=before.authorization_generation,
    )
    setattr(after, field, values[field])
    lock, rotate = AsyncMock(return_value=after), AsyncMock()
    monkeypatch.setattr(service.mcp_connection_repo, "get_for_token_refresh", lock)
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", rotate)

    @asynccontextmanager
    async def context():
        yield object()

    monkeypatch.setattr(service, "get_worker_db_context", context)
    assert await service._oauth_access_token(before) is None
    rotate.assert_not_awaited()


async def test_repeated_cancellation_waits_for_the_new_pair_to_commit(monkeypatch):
    connection = _oauth_connection(
        _base_payload(access_token="old", refresh_token="rotate", expires_at=0)
    )
    committing, release = asyncio.Event(), asyncio.Event()
    commits = []
    update = AsyncMock()
    monkeypatch.setattr(
        service.mcp_connection_repo, "get_for_token_refresh", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(service.mcp_connection_repo, "update", update)
    monkeypatch.setattr(
        service.mcp_oauth,
        "refresh_tokens",
        AsyncMock(
            return_value=OAuthToken(access_token="new", refresh_token="next", expires_in=3600)
        ),
    )

    @asynccontextmanager
    async def context():
        yield object()
        committing.set()
        await release.wait()
        commits.append(update.await_args.kwargs["update_data"]["oauth_payload"])

    monkeypatch.setattr(service, "get_worker_db_context", context)
    async with asyncio.timeout(3):
        task = asyncio.create_task(service._oauth_access_token(connection))
        await committing.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(commits) == 1
    assert (
        service._decode_payload(connection, commits[0]).refresh_token.get_secret_value() == "next"
    )


async def test_commit_failure_is_not_reported_as_a_usable_token(monkeypatch):
    connection = _oauth_connection(
        _base_payload(access_token="old", refresh_token="rotate", expires_at=0)
    )
    monkeypatch.setattr(service, "_rotate_token", AsyncMock(return_value="new"))
    monkeypatch.setattr(
        service.mcp_connection_repo, "get_for_token_refresh", AsyncMock(return_value=connection)
    )

    @asynccontextmanager
    async def context():
        yield object()
        raise RuntimeError("commit failed after rotation")

    monkeypatch.setattr(service, "get_worker_db_context", context)
    with pytest.raises(RuntimeError, match="commit failed"):
        await service._oauth_access_token(connection)


@pytest.mark.parametrize(
    "failure", [RuntimeError("persistence uncertain"), asyncio.CancelledError()]
)
async def test_settlement_failure_preserves_the_request_cancellation(monkeypatch, failure):
    connection = _oauth_connection(
        _base_payload(access_token="old", refresh_token="rotate", expires_at=0)
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def transaction(connection, *, rejected: str | None = None):
        assert rejected is None
        entered.set()
        await release.wait()
        raise failure

    monkeypatch.setattr(service, "_refresh_transaction", transaction)
    async with asyncio.timeout(3):
        task = asyncio.create_task(service._oauth_access_token(connection))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize(
    "change", ["no_payload", "no_access", "unbound_account", "revoked_client", "no_refresh"]
)
async def test_refresh_never_contacts_a_provider_without_the_original_live_grant(
    monkeypatch, change
):
    payload = _base_payload(
        access_token=None if change == "no_access" else "old",
        refresh_token=None if change == "no_refresh" else "refresh",
        expires_at=0,
        account_source_organization_id=uuid4() if change == "revoked_client" else None,
    )
    connection = _oauth_connection(
        payload, purpose="account" if change in {"unbound_account", "revoked_client"} else "mcp"
    )
    if change == "no_payload":
        connection.oauth_payload = None
    monkeypatch.setattr(
        service.McpConnectionService, "_account_source_current", AsyncMock(return_value=False)
    )
    refresh = AsyncMock()
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    assert await service._rotate_token(AsyncMock(), connection) is None
    refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "change", ["current", "legacy", "missing_payload", "missing_client", "missing_generation"]
)
def test_google_account_source_metadata_is_recovered_only_from_a_verifiable_grant(change):
    from tests.test_connected_accounts import (
        SOURCE_GENERATION,
        SOURCE_ORG,
        SOURCE_SECRET,
        _account,
        _payload,
        _sealed,
    )

    account = _account(account_source_organization_id=None)
    payload = (
        _payload(account_source_organization_id=None)
        if change == "legacy"
        else _payload(account_source_secret_id=None)
        if change == "missing_client"
        else _payload(account_source_generation=None)
        if change == "missing_generation"
        else _payload()
    )
    account.oauth_payload = None if change == "missing_payload" else _sealed(account, payload)
    assert service.account_client_identity(account) == (
        (SOURCE_ORG, SOURCE_SECRET, SOURCE_GENERATION) if change == "current" else None
    )
    assert service.account_source_organization(account) == (
        None if change in {"legacy", "missing_payload"} else SOURCE_ORG
    )


def _org_account(org, **overrides):
    """A member's Google account whose client is the organization's app."""
    payload = _base_payload(
        token_endpoint="https://oauth2.googleapis.com/token",
        provider="google",
        client_id="org-client",
        client_secret=None,
        access_token="old",
        refresh_token="rt",
        expires_at=0,
        account_source_organization_id=org,
        account_source_secret_id=uuid4(),
        account_source_generation=uuid4(),
    )
    return _oauth_connection(
        payload,
        purpose="account",
        scope="org",
        organization_id=org,
        **overrides,
    )


def _live_org_app(monkeypatch, current: dict, org):
    """The organization's Google app as it stands now: `current` is edited to rotate it."""

    async def app(self, organization_id, *, kind):
        assert organization_id == org
        value = SimpleNamespace(
            client_id=current["client_id"], client_secret=SecretStr(current["secret"])
        )
        return value, uuid4(), uuid4()

    monkeypatch.setattr(service.OrganizationSecretService, "oauth_app_identity_for_org", app)
    # The owner checks are a separate concern, covered in test_connected_accounts.
    monkeypatch.setattr(
        service.McpConnectionService, "_account_source_current", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        service.McpConnectionService, "_is_current_member", AsyncMock(return_value=True)
    )


async def test_a_rotated_org_app_secret_reaches_a_members_next_refresh(monkeypatch):
    org = uuid4()
    connection = _org_account(org)
    current = {"client_id": "org-client", "secret": "first"}
    _live_org_app(monkeypatch, current, org)
    refresh = AsyncMock(return_value=OAuthToken(access_token="AT", expires_in=3600))
    update = AsyncMock(return_value=connection)
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    monkeypatch.setattr(service.mcp_connection_repo, "update", update)

    await service._rotate_token(AsyncMock(), connection)
    current["secret"] = "rotated"
    await service._rotate_token(AsyncMock(), connection)

    secrets_spent = [call.kwargs["client_secret"] for call in refresh.await_args_list]
    assert secrets_spent == ["first", "rotated"]
    stored = service._decode_payload(
        connection, update.await_args.kwargs["update_data"]["oauth_payload"]
    )
    assert stored is not None
    assert stored.client_secret is None
    assert stored.account_source_organization_id == org


async def test_a_grant_reads_the_org_apps_current_secret(monkeypatch):
    org = uuid4()
    connection = _org_account(org)
    current = {"client_id": "org-client", "secret": "rotated"}
    _live_org_app(monkeypatch, current, org)

    grant = await service.McpConnectionService(AsyncMock()).account_grant(
        connection, organization_id=org
    )

    assert grant is not None
    assert grant.client_id == "org-client"
    assert grant.client_secret.get_secret_value() == "rotated"


async def test_a_switched_org_client_is_not_refreshed_with_the_old_grant(monkeypatch):
    org = uuid4()
    connection = _org_account(org)
    current = {"client_id": "another-client", "secret": "x"}
    _live_org_app(monkeypatch, current, org)
    refresh = AsyncMock()
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)

    grant = await service.McpConnectionService(AsyncMock()).account_grant(
        connection, organization_id=org
    )

    assert grant is None
    refresh.assert_not_awaited()


async def test_a_public_client_refreshes_without_a_secret(monkeypatch):
    # No org app and no secret: the client is public, and a refresh with no
    # client secret is the normal case, not a refusal.
    connection = _oauth_connection(
        _base_payload(
            client_id="public-client",
            client_secret=None,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
        )
    )
    refresh = AsyncMock(return_value=OAuthToken(access_token="AT", expires_in=3600))
    update = AsyncMock(return_value=connection)
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    monkeypatch.setattr(service.mcp_connection_repo, "update", update)

    assert await service._rotate_token(AsyncMock(), connection) == "AT"
    assert refresh.await_args.kwargs["client_id"] == "public-client"
    assert refresh.await_args.kwargs["client_secret"] is None


async def test_an_mcp_connection_on_an_org_client_reads_the_rotated_secret(monkeypatch):
    org = uuid4()
    connection = _oauth_connection(
        _base_payload(
            client_id="org-client",
            client_secret=None,
            client_org_id=org,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
        ),
        purpose="mcp",
        scope="org",
        organization_id=org,
    )
    current = {"client_id": "org-client", "secret": "first"}
    _live_org_app(monkeypatch, current, org)
    refresh = AsyncMock(return_value=OAuthToken(access_token="AT", expires_in=3600))
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    monkeypatch.setattr(service.mcp_connection_repo, "update", AsyncMock(return_value=connection))

    await service._rotate_token(AsyncMock(), connection)
    current["secret"] = "rotated"
    await service._rotate_token(AsyncMock(), connection)

    secrets_spent = [call.kwargs["client_secret"] for call in refresh.await_args_list]
    assert secrets_spent == ["first", "rotated"]


async def test_an_mcp_connection_whose_org_app_is_gone_is_not_refreshed(monkeypatch):
    org = uuid4()
    connection = _oauth_connection(
        _base_payload(
            client_id="org-client",
            client_secret=None,
            client_org_id=org,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
        ),
        purpose="mcp",
        scope="org",
        organization_id=org,
    )

    async def gone(self, organization_id, *, kind):
        raise service.NotFoundError("no org app")

    monkeypatch.setattr(service.OrganizationSecretService, "oauth_app_identity_for_org", gone)
    refresh = AsyncMock()
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)

    assert await service._rotate_token(AsyncMock(), connection) is None
    refresh.assert_not_awaited()


def test_only_the_listed_google_hosts_count_as_google_mcp_servers():
    assert service.is_google_mcp("https://calendarmcp.googleapis.com/mcp/v1")
    for url in [
        # A bucket anyone can create under the Google domain, serving its own metadata.
        "https://storage.googleapis.com/attacker-bucket/mcp/v1",
        "https://attacker-bucket.storage.googleapis.com/mcp/v1",
        "https://calendarmcp.googleapis.com.evil.test/mcp/v1",
        "http://calendarmcp.googleapis.com/mcp/v1",
    ]:
        assert not service.is_google_mcp(url), url


async def test_an_org_client_is_only_ever_sent_to_googles_endpoints(monkeypatch):
    # Discovery names its own token endpoint for a Google-hosted server; the org secret
    # must still go only to Google's.
    org = uuid4()
    evil = "https://attacker-bucket.storage.googleapis.com/token"
    server = service.mcp_oauth.DiscoveredServer(
        authorization_endpoint=evil.replace("/token", "/authorize"),
        token_endpoint=evil,
        registration_endpoint=None,
        resource="https://calendarmcp.googleapis.com/mcp/v1",
        scope=None,
        metadata=MagicMock(),
    )
    staged: dict = {}
    authorize_with: dict = {}

    async def stage(self, **kwargs):
        staged.update(kwargs)

    def authorize(server_arg, **kwargs):
        authorize_with["server"] = server_arg
        return "https://accounts.google.com/o/oauth2/v2/auth?x"

    monkeypatch.setattr(service, "_checked_url", AsyncMock(side_effect=lambda url: url))
    monkeypatch.setattr(service.mcp_oauth, "discover", AsyncMock(return_value=server))
    monkeypatch.setattr(
        service, "_refuse_a_client_this_server_will_not_authenticate", lambda s: None
    )
    monkeypatch.setattr(service.mcp_oauth, "authorization_url", authorize)
    monkeypatch.setattr(service.McpConnectionService, "_stage_pending_oauth", stage)

    await service.McpConnectionService(AsyncMock())._oauth_start(
        name="calendar",
        url="https://calendarmcp.googleapis.com/mcp/v1",
        existing=None,
        vault_scope=None,
        create=AsyncMock(),
        client_id="org-client",
        client_org_id=org,
    )

    payload = staged["payload"]
    assert payload.token_endpoint == service.google_oauth.TOKEN_ENDPOINT
    assert payload.authorization_endpoint == service.google_oauth.AUTHORIZE_ENDPOINT
    assert (
        authorize_with["server"].authorization_endpoint == service.google_oauth.AUTHORIZE_ENDPOINT
    )


async def test_a_refresh_of_an_org_client_spends_the_secret_at_googles_endpoint_only(monkeypatch):
    org = uuid4()
    evil = "https://attacker-bucket.storage.googleapis.com/token"
    connection = _oauth_connection(
        _base_payload(
            client_id="org-client",
            client_secret=None,
            client_org_id=org,
            token_endpoint=evil,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
        ),
        purpose="mcp",
        scope="user",
        user_id=uuid4(),
    )
    current = {"client_id": "org-client", "secret": "org-secret"}
    _live_org_app(monkeypatch, current, org)
    refresh = AsyncMock(return_value=OAuthToken(access_token="AT", expires_in=3600))
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    monkeypatch.setattr(service.mcp_connection_repo, "update", AsyncMock(return_value=connection))

    assert await service._rotate_token(AsyncMock(), connection) == "AT"
    assert refresh.await_args.kwargs["token_endpoint"] == service.google_oauth.TOKEN_ENDPOINT
    assert refresh.await_args.kwargs["client_secret"] == "org-secret"


async def test_a_member_who_left_the_organization_cannot_refresh_on_its_client(monkeypatch):
    org = uuid4()
    connection = _oauth_connection(
        _base_payload(
            client_id="org-client",
            client_secret=None,
            client_org_id=org,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
        ),
        purpose="mcp",
        scope="user",
        user_id=uuid4(),
    )
    current = {"client_id": "org-client", "secret": "org-secret"}
    _live_org_app(monkeypatch, current, org)
    monkeypatch.setattr(
        service.McpConnectionService, "_is_current_member", AsyncMock(return_value=False)
    )
    refresh = AsyncMock()
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)

    assert await service._rotate_token(AsyncMock(), connection) is None
    refresh.assert_not_awaited()


async def _requested_scope_for(monkeypatch, metadata_scope: str) -> tuple[str, str]:
    """(scope staged on the pending payload, scope put to the consent URL)."""
    org = uuid4()
    server = service.mcp_oauth.DiscoveredServer(
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint=service.google_oauth.TOKEN_ENDPOINT,
        registration_endpoint=None,
        resource="https://calendarmcp.googleapis.com/mcp/v1",
        scope=metadata_scope,
        metadata=MagicMock(),
    )
    staged: dict = {}
    requested: dict = {}

    async def stage(self, **kwargs):
        staged.update(kwargs)

    def authorize(server_arg, **kwargs):
        requested["scope"] = server_arg.scope
        return "https://accounts.google.com/o/oauth2/v2/auth?x"

    monkeypatch.setattr(service, "_checked_url", AsyncMock(side_effect=lambda url: url))
    monkeypatch.setattr(service.mcp_oauth, "discover", AsyncMock(return_value=server))
    monkeypatch.setattr(
        service, "_refuse_a_client_this_server_will_not_authenticate", lambda s: None
    )
    monkeypatch.setattr(service.mcp_oauth, "authorization_url", authorize)
    monkeypatch.setattr(service.McpConnectionService, "_stage_pending_oauth", stage)

    await service.McpConnectionService(AsyncMock())._oauth_start(
        name="chat",
        url="https://chatmcp.googleapis.com/mcp/v1",
        existing=None,
        vault_scope=None,
        create=AsyncMock(),
        client_id="org-client",
        client_org_id=org,
    )
    return staged["payload"].scope, requested["scope"]


async def test_an_org_client_requests_only_google_scopes_from_the_metadata(monkeypatch):
    # A Google scope the server names is kept; a foreign scope in the same list is not.
    staged, requested = await _requested_scope_for(
        monkeypatch,
        "https://www.googleapis.com/auth/chat.messages https://attacker.example/x",
    )
    assert staged == "https://www.googleapis.com/auth/chat.messages"
    assert requested == "https://www.googleapis.com/auth/chat.messages"


async def test_an_org_client_falls_back_when_the_metadata_names_no_google_scope(monkeypatch):
    staged, requested = await _requested_scope_for(
        monkeypatch, "https://attacker.example/everything https://attacker.example/x"
    )
    fixed = " ".join(service.google_oauth.ACCOUNT_SCOPES)
    assert staged == fixed
    assert requested == fixed


async def test_an_org_client_keeps_a_google_scope_from_the_metadata_unchanged(monkeypatch):
    staged, requested = await _requested_scope_for(
        monkeypatch, "openid https://www.googleapis.com/auth/calendar"
    )
    assert staged == "openid https://www.googleapis.com/auth/calendar"
    assert requested == staged


async def test_an_org_account_is_pinned_to_googles_token_endpoint_like_an_org_mcp_client(
    monkeypatch,
):
    # The account row has no client_org_id, but its client is the org app, so its
    # refresh is pinned by the same rule that decides where the org secret goes.
    org = uuid4()
    evil = "https://attacker-bucket.storage.googleapis.com/token"
    connection = _oauth_connection(
        _base_payload(
            token_endpoint=evil,
            provider="google",
            client_id="org-client",
            client_secret=None,
            access_token="old",
            refresh_token="rt",
            expires_at=0,
            account_source_organization_id=org,
            account_source_secret_id=uuid4(),
            account_source_generation=uuid4(),
        ),
        purpose="account",
        scope="org",
        organization_id=org,
    )
    current = {"client_id": "org-client", "secret": "org-secret"}
    _live_org_app(monkeypatch, current, org)
    refresh = AsyncMock(return_value=OAuthToken(access_token="AT", expires_in=3600))
    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    monkeypatch.setattr(service.mcp_connection_repo, "update", AsyncMock(return_value=connection))

    assert await service._rotate_token(AsyncMock(), connection) == "AT"
    assert refresh.await_args.kwargs["token_endpoint"] == service.google_oauth.TOKEN_ENDPOINT
    assert refresh.await_args.kwargs["client_secret"] == "org-secret"


@pytest.mark.parametrize("initiator_authority", [None, "without_mcp_manage"])
async def test_a_removed_admin_cannot_finish_an_org_connection_they_started(
    monkeypatch, initiator_authority
):
    # The person who started the org flow has since left, or lost MCP_MANAGE.
    org = uuid4()
    initiator = uuid4()
    pending = _connection(auth_type="oauth", scope="org", organization_id=org, oauth_state="s")
    pending.oauth_pending_payload = _seal_into(
        pending, _base_payload(client_id="org-client", initiator_id=initiator).model_dump_json()
    )
    authority = (
        None
        if initiator_authority is None
        else SimpleNamespace(has=lambda perm: perm is not Perm.MCP_MANAGE)
    )
    decider = AsyncMock(return_value=authority)
    monkeypatch.setattr(service, "decider_context", decider)
    monkeypatch.setattr(
        service.mcp_connection_repo, "get_by_oauth_state", AsyncMock(return_value=pending)
    )
    complete = AsyncMock()
    monkeypatch.setattr(service, "_complete_mcp_flow", complete)

    with pytest.raises(OAuthError, match="organization access changed"):
        await service.McpConnectionService(AsyncMock()).oauth_callback(state="s", code="c")

    decider.assert_awaited_once()
    assert decider.await_args.kwargs["user_id"] == initiator
    complete.assert_not_awaited()
