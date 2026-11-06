"""A rotating credential commits independently and is never sent to a stale binding."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mcp.shared.auth import OAuthToken

from app.services import mcp_connection as service
from tests.test_mcp_connections import _base_payload, _oauth_connection

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
