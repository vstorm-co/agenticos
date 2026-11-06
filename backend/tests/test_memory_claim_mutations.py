"""Mutation guards must account for scope and validity, including stale claim ids."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError
from app.db.models.memory_claim import MemoryClaim
from app.repositories.memory_claim import ClaimScope
from app.services.memory import claims

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("status", "ends", "expected"),
    [
        ("current", None, True),
        ("disputed", None, True),
        ("current", -1, False),
        ("current", 1, True),
        ("superseded", None, False),
        ("retracted", None, False),
        ("merged", None, False),
    ],
)
async def test_only_claims_still_in_use_can_change(
    status: str, ends: int | None, expected: bool
) -> None:
    row = MemoryClaim(
        status=status,
        effective_to=datetime.now(UTC) + timedelta(days=ends) if ends is not None else None,
    )
    assert claims.mutable(row) is expected


async def test_same_scope_sharing_is_refused_before_any_persistence() -> None:
    row = MemoryClaim(id=uuid4(), organization_id=uuid4(), scope_key="org:test", agent_id=None)
    db = AsyncMock()
    with pytest.raises(ConflictError, match="already"):
        await claims.share(
            db, claim=row, to=ClaimScope(row.scope_key, None), author_user_id=uuid4()
        )
    db.execute.assert_not_awaited()
