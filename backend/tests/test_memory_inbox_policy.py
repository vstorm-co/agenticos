from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import organization_owner_key
from app.db.models.memory_claim import MemoryClaim, MemoryInboxRule
from app.services import memory_inbox_policy
from app.services.memory_inbox_policy import inbox_source
from app.worker.jobs import SHADOW_MEMORY_INBOX

pytestmark = pytest.mark.anyio


async def test_a_missing_connector_proof_cannot_behave_like_a_reviewed_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MemoryClaim(
        organization_id=uuid4(),
        mail_event_id=uuid4(),
        origin="person",
        author_user_id=uuid4(),
    )
    db = MagicMock(spec=AsyncSession)
    monkeypatch.setattr("app.repositories.memory_claim.mail_event", AsyncMock(return_value=None))
    assert await inbox_source(db, claim) is None


async def test_shadow_model_counts_review_candidates_the_baseline_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, object_id, reviewer = uuid4(), uuid4(), uuid4()
    scope = organization_owner_key(organization)
    prior = MemoryClaim(
        id=uuid4(),
        organization_id=organization,
        scope_key=scope,
        object_id=object_id,
        subject="deadline",
        kind="fact",
        status="current",
        value="2026-12-01",
    )
    contender = MemoryClaim(
        id=uuid4(),
        organization_id=organization,
        scope_key=scope,
        object_id=object_id,
        subject="deadline",
        kind="fact",
        status="disputed",
        value="2026-12-03",
        origin="person",
        author_user_id=reviewer,
    )
    rule = MemoryInboxRule(
        organization_id=organization,
        version=1,
        sources=["reviewed"],
        recipient_ids=[reviewer],
        include_review=False,
        mode="shadow",
    )
    db = MagicMock(spec=AsyncSession)
    queue = AsyncMock()
    monkeypatch.setattr(
        memory_inbox_policy.memory_claim, "inbox_rule", AsyncMock(return_value=rule)
    )
    monkeypatch.setattr(
        memory_inbox_policy.memory_claim,
        "latest_claim_revision",
        AsyncMock(return_value=datetime.now(UTC)),
    )
    monkeypatch.setattr(memory_inbox_policy, "enqueue", queue)
    await memory_inbox_policy.queue_inbox_change(db, claim=contender, previous=prior)
    queue.assert_not_awaited()

    rule.shadow_model_owner_id = reviewer
    await memory_inbox_policy.queue_inbox_change(db, claim=contender, previous=prior)
    queue.assert_awaited_once()
    assert queue.await_args is not None and queue.await_args.args[1] is SHADOW_MEMORY_INBOX
    assert queue.await_args.args[2].change == "review"
