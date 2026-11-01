"""The scheduled memory sweep (#2090): changed scopes only, one failure never stops the rest."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import person_owner_key
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.services.memory import claims
from app.worker.tasks import memory_tasks

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _own_session(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> None:
    @asynccontextmanager
    async def reuse():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", reuse)


async def _written(db: AsyncSession):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    key = person_owner_key(user.id)
    for statement in ("Prefers X", "prefers x"):
        await claim_repo.create(
            db,
            organization_id=org.id,
            scope_key=key,
            agent_id=None,
            subject="channel",
            statement=statement,
            kind="fact",
            origin="agent",
            status="current",
            observed_at=datetime.now(UTC),
        )
    await claim_repo.bump_revision(db, organization_id=org.id, scope_key=key)
    return org, key


async def test_a_changed_scope_is_folded_once_and_an_unchanged_one_costs_nothing(
    db: AsyncSession,
) -> None:
    org, key = await _written(db)

    first = await memory_tasks.consolidate_memory()
    second = await memory_tasks.consolidate_memory()

    assert first == 1 and second == 0
    live = await claim_repo.list_in_scopes(
        db, organization_id=org.id, scopes=[ClaimScope(key, None)]
    )
    assert [claim.origin for claim in live] == ["consolidation"]


async def test_one_failing_scope_does_not_stop_the_others(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await _written(db)
    other_org, other_key = await _written(db)
    real = claims.consolidate

    async def flaky(db_, *, organization_id, scope_key):
        if organization_id != other_org.id:
            raise RuntimeError("boom")
        return await real(db_, organization_id=organization_id, scope_key=scope_key)

    monkeypatch.setattr(memory_tasks.claims, "consolidate", flaky)

    done = await memory_tasks.consolidate_memory()

    assert done == 1 and "Memory consolidation failed" in caplog.text
