from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory_claim import MemoryClaim
from app.services.memory_inbox_policy import inbox_source

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
