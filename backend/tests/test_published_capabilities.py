"""The chat reads capabilities from the frozen version rather than the draft."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.agent import published_capabilities

pytestmark = pytest.mark.anyio


async def test_enabled_published_bindings_are_distinct_from_disabled_and_absent_ones() -> None:
    version, old = uuid4(), uuid4()
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        (
            version,
            [
                {"id": "sandbox", "enabled": True},
                {"id": "browser_use", "enabled": False},
                {"id": "computer_use"},
            ],
        ),
        (old, None),
    ]
    db.execute.return_value = result
    assert await published_capabilities(db, version_ids=[version, old]) == {
        version: ["sandbox", "computer_use"],
        old: [],
    }


async def test_no_versions_does_not_query_the_database() -> None:
    db = AsyncMock(spec=AsyncSession)
    assert await published_capabilities(db, version_ids=[]) == {}
    db.execute.assert_not_awaited()


async def test_invalid_frozen_metadata_is_not_disguised_as_disabled_tools() -> None:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [(uuid4(), {"invalid": "shape"})]
    db.execute.return_value = result
    with pytest.raises(ValidationError):
        await published_capabilities(db, version_ids=[uuid4()])
