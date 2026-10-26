"""Real row locks and commits around externally rotating OAuth credentials."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from mcp.shared.auth import OAuthToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import mcp_connection_repo
from app.services import mcp_connection as service
from tests.test_mcp_connections import _base_payload

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _rows(db: AsyncSession, *, portal: bool = False) -> list[McpConnection]:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    rows = []
    for index in range(1 if portal else 2):
        row = McpConnection(
            id=uuid4(),
            scope="org",
            organization_id=org.id,
            created_by_user_id=user.id,
            name=f"service-{index}",
            url="https://srv/mcp",
            auth_type="oauth",
            is_enabled=True,
            secret_key_version=1,
            purpose="portal" if portal else "mcp",
            portal_key="google" if portal else None,
        )
        payload = _base_payload(access_token="old", refresh_token=f"old-{index}", expires_at=0)
        row.oauth_payload = service._seal_for(row, payload.model_dump_json()).ciphertext
        db.add(row)
        rows.append(row)
    await db.commit()
    return rows


def _independent_context(monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    monkeypatch.setattr(service, "get_worker_db_context", context)


async def test_reverse_binding_order_and_outer_rollback_keep_each_rotated_pair(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await _rows(db)
    _independent_context(monkeypatch, engine)
    reached, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def refresh(**kwargs: object) -> OAuthToken:
        nonlocal calls
        calls += 1
        if calls == 2:
            reached.set()
        await release.wait()
        return OAuthToken(access_token="new", refresh_token="next", expires_in=3600)

    monkeypatch.setattr(service.mcp_oauth, "refresh_tokens", refresh)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare(ids: list[UUID]) -> None:
        async with factory() as outer:
            for connection_id in ids:
                connection = await mcp_connection_repo.get_by_id(outer, connection_id)
                assert connection is not None
                assert await service._oauth_access_token(connection) == "new"
            # A later failure in run preparation must not undo either provider rotation.
            await outer.rollback()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(prepare([row.id for row in rows]))
        group.create_task(prepare([row.id for row in reversed(rows)]))
        await reached.wait()
        release.set()
    assert calls == 2
    for row in rows:
        stored = await db.scalar(
            select(McpConnection.oauth_payload).where(McpConnection.id == row.id)
        )
        payload = service._decode_payload(row, stored)
        assert payload is not None and payload.refresh_token is not None
        assert payload.refresh_token.get_secret_value() == "next"


async def test_a_portal_poll_claim_does_not_block_its_credential_refresh(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    [row] = await _rows(db, portal=True)
    _independent_context(monkeypatch, engine)
    monkeypatch.setattr(
        service.mcp_oauth,
        "refresh_tokens",
        AsyncMock(
            return_value=OAuthToken(access_token="new", refresh_token="next", expires_in=3600)
        ),
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with asyncio.timeout(10), factory() as poller, factory() as other:
        kwargs = {
            "connection_id": row.id,
            "portal_keys": ["google"],
            "not_polled_since": datetime.now(UTC),
        }
        grant = await mcp_connection_repo.claim_portal_grant_to_poll(poller, **kwargs)
        assert grant is not None
        assert await mcp_connection_repo.claim_portal_grant_to_poll(other, **kwargs) is None
        assert await service._oauth_access_token(grant) == "new"
        await service.McpConnectionService(poller).store_poll_cursor(
            grant, cursor={"history_id": "9"}
        )
        await poller.rollback()
        await other.rollback()
        reread = await mcp_connection_repo.get_by_id(other, row.id)
        assert reread is not None and reread.poll_cursor is None
        payload = service._decode_payload(reread, reread.oauth_payload)
        assert payload is not None and payload.access_token is not None
        assert payload.access_token.get_secret_value() == "new"
        assert await mcp_connection_repo.claim_portal_grant_to_poll(other, **kwargs) is not None


async def test_oauth_renewal_does_not_push_servers_to_the_back_of_the_health_queue(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await _rows(db)
    oldest, newer = rows
    oldest.health_checked_at = datetime(2020, 1, 1, tzinfo=UTC)
    newer.health_checked_at = datetime(2021, 1, 1, tzinfo=UTC)
    await db.commit()
    _independent_context(monkeypatch, engine)
    monkeypatch.setattr(
        service.mcp_oauth,
        "refresh_tokens",
        AsyncMock(
            return_value=OAuthToken(access_token="new", refresh_token="next", expires_in=3600)
        ),
    )
    await service.sweep_oauth_connections(db)
    assert oldest.last_checked_at is not None and oldest.last_checked_at.year > 2021
    assert [row.id for row in await mcp_connection_repo.list_org_servers_to_check(db, limit=1)] == [
        oldest.id
    ]
    await service._record_check(db, oldest, [], None)
    assert [row.id for row in await mcp_connection_repo.list_org_servers_to_check(db, limit=1)] == [
        newer.id
    ]


async def test_a_mailbox_sql_failure_rolls_back_its_work_and_does_not_poison_the_next_tenant(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import text

    from app.worker.tasks import trigger_tasks

    first = (await _rows(db, portal=True))[0]
    second = (await _rows(db, portal=True))[0]
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seen: list[UUID] = []

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    async def poll(session: AsyncSession, grant: McpConnection, source: str) -> int:
        seen.append(grant.id)
        if len(seen) == 1:
            await session.execute(text("SELECT 1 / 0"))
        await service.McpConnectionService(session).store_poll_cursor(
            grant, cursor={"history_id": "9"}
        )
        return 0

    monkeypatch.setattr(trigger_tasks, "get_worker_db_context", context)
    monkeypatch.setattr(trigger_tasks, "_ensure_trigger_dedupe", AsyncMock())
    monkeypatch.setattr(trigger_tasks, "_poll_one_grant", poll)
    async with asyncio.timeout(10):
        await trigger_tasks.poll_portal_grants()
    assert set(seen) == {first.id, second.id}
    failed = await db.get(McpConnection, seen[0], populate_existing=True)
    succeeded = await db.get(McpConnection, seen[1], populate_existing=True)
    assert failed is not None and succeeded is not None
    assert failed.poll_cursor is None and failed.last_status == "error"
    assert failed.polled_at is not None
    assert succeeded.poll_cursor == {"history_id": "9"} and succeeded.polled_at is not None
