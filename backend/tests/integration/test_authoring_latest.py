"""Which authoring request and proposal batch is an agent's latest, against Postgres.

Requests and batches written in one transaction must still be told apart by when
they were written: `now()` gives every row in a transaction the same time, and the
newest-first reads would then pick among them in no defined order.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.authoring import AuthoringRequest, BatchStatus, SpecProposalBatch
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import authoring_repo

pytestmark = pytest.mark.anyio


async def _agent(db: AsyncSession) -> tuple[Organization, Agent]:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        visibility="org",
        slug=f"refunds-{uuid.uuid4().hex[:8]}",
        name="Refund desk",
        status="draft",
        draft_spec={"name": "Refund desk"},
    )
    db.add(agent)
    await db.flush()
    return org, agent


async def _request(
    db: AsyncSession, org: Organization, agent: Agent, kind: str
) -> AuthoringRequest:
    return await authoring_repo.create_request(
        db,
        organization_id=org.id,
        kind=kind,
        target="agent",
        agent_id=agent.id,
        skill_id=None,
        context_id=None,
        created_by_user_id=None,
        estimate_usd=Decimal("0.01"),
        window_days=30,
    )


async def _batch(db: AsyncSession, org: Organization, agent: Agent) -> SpecProposalBatch:
    return await authoring_repo.create_batch(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        request_id=None,
        source_started_at=datetime.now(UTC),
        expected_effect="",
        evidence_conversation_ids=[],
    )


async def test_requests_written_in_one_transaction_read_newest_first(db: AsyncSession):
    org, agent = await _agent(db)
    written = [await _request(db, org, agent, kind) for kind in ("improve", "verify") * 3]

    assert all(a.created_at < b.created_at for a, b in pairwise(written))
    listed = await authoring_repo.list_requests(db, organization_id=org.id, agent_id=agent.id)
    assert [request.id for request in listed] == [request.id for request in reversed(written)]


async def test_the_latest_batch_is_the_one_written_last_in_its_transaction(db: AsyncSession):
    org, agent = await _agent(db)
    first = await _batch(db, org, agent)
    await authoring_repo.update_batch(
        db, batch=first, values={"status": BatchStatus.SUPERSEDED.value}
    )
    last = await _batch(db, org, agent)

    assert first.created_at < last.created_at
    latest = await authoring_repo.latest_batch(db, organization_id=org.id, agent_id=agent.id)
    assert latest is not None and latest.id == last.id
