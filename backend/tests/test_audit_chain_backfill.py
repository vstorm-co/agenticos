"""Backfilling the audit hash chain over entries that predate it.

The runtime path is covered against Postgres in
`tests/integration/test_audit_hash_chain.py`; this covers the other half of #1622,
which no runtime test can reach: migration `0079_audit_hash_chain` walking a table
that already holds entries and giving each one a `seq`, a `prev_hash` and an
`entry_hash` such that the trail verifies afterwards.

So it drives real Alembic against a database of its own: upgrade to the revision
before the chain existed, insert entries the old way (several organizations and the
deployment-wide chain), upgrade through `0079`, and assert every chain the backfill
produced verifies through the same `AuditService` an operator's `audit-verify`
would use. The database is this module's and this pid's, created and dropped here,
for the reasons `tests/test_migrations.py` sets out at length.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio

BACKFILL_DATABASE = f"agenticos_audit_backfill_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_REVISION_BEFORE_CHAIN = "0078_local_services"

_ORG_A = uuid.uuid4()
_ORG_B = uuid.uuid4()
_BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

# Several chains, interleaved in write order, so the backfill's global `seq` and its
# per-organization linkage are exercised together: three tenants and the
# deployment-wide chain (a NULL organization), each expected to verify on its own.
_ENTRIES = [
    (_ORG_A, "agent.created", {"fields": ["name"], "version": 1}),
    (None, "approval.expired", None),
    (_ORG_B, "org.member.invited", {"email_domain": "example.com"}),
    (_ORG_A, "agent.published", {"version": 2}),
    (None, "rag.source.added", {"source": "drive"}),
    (_ORG_B, "org.settings.updated", {"fields": ["name", "budget"]}),
    (_ORG_A, "agent.deleted", None),
]


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _async_url(database: str) -> str:
    return f"{settings.DATABASE_URL.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": BACKFILL_DATABASE},
        timeout=120,
    )


def _outside_a_transaction(url: str, statement: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _server_reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _insert_pre_chain_entries() -> None:
    """Insert the entries the old way - no seq, prev_hash or entry_hash, which do
    not exist at this revision."""
    engine = create_engine(_url(BACKFILL_DATABASE))
    statement = text(
        "INSERT INTO app_admin_audit_logs "
        "(id, actor_user_id, impersonator_user_id, organization_id, action, "
        " target_type, target_id, details, ip_address, created_at) "
        "VALUES (:id, :actor, NULL, :org, :action, NULL, NULL, "
        " CAST(:details AS JSONB), :ip, :created_at)"
    )
    try:
        with engine.begin() as connection:
            for index, (org, action, details) in enumerate(_ENTRIES):
                connection.execute(
                    statement,
                    {
                        "id": uuid.uuid4(),
                        "actor": uuid.uuid4(),
                        "org": org,
                        "action": action,
                        "details": json.dumps(details) if details is not None else None,
                        "ip": "203.0.113.9",
                        "created_at": _BASE_TIME + timedelta(minutes=index),
                    },
                )
    finally:
        engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _backfilled_database() -> Iterator[None]:
    maintenance = _url(_MAINTENANCE_DATABASE)
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{BACKFILL_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{BACKFILL_DATABASE}"')
    try:
        before = _alembic("upgrade", _REVISION_BEFORE_CHAIN)
        assert before.returncode == 0, (
            f"upgrade to {_REVISION_BEFORE_CHAIN} failed:\n{before.stderr}"
        )
        _insert_pre_chain_entries()
        after = _alembic("upgrade", "head")
        assert after.returncode == 0, f"upgrade through 0079 failed:\n{after.stderr}"
        yield
    finally:
        _outside_a_transaction(maintenance, drop)


async def _verifications() -> list:
    engine = create_async_engine(_async_url(BACKFILL_DATABASE))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            return await AuditService(session).verify_all_chains()
    finally:
        await engine.dispose()


async def test_every_backfilled_chain_verifies() -> None:
    results = {result.organization_id: result for result in await _verifications()}

    assert all(result.first_break is None for result in results.values())
    assert results[_ORG_A].entries_checked == 3
    assert results[_ORG_B].entries_checked == 2
    assert results[None].entries_checked == 2


async def test_the_backfill_assigns_a_unique_ordinal_and_seals_the_head() -> None:
    engine = create_async_engine(_async_url(BACKFILL_DATABASE))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT seq, prev_hash, entry_hash, organization_id "
                        "FROM app_admin_audit_logs ORDER BY seq"
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    seqs = [row.seq for row in rows]
    assert seqs == list(range(1, len(_ENTRIES) + 1))  # a global, gapless ordinal
    assert all(row.entry_hash for row in rows)  # every entry sealed

    # Exactly one head (null prev_hash) per chain, and no chain left unsealed.
    heads_per_org: dict[object, int] = {}
    for row in rows:
        if row.prev_hash is None:
            heads_per_org[row.organization_id] = heads_per_org.get(row.organization_id, 0) + 1
    assert all(count == 1 for count in heads_per_org.values())
    assert set(heads_per_org) == {_ORG_A, _ORG_B, None}
